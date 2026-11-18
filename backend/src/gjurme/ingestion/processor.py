"""PROCESS stage: ``raw.feed_items`` → ``core.articles``.

Cleans, validates and deduplicates. Every raw item ends in exactly one terminal state —
``accepted``, ``updated``, ``duplicate`` or ``rejected`` (with a reason) — nothing is silently
dropped. Each item is processed inside a SAVEPOINT so one bad item cannot abort the batch.

Deduplication layers (see docs/BLUEPRINT.md §6):
    L1 raw (source, item_key)             — enforced at ingest
    L2 canonical URL hash                 — unique constraint on core.articles.url_hash
    L3 same source + title hash ±48 h     — republished / slug-edited articles
    L3b same source + edited headline ±6 h — typo / ending / one word; hidden, duplicate_of_id
    L4 cross-source near-duplicate titles — pg_trgm similarity, linked via duplicate_of_id
"""

from __future__ import annotations

import difflib
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from gjurme.config import Settings
from gjurme.db.models import Article, FeedItem, Source
from gjurme.ingestion.normalize import (
    InvalidURLError,
    canonical_url,
    clean_excerpt,
    clean_text,
    normalize_key,
    normalize_url,
    resolve_published_at,
    sha256_hex,
)

log = logging.getLogger(__name__)

TITLE_DEDUP_WINDOW = timedelta(hours=48)
# Calibrated on real headline pairs (see docs/DECISIONS.md, ADR-008): *different* events whose
# titles differ only by a place name score 0.74–0.85 trigram similarity, while genuine rewrites
# of the same story by another outlet score 0.43–0.68. Trigram similarity therefore only
# identifies near-verbatim copies, and a candidate is accepted only if the words that differ
# are noise (labels like "VIDEO", short stopwords) — never a content word such as a place.
NEAR_DUP_SIMILARITY = 0.8
NEAR_DUP_MIN_WORDS = 4
NOISE_TOKENS = frozenset(
    {
        "video",
        "foto",
        "fotot",
        "live",
        "lajm",
        "lajmi",
        "update",
        "ekskluzive",
        "ekskluzivisht",
        "breaking",
        "urgjent",
        "bomba",
        "shikoni",
        "lexoni",
        "detajet",
        "zyrtare",
        "zyrtarisht",
    }
)


def is_near_verbatim(a: str, b: str) -> bool:
    """True when two normalized titles differ only by noise tokens."""
    diff = set(a.split()) ^ set(b.split())
    return all(tok in NOISE_TOKENS or (len(tok) <= 2 and tok.isalpha()) for tok in diff)


# L3b — the same outlet re-publishing one article with its headline edited: a typo fixed
# ("nacionalisteserbe" → "nacionaliste serbe"), an ending changed ("skandaloze" → "skandaloz" →
# "skandal"), a word added ("si u kënga" → "si u përzgjodh kënga"). The feed gives the edit a new
# URL and guid, so L1–L3 see a new article. Calibrated on the live archive (ADR-034): in five
# weeks every edit came within 2.3 h of the first version (most within a minute), while the same
# outlet's look-alike headlines further apart were different articles (hourly turnout figures,
# "sonte në Konfront", a visit announced the day before).
REVISION_WINDOW = timedelta(hours=3)
REVISION_MAX_CHANGED_WORDS = 2
REVISION_MIN_WORDS = 5
REVISION_HIDDEN_REASON = "duplicate: same outlet, edited headline (L3b)"
# Live blogs and running updates re-publish one headline with a word changed, and each entry is
# a new article: a headline with one of these is never folded into another.
LIVE_MARKERS = frozenset(
    {"live", "drejtperdrejt", "minute", "perditesim", "perditesohet", "update", "ndiqni"}
)
# Words whose change makes another headline even when nothing else changed (folded forms).
_CONTENT_WORDS = frozenset(
    {
        # negations: "do të marrë pjesë" ≠ "nuk do të marrë pjesë"
        "nuk", "s", "jo", "mos", "pa", "as", "asnje", "askush", "kurre", "aspak",
        # counts and ordinals: series ("Pjesa e parë" / "e dytë"), prizes, tolls
        "dy", "tre", "tri", "kater", "pese", "gjashte", "shtate", "tete", "nente", "dhjete",
        "pare", "dyte", "trete", "katert", "peste", "fundit",
        # time: a preview ("nesër", "sonte") and the report on the day are two articles
        "sot", "neser", "dje", "sonte", "mbreme", "pasneser", "paradite", "pasdite",
    }
)  # fmt: skip
_ROMAN = re.compile(r"^[ivxlc]{2,}$")  # Pjesa II, III (one letter is a word: "i")


