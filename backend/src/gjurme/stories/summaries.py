"""The SUMMARIZE stage: what happened, in two or three sentences, for each story (ADR-035).

A story card showed the summary of one article: its representative's, which the keyword rules
leave empty. On 2026-11-18 two of the front page's top 30 stories had one. Readers saw how the
outlets differed, not what had happened. This stage writes one summary per story from every
outlet's headline and opening lines, in Albanian and English:

* **Which stories.** Those the front page shows: at least ``STORY_SUMMARY_MIN_OUTLETS``
  outlets, started in the last ``STORY_SUMMARY_DAYS`` local days. Unsummarised ones first, the
  most covered first; a story is written again once ``STORY_SUMMARY_REGROW_OUTLETS`` more
  outlets have joined (and two hours have passed), because a developing story changes.
* **One request per story,** not per article: about 250 a day at November 2026's volume, which
  fits a free model's daily quota. The stage runs before ENRICH and counts its requests in the
  same per-model quota (enrichment/quota.py, ADR-033), so the articles get what is left.
* **No invention.** The model gets only the reports and must use only facts in them. Its
  Albanian summary is checked like extracted names are (grounding.py): every capitalised word
  past the start of a sentence must appear in the reports, inflection allowed, and every number
  too. A summary that fails is not stored, and the story keeps the lead article's summary.
* **Disclosed.** The API says whose summary it is (``summary_scope``: ``story`` or
  ``article``) and from how many outlets; the site labels it as written by a model.

The keyword rules write no summaries: nothing is better than a fake one. A paid model writes
them only when ``STORY_SUMMARY_WITH_PAID_MODEL`` allows it (their cost is not in the
enrichment ledger the daily budget reads).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from gjurme.config import Settings
from gjurme.enrichment.grounding import PREFIX, _token_matches, _tokens
from gjurme.enrichment.providers import LLMError, LLMProvider
from gjurme.enrichment.quota import QuotaConfig, begin_run, note

log = logging.getLogger(__name__)

PROMPT_VERSION = "story-v1"
MAX_OUTLETS = 12  # reports given to the model: one per outlet, the earliest
EXCERPT_CHARS = 280
MIN_CHARS = 40
MAX_CHARS = 420
MAX_OUTPUT_TOKENS = 1200  # room for a reasoning model's thinking (gpt-oss on Groq)

SYSTEM_PROMPT = """You write neutral news summaries for GJURMË, a site that shows how \
Albanian-language outlets in Kosovo, Albania and North Macedonia covered the same event.

You get the headlines and opening lines that several outlets published about ONE event. \
Write what happened, in two or three short sentences:
- Use only facts stated in the reports. Never add a name, number, date, place, title or cause \
that is not in them, and no background knowledge.
- Neutral wording: no judging adjectives ("scandalous", "shameful"), no loaded words. \
Attribute claims and reactions to who made them ("X said", "according to the police").
- If the reports disagree on a fact (numbers, who did what), say that reports differ.
- Do not mention the outlets, the headlines or that this is a summary.
- summary_sq: in Albanian, at most 380 characters. Keep names as the reports spell them.
- summary_en: the same in English, at most 380 characters.
Answer with the JSON object only."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary_sq", "summary_en"],
    "properties": {
        "summary_sq": {"type": "string", "description": "2-3 sentences in Albanian"},
        "summary_en": {"type": "string", "description": "The same in English"},
    },
}