def _is_content_token(tok: str) -> bool:
    """A word whose change makes a different headline: a number ("3" ≠ "5" të vdekur), a count,
    an ordinal, a Roman numeral, a negation or a day."""
    return any(ch.isdigit() for ch in tok) or tok in _CONTENT_WORDS or bool(_ROMAN.match(tok))


def _edit_distance(a: str, b: str, limit: int) -> int:
    """Levenshtein distance, stopping once it exceeds ``limit``."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def _same_word(a: str, b: str) -> bool:
    """One word typed or inflected differently: a typo (≤ 1 letter, ≤ 2 in words of 7+) or a
    changed ending on a shared stem of ≥ 5 letters that covers most of the longer word
    (skandaloze / skandaloz / skandal, Kosova / Kosovës), never presidenti / presioni. Short
    particles (e / të, i / u) may replace each other."""
    shorter = min(len(a), len(b))
    if shorter >= 4 and _edit_distance(a, b, 2) <= (2 if shorter >= 7 else 1):
        return True
    if len(a) <= 2 and len(b) <= 2 and a.isalpha() and b.isalpha():
        return True
    stem = next((i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), shorter)
    return stem >= 5 and stem >= 0.6 * max(len(a), len(b))


def is_headline_revision(a: str, b: str) -> bool:
    """True when two normalized titles *of one outlet* are one headline edited: at most
    ``REVISION_MAX_CHANGED_WORDS`` words changed, each change a typo, a changed ending, words
    split or joined, a particle, a noise label, or (once) one word added or removed. Numbers,
    counts, ordinals, negations, days and live markers always make two headlines different."""
    ta, tb = a.split(), b.split()
    if a == b or min(len(ta), len(tb)) < REVISION_MIN_WORDS:
        return a == b
    if LIVE_MARKERS.intersection(ta) or LIVE_MARKERS.intersection(tb):
        return False
    changed = added = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        old, new = ta[i1:i2], tb[j1:j2]
        if all(tok in NOISE_TOKENS for tok in old + new):
            continue  # "VIDEO", "FOTO" added or dropped
        if any(_is_content_token(tok) for tok in old + new):
            return False
        changed += max(len(old), len(new))
        if len(old) == len(new):
            if not all(_same_word(x, y) for x, y in zip(old, new, strict=True)):
                return False
        elif old and new:  # words split or joined: "nacionalisteserbe" / "nacionaliste serbe"
            if not _same_word("".join(old), "".join(new)):
                return False
        elif len(old + new) == 1:
            # one word added or removed; a particle ("e", "i") does not count as a word
            added += len((old + new)[0]) > 2
        else:
            return False
    return changed <= REVISION_MAX_CHANGED_WORDS and added <= 1


MIN_TITLE_CHARS = 8
MAX_TITLE_CHARS = 500


@dataclass(slots=True)
class ProcessStats:
    processed: int = 0
    accepted: int = 0
    updated: int = 0
    duplicates: Counter[str] = field(default_factory=Counter)
    rejected: Counter[str] = field(default_factory=Counter)
    date_issues: Counter[str] = field(default_factory=Counter)
    near_duplicates: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "processed": self.processed,
            "accepted": self.accepted,
            "updated": self.updated,
            "duplicates": dict(self.duplicates),
            "duplicates_total": sum(self.duplicates.values()),
            "rejected": dict(self.rejected),
            "rejected_total": sum(self.rejected.values()),
            "date_issues": dict(self.date_issues),
            "near_duplicates_linked": self.near_duplicates,
        }


@dataclass(frozen=True, slots=True)
class Candidate:
    title: str
    title_normalized: str
    title_hash: str
    url: str
    canonical_url: str
    url_hash: str
    excerpt: str | None
    author: str | None
    categories: list[str]
    language: str
    published_at: datetime
    published_estimated: bool
    content_hash: str
    image_url: str | None = None


class ItemRejectedError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def build_candidate(
    item: FeedItem, source: Source, settings: Settings, date_issues: Counter[str]
) -> Candidate:
    """Pure transformation + validation of one raw item. Raises ``ItemRejectedError``."""
    payload = item.payload or {}
    title = clean_text(payload.get("title"))
    if not title:
        raise ItemRejectedError("missing_title")
    if len(title) < MIN_TITLE_CHARS:
        raise ItemRejectedError("title_too_short")
    if len(title) > MAX_TITLE_CHARS:
        title = title[:MAX_TITLE_CHARS]

    link = payload.get("link") or item.link
    if not link:
        raise ItemRejectedError("missing_url")
    try:
        url = normalize_url(link, base=source.homepage_url)
        canon = canonical_url(url)
    except InvalidURLError as exc:
        raise ItemRejectedError(f"invalid_url: {exc}") from exc

    parsed_dt = None
    if payload.get("published_iso"):
        try:
            parsed_dt = datetime.fromisoformat(payload["published_iso"])
        except ValueError:
            parsed_dt = None
    published_at, estimated, issue = resolve_published_at(parsed_dt, item.first_seen_at)
    if issue:
        date_issues[issue] += 1
    if published_at < item.first_seen_at - timedelta(days=settings.max_item_age_days):
        raise ItemRejectedError("too_old")

    excerpt = clean_excerpt(payload.get("summary"), settings.excerpt_max_chars) or None
    if excerpt and normalize_key(excerpt) == normalize_key(title):
        excerpt = None
    title_norm = normalize_key(title)
    author = clean_text(payload.get("author"))[:200] or None
    categories = [c for c in (clean_text(t)[:80] for t in payload.get("tags") or []) if c][:20]
    return Candidate(
        title=title,
        title_normalized=title_norm,
        title_hash=sha256_hex(title_norm),
        url=url,
        canonical_url=canon,
        url_hash=sha256_hex(canon),
        excerpt=excerpt,
        author=author,
        categories=categories,
        language=source.language,
        published_at=published_at,
        published_estimated=estimated,
        content_hash=sha256_hex(title, excerpt or ""),
        image_url=_image_url(payload.get("image")),
    )


def _image_url(value: Any) -> str | None:
    """The feed's photo address, as the parser kept it (absolute https, bounded)."""
    ok = isinstance(value, str) and value.startswith("https://")
    return value if ok and len(value) <= 1000 else None


def _find_same_source_title_dup(session: Session, source_id: int, cand: Candidate) -> int | None:
    return session.scalar(
        select(Article.id)
        .where(
            Article.source_id == source_id,
            Article.title_hash == cand.title_hash,
            Article.published_at.between(
                cand.published_at - TITLE_DEDUP_WINDOW, cand.published_at + TITLE_DEDUP_WINDOW
            ),
        )
        .order_by(Article.id)
        .limit(1)
    )


@dataclass(frozen=True, slots=True)
class RevisionRow:
    """An article of the outlet published near a candidate: ``root_id`` is the article readers
    see (the row itself, or the one an earlier revision was folded into)."""

    id: int
    root_id: int
    title_normalized: str
    published_at: datetime


def find_revision_root(title_normalized: str, rows: list[RevisionRow]) -> int | None:
    """The visible article whose headline ``title_normalized`` revises, if any: the root of the
    first row that matches (the same outlet's articles in the window, nearest first)."""
    for row in rows:
        if is_headline_revision(row.title_normalized, title_normalized):
            return row.root_id
    return None


def _find_same_source_revision(
    session: Session, source_id: int, cand: Candidate
) -> RevisionRow | None:
    """L3b: the outlet's visible article whose headline this one edits (±REVISION_WINDOW).

    Folded revisions are compared too, so a third edit matches whichever earlier wording it is
    closest to. Returns the root with the newest ``published_at`` of its group, so the caller
    knows whether the candidate is the newest wording."""
    rows = session.execute(
        select(
            Article.id,
            Article.duplicate_of_id,
            Article.is_hidden,
            Article.hidden_reason,
            Article.title_normalized,
            Article.published_at,
        )
        .where(
            Article.source_id == source_id,
            Article.published_at.between(
                cand.published_at - REVISION_WINDOW, cand.published_at + REVISION_WINDOW
            ),
        )
        .order_by(Article.id)
    ).all()
    group: list[RevisionRow] = []
    for r in rows:
        if not r.is_hidden:
            group.append(RevisionRow(r.id, r.id, r.title_normalized, r.published_at))
        elif r.hidden_reason == REVISION_HIDDEN_REASON and r.duplicate_of_id is not None:
            group.append(
                RevisionRow(r.id, int(r.duplicate_of_id), r.title_normalized, r.published_at)
            )
    group.sort(key=lambda g: abs(g.published_at - cand.published_at))
    root_id = find_revision_root(cand.title_normalized, group)
    if root_id is None:
        return None
    members = [g for g in group if g.root_id == root_id]
    root = next((g for g in members if g.id == root_id), None)
    if root is None:  # matched a revision whose original is older than the window
        shown = session.get(Article, root_id)
        if shown is None or shown.is_hidden:  # taken down: the item stays an article
            return None
        root = RevisionRow(shown.id, shown.id, shown.title_normalized, shown.published_at)
        members.append(root)
    newest = max(g.published_at for g in members)
    return RevisionRow(root.id, root.id, root.title_normalized, newest)