_DUE_SQL = """
    WITH cand AS (
      SELECT st.id, st.summary_at, st.summary_outlets
      FROM core.stories st
      WHERE st.published_date >= :start AND st.merged_into_id IS NULL),
    agg AS (
      SELECT a.story_id, count(DISTINCT a.source_id) AS outlets, max(a.published_at) AS last_at
      FROM core.articles a JOIN cand ON cand.id = a.story_id
      WHERE NOT a.is_hidden AND a.published_date >= :start
      GROUP BY a.story_id)
    SELECT agg.story_id, agg.outlets
    FROM agg JOIN cand ON cand.id = agg.story_id
    WHERE agg.outlets >= :min_outlets
      AND (cand.summary_at IS NULL
           OR (agg.outlets >= cand.summary_outlets + :regrow
               AND cand.summary_at < :written_before))
    ORDER BY cand.summary_at IS NULL DESC, agg.outlets DESC, agg.last_at DESC, agg.story_id
    LIMIT :limit
"""

_REPORTS_SQL = """
    SELECT DISTINCT ON (a.source_id) a.source_id, s.name AS outlet, a.title, a.excerpt,
           a.published_at
    FROM core.articles a JOIN core.sources s ON s.id = a.source_id
    WHERE a.story_id = :story_id AND NOT a.is_hidden
    ORDER BY a.source_id, a.published_at, a.id
"""

_SENTENCE_END = re.compile(r"[.!?:;…\"“”«»]\s*$")
_WORD = re.compile(r"[^\W\d_][\w'’-]*|\d[\d.,:]*", re.UNICODE)
_NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")


class InvalidSummaryError(ValueError):
    """The model's answer cannot be stored."""


@dataclass(slots=True)
class SummaryStats:
    due: int = 0
    requests: int = 0
    stored: int = 0
    rewritten: int = 0  # of those: stories summarised before, grown since
    rejected: Counter[str] = field(default_factory=Counter)
    failed: Counter[str] = field(default_factory=Counter)
    models: Counter[str] = field(default_factory=Counter)
    rate_limited: bool = False
    quota_capped: bool = False
    time_limited: bool = False
    skipped: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "due": self.due,
            "requests": self.requests,
            "stored": self.stored,
            "rewritten": self.rewritten,
            "rejected": dict(self.rejected),
            "failed": dict(self.failed),
            "models": dict(self.models),
            "rate_limited": self.rate_limited,
            "quota_capped": self.quota_capped,
            "time_limited": self.time_limited,
            "skipped": self.skipped,
        }


@dataclass(frozen=True, slots=True)
class StoryInput:
    story_id: int
    outlets: int
    message: str
    source_text: str


def due_stories(
    session: Session, settings: Settings, *, limit: int, now: datetime | None = None
) -> list[tuple[int, int]]:
    """(story id, outlets) of the stories to summarise, in order: never summarised first, then
    grown ones; the most covered first."""
    now = now or datetime.now(UTC)
    today = now.astimezone(ZoneInfo(settings.timezone)).date()
    rows = session.execute(
        text(_DUE_SQL),
        {
            "start": today - timedelta(days=settings.story_summary_days - 1),
            "min_outlets": settings.story_summary_min_outlets,
            "regrow": settings.story_summary_regrow_outlets,
            "written_before": now - timedelta(hours=2),
            "limit": limit,
        },
    )
    return [(r.story_id, r.outlets) for r in rows]


def story_input(session: Session, story_id: int, timezone: str) -> StoryInput | None:
    """The reports the model gets: one per outlet (its first), earliest first, at most
    ``MAX_OUTLETS``; and the text the summary is checked against."""
    reports = sorted(
        session.execute(text(_REPORTS_SQL), {"story_id": story_id}).mappings(),
        key=lambda r: r["published_at"],
    )
    if not reports:
        return None
    tz = ZoneInfo(timezone)
    parts = []
    for r in reports[:MAX_OUTLETS]:
        excerpt = (r["excerpt"] or "").strip()
        if len(excerpt) > EXCERPT_CHARS:
            excerpt = excerpt[:EXCERPT_CHARS].rsplit(" ", 1)[0] + "…"
        when = r["published_at"].astimezone(tz).strftime("%d.%m %H:%M")
        parts.append(
            f'<report outlet="{escape(r["outlet"], quote=True)}" time="{when}">\n'
            f"<headline>{escape(r['title'])}</headline>\n"
            + (f"<opening>{escape(excerpt)}</opening>\n" if excerpt else "")
            + "</report>"
        )
    message = (
        f"Reports of {len(reports)} outlets about one event"
        + (f" (the first {MAX_OUTLETS} shown)" if len(reports) > MAX_OUTLETS else "")
        + ":\n\n"
        + "\n".join(parts)
    )
    source_text = "\n".join(f"{r['title']}\n{r['excerpt'] or ''}" for r in reports)
    return StoryInput(story_id, len(reports), message, source_text)