def _find_cross_source_near_dup(session: Session, source_id: int, cand: Candidate) -> int | None:
    """Needs the similarity threshold set in the transaction (``_set_near_dup_threshold``)."""
    if len(cand.title_normalized.split()) < NEAR_DUP_MIN_WORDS:
        return None
    rows = session.execute(
        select(Article.id, Article.duplicate_of_id, Article.title_normalized)
        .where(
            Article.source_id != source_id,
            Article.title_normalized.op("%")(cand.title_normalized),
            Article.published_at.between(
                cand.published_at - TITLE_DEDUP_WINDOW, cand.published_at + TITLE_DEDUP_WINDOW
            ),
        )
        .order_by(
            func.similarity(Article.title_normalized, cand.title_normalized).desc(),
            Article.published_at,
        )
        .limit(5)
    ).all()
    for row in rows:
        if is_near_verbatim(row.title_normalized, cand.title_normalized):
            return int(row.duplicate_of_id or row.id)
    return None


def _set_near_dup_threshold(session: Session) -> None:
    """The ``%`` operator's threshold, for the rest of the transaction: once per batch, not per
    item, since from a runner far from the database every statement is a round trip."""
    session.execute(
        text("SELECT set_config('pg_trgm.similarity_threshold', :t, true)"),
        {"t": str(NEAR_DUP_SIMILARITY)},
    )


def _local_date(dt: datetime, tz: ZoneInfo) -> Any:
    return dt.astimezone(tz).date()


def process_item(
    session: Session,
    item: FeedItem,
    source: Source,
    settings: Settings,
    stats: ProcessStats,
    tz: ZoneInfo,
) -> None:
    now = datetime.now(UTC)
    try:
        cand = build_candidate(item, source, settings, stats.date_issues)
    except ItemRejectedError as rej:
        item.process_status, item.rejection_reason = "rejected", rej.reason
        item.processed_at = now
        stats.rejected[rej.reason.split(":")[0]] += 1
        return

    # L2 — canonical URL already known?
    existing = session.scalar(select(Article).where(Article.url_hash == cand.url_hash))
    if existing is not None:
        item.article_id = existing.id
        item.processed_at = now
        title_changed = existing.title_normalized != cand.title_normalized
        excerpt_changed = bool(cand.excerpt) and cand.excerpt != existing.excerpt
        if existing.source_id == source.id and cand.image_url and not existing.image_url:
            # an entry seen again now carries a photo (or was stored before photos were kept)
            existing.image_url = cand.image_url
        if existing.source_id == source.id and (title_changed or excerpt_changed):
            # Publisher corrected the entry. Never downgrade: a missing excerpt in the new
            # version keeps the stored one.
            existing.title, existing.title_normalized = cand.title, cand.title_normalized
            existing.title_hash = cand.title_hash
            existing.excerpt = cand.excerpt or existing.excerpt
            existing.content_hash = sha256_hex(existing.title, existing.excerpt or "")
            if title_changed and existing.enrichment_status != "pending":
                # A corrected headline can change topics/entities → re-enrich.
                existing.enrichment_status, existing.enrichment_attempts = "pending", 0
            item.process_status = "updated"
            stats.updated += 1
        else:
            item.process_status = "duplicate"
            item.rejection_reason = "dup_l2_url"
            stats.duplicates["l2_url"] += 1
        return

    # L3 — same source, same headline, within 48 h (republished / URL slug edited)
    same = _find_same_source_title_dup(session, source.id, cand)
    if same is not None:
        item.article_id, item.processed_at = same, now
        item.process_status, item.rejection_reason = "duplicate", "dup_l3_title"
        stats.duplicates["l3_title"] += 1
        return

    # L3b — same source, the headline edited (typo, ending, one word), within a few hours:
    # stored hidden and linked to the article readers see, which takes the newest wording.
    revision = _find_same_source_revision(session, source.id, cand)
    if revision is not None:
        _store_revision(session, item, source, cand, revision, tz, now)
        stats.duplicates["l3_revision"] += 1
        return

    # L4 — cross-source near-duplicate (kept, but linked to the earliest story)
    near = _find_cross_source_near_dup(session, source.id, cand)

    stmt = (
        insert(Article)
        .values(**_article_values(item, source, cand, tz), duplicate_of_id=near)
        .on_conflict_do_nothing(index_elements=[Article.url_hash])
        .returning(Article.id)
    )
    article_id = session.scalar(stmt)
    if article_id is None:  # lost a race with a concurrent writer — treat as L2 duplicate
        item.article_id = session.scalar(
            select(Article.id).where(Article.url_hash == cand.url_hash)
        )
        item.process_status, item.rejection_reason = "duplicate", "dup_l2_url"
        item.processed_at = now
        stats.duplicates["l2_url"] += 1
        return
    item.article_id, item.processed_at = article_id, now
    item.process_status, item.rejection_reason = "accepted", None
    stats.accepted += 1
    if near is not None:
        stats.near_duplicates += 1


def _article_values(
    item: FeedItem, source: Source, cand: Candidate, tz: ZoneInfo
) -> dict[str, Any]:
    return {
        "source_id": source.id,
        "url": cand.url,
        "canonical_url": cand.canonical_url,
        "url_hash": cand.url_hash,
        "guid": item.guid,
        "title": cand.title,
        "title_normalized": cand.title_normalized,
        "title_hash": cand.title_hash,
        "excerpt": cand.excerpt,
        "author": cand.author,
        "feed_categories": cand.categories,
        "language": cand.language,
        "published_at": cand.published_at,
        "published_date": _local_date(cand.published_at, tz),
        "published_at_estimated": cand.published_estimated,
        "content_hash": cand.content_hash,
        "image_url": cand.image_url,
    }


def adopt_wording(root: Article, title: str, excerpt: str | None) -> None:
    """The visible article takes a revision's headline (and excerpt, if it has one).

    Not re-analysed: a revision differs by a typo, an ending or one word, and a new analysis
    would spend a free model's daily quota on the same news."""
    root.title, root.title_normalized = title, normalize_key(title)
    root.title_hash = sha256_hex(root.title_normalized)
    root.excerpt = excerpt or root.excerpt
    root.content_hash = sha256_hex(root.title, root.excerpt or "")


def _store_revision(
    session: Session,
    item: FeedItem,
    source: Source,
    cand: Candidate,
    revision: RevisionRow,
    tz: ZoneInfo,
    now: datetime,
) -> None:
    """Keep the revision as a hidden row linked to the visible article (``duplicate_of_id``):
    nothing counts it, its URL stays known, and an operator can unhide it."""
    article_id = session.scalar(
        insert(Article)
        .values(
            **_article_values(item, source, cand, tz),
            duplicate_of_id=revision.id,
            is_hidden=True,
            hidden_reason=REVISION_HIDDEN_REASON,
            enrichment_status="skipped",
        )
        .on_conflict_do_nothing(index_elements=[Article.url_hash])
        .returning(Article.id)
    )
    if article_id is not None and cand.published_at >= revision.published_at:
        root = session.get(Article, revision.id)
        if root is not None:
            adopt_wording(root, cand.title, cand.excerpt)
    item.article_id = article_id or session.scalar(
        select(Article.id).where(Article.url_hash == cand.url_hash)
    )
    item.processed_at = now
    item.process_status, item.rejection_reason = "duplicate", "dup_l3_revision"


def process_pending(
    session: Session, settings: Settings, *, batch_size: int = 500, max_items: int = 20_000
) -> ProcessStats:
    """Process pending raw items in batches; commits after each batch."""
    stats = ProcessStats()
    tz = ZoneInfo(settings.timezone)
    sources: dict[int, Source] = {s.id: s for s in session.scalars(select(Source))}
    while stats.processed < max_items:
        items = list(
            session.scalars(
                select(FeedItem)
                .where(FeedItem.processed_at.is_(None))
                .order_by(FeedItem.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        if not items:
            break
        _set_near_dup_threshold(session)
        for item in items:
            source = sources[item.source_id]
            try:
                with session.begin_nested():
                    process_item(session, item, source, settings, stats, tz)
            except Exception as exc:
                log.exception("processing item failed", extra={"feed_item_id": item.id})
                item.process_status = "rejected"
                item.rejection_reason = f"processing_error: {type(exc).__name__}"[:200]
                item.processed_at = datetime.now(UTC)
                stats.rejected["processing_error"] += 1
            stats.processed += 1
        session.commit()
    log.info("processing done", extra=stats.as_dict())
    return stats