def _json_object(raw: str | None) -> dict[str, Any]:
    text_ = (raw or "").strip()
    if text_.startswith("```"):
        text_ = text_.strip("`")
    start, end = text_.find("{"), text_.rfind("}")
    if start < 0 or end < start:
        raise InvalidSummaryError("no JSON object")
    try:
        data = json.loads(text_[start : end + 1])
    except json.JSONDecodeError as exc:
        raise InvalidSummaryError(f"malformed JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise InvalidSummaryError("not an object")
    return data


def _clean(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise InvalidSummaryError(f"{name} missing")
    cleaned = " ".join(value.split())
    if not MIN_CHARS <= len(cleaned) <= MAX_CHARS:
        raise InvalidSummaryError(f"{name} length {len(cleaned)}")
    return cleaned


def ungrounded(summary: str, source_text: str) -> list[str]:
    """Words of ``summary`` the reports do not contain: capitalised words past the start of a
    sentence (names, places, institutions), checked with inflection like extracted names, and
    numbers, checked as they are written."""
    text_tokens = set(_tokens(source_text))
    text_prefixes = {t[:PREFIX] for t in text_tokens if len(t) >= PREFIX}
    numbers = set(_NUMBER.findall(source_text))
    missing: list[str] = []
    sentence_start = True
    for match in _WORD.finditer(summary):
        word = match.group(0)
        before = summary[: match.start()]
        if before and _SENTENCE_END.search(before):
            sentence_start = True
        if word[0].isdigit():
            if word.rstrip(".,:") not in numbers:
                missing.append(word)
        elif word[0].isupper() and not sentence_start:
            name_tokens = [t for t in _tokens(word) if len(t) >= 3]
            if name_tokens and not all(
                _token_matches(t, text_tokens, text_prefixes) for t in name_tokens
            ):
                missing.append(word)
        sentence_start = False
    return missing


def parse_summary(raw: str | None, source_text: str) -> tuple[str, str]:
    """(summary_sq, summary_en) from the model's answer; raises ``InvalidSummaryError``."""
    data = _json_object(raw)
    sq = _clean(data.get("summary_sq"), "summary_sq")
    en = _clean(data.get("summary_en"), "summary_en")
    missing = ungrounded(sq, source_text)
    if missing:
        raise InvalidSummaryError("not in the reports: " + ", ".join(dict.fromkeys(missing)))
    numbers = set(_NUMBER.findall(source_text))
    stray = [n for n in _NUMBER.findall(en) if n not in numbers]
    if stray:
        raise InvalidSummaryError("numbers not in the reports: " + ", ".join(stray))
    return sq, en


def _store(session: Session, item: StoryInput, sq: str, en: str, model: str, now: datetime) -> bool:
    """Store the summary; True when the story had one before."""
    before = session.execute(
        text("SELECT summary_at IS NOT NULL FROM core.stories WHERE id = :id"),
        {"id": item.story_id},
    ).scalar()
    session.execute(
        text("""
        UPDATE core.stories SET summary_sq = :sq, summary_en = :en, summary_model = :model,
               summary_at = :now, summary_outlets = :outlets
        WHERE id = :id"""),
        {
            "sq": sq,
            "en": en,
            "model": model,
            "now": now,
            "outlets": item.outlets,
            "id": item.story_id,
        },
    )
    return bool(before)


def summarize_stage(
    session_factory: Any,
    settings: Settings,
    providers: list[tuple[LLMProvider, QuotaConfig]],
) -> dict[str, Any]:
    """Summarise the due stories with the first provider, then the next when its quota or this
    run's share of it is used up. Requests count in each model's daily quota."""
    stats = SummaryStats()
    if not settings.story_summaries or settings.story_summary_max_per_run == 0:
        stats.skipped = "disabled"
        return stats.as_dict()
    models = [(p, c) for p, c in providers if p.name != "fake"]
    if not models:
        stats.skipped = "no model (the keyword rules write no summaries)"
        return stats.as_dict()
    if not settings.story_summary_with_paid_model:
        models = [(p, c) for p, c in models if p.name != "anthropic"]
        if not models:
            stats.skipped = "paid model (STORY_SUMMARY_WITH_PAID_MODEL is off)"
            return stats.as_dict()
    started = time.monotonic()
    with session_factory() as s:
        due = due_stories(s, settings, limit=settings.story_summary_max_per_run)
    stats.due = len(due)
    queue = list(due)
    for provider, quota_config in models:
        if not queue:
            break
        with session_factory() as s, s.begin():
            plan = begin_run(s, provider.model, quota_config, datetime.now(UTC))
        allowed = len(queue) if plan.cap is None else max(plan.cap, 0)
        if plan.limited:
            allowed = min(allowed, 1)  # a 429 for the day: one request finds out if it passed
        sent = 0
        while queue and sent < allowed:
            if time.monotonic() - started > settings.story_summary_max_seconds:
                stats.time_limited = True
                return stats.as_dict()
            story_id, _ = queue[0]
            with session_factory() as s:
                item = story_input(s, story_id, settings.timezone)
            if item is None:
                queue.pop(0)
                continue
            try:
                result = provider.complete(
                    SYSTEM_PROMPT, item.message, OUTPUT_SCHEMA, max_output_tokens=MAX_OUTPUT_TOKENS
                )
            except LLMError as exc:
                if exc.kind == "rate_limited":
                    stats.rate_limited = True
                    if exc.limit_scope != "minute":
                        with session_factory() as s, s.begin():
                            note(s, provider.model, datetime.now(UTC), limited=True)
                    log.warning(
                        "story summaries: rate limit, next model",
                        extra={"model": provider.model, "scope": exc.limit_scope},
                    )
                    break  # this model is done for the run; the story stays in the queue
                answered = 0 if exc.kind in ("connection", "unexpected") else 1
                stats.requests += answered
                stats.failed[exc.kind] += 1
                with session_factory() as s, s.begin():
                    note(s, provider.model, datetime.now(UTC), requests=answered)
                if exc.fatal:
                    break
                queue.pop(0)  # a failed story waits for the next run
                sent += 1
                continue
            sent += 1
            stats.requests += 1
            queue.pop(0)
            now = datetime.now(UTC)
            try:
                sq, en = parse_summary(result.text, item.source_text)
            except InvalidSummaryError as exc:
                stats.rejected[str(exc).split(":")[0]] += 1
                log.info(
                    "story summary rejected",
                    extra={"story_id": item.story_id, "reason": str(exc)[:300]},
                )
                with session_factory() as s, s.begin():
                    note(s, provider.model, now, requests=1, cleared=plan.limited)
                continue
            with session_factory() as s, s.begin():
                note(s, provider.model, now, requests=1, cleared=plan.limited)
                stats.rewritten += _store(s, item, sq, en, result.model or provider.model, now)
            stats.stored += 1
            stats.models[result.model or provider.model] += 1
        if queue and sent >= allowed and plan.cap is not None:
            stats.quota_capped = True
    log.info("story summaries", extra={k: v for k, v in stats.as_dict().items() if v})
    return stats.as_dict()
