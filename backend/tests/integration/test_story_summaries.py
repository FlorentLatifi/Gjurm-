"""The SUMMARIZE stage against PostgreSQL: which stories, what is stored, quota, the API."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from gjurme.api.app import create_app
from gjurme.config import Settings
from gjurme.db.models import Article, LLMQuota, Source, Story
from gjurme.enrichment.pricing import Usage
from gjurme.enrichment.providers import FakeProvider, LLMError, LLMResult
from gjurme.enrichment.quota import QuotaConfig
from gjurme.ingestion.normalize import normalize_key, sha256_hex
from gjurme.stories.summaries import due_stories, summarize_stage

pytestmark = pytest.mark.integration

TZ = ZoneInfo("Europe/Tirane")
GOOD = {
    "summary_sq": "Qeveria e Kosovës ndaloi tregtimin e energjisë elektrike me kompanitë "
    "serbe, me vendim të marrë në mbledhjen e djeshme.",
    "summary_en": "Kosovo's government banned electricity trading with Serbian companies, "
    "in a decision taken at yesterday's meeting.",
}


@dataclass
class Scripted:
    """Answers in turn (the last one repeats); an exception is raised instead."""

    answers: list[Any]
    model: str = "free-model"
    name: str = "openai_compatible"
    calls: list[str] = field(default_factory=list)

    def complete(self, system: str, user: str, schema: dict[str, Any], **_: Any) -> LLMResult:
        self.calls.append(user)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return LLMResult(
            text=json.dumps(answer, ensure_ascii=False), model=self.model, usage=Usage(),
            latency_ms=5,
        )  # fmt: skip


def _source(s: Session, slug: str) -> Source:
    src = Source(
        slug=slug,
        name=slug.title(),
        homepage_url=f"https://{slug}.example.com/",
        feed_url=f"https://{slug}.example.com/feed/",
        language="sq",
        country="XK",
    )
    s.add(src)
    s.flush()
    return src


def _story(s: Session, sources: list[Source], *, days_ago: int = 0, title: str = "") -> int:
    at = datetime.now(UTC) - timedelta(days=days_ago, hours=1)
    story = Story(
        first_published_at=at, last_published_at=at, published_date=at.astimezone(TZ).date()
    )
    s.add(story)
    s.flush()
    for i, src in enumerate(sources):
        headline = title or "Qeveria e Kosovës ndalon tregtimin e energjisë me kompanitë serbe"
        art = Article(
            source_id=src.id,
            story_id=story.id,
            url=f"https://{src.slug}.example.com/{story.id}",
            canonical_url=f"https://{src.slug}.example.com/{story.id}",
            url_hash=sha256_hex(src.slug, str(story.id)),
            title=f"{headline} ({src.name})",
            title_normalized=normalize_key(headline),
            title_hash=sha256_hex(headline, src.slug),
            excerpt="Qeveria e Kosovës në mbledhjen e djeshme mori vendimin për ndalimin e "
            "tregtimit të energjisë elektrike me kompanitë serbe.",
            language="sq",
            published_at=at + timedelta(minutes=i),
            published_date=at.astimezone(TZ).date(),
            content_hash=sha256_hex(headline, src.slug, str(story.id)),
        )
        s.add(art)
    s.flush()
    return story.id


@pytest.fixture
def stories(db: sessionmaker[Session]) -> dict[str, Any]:
    with db() as s, s.begin():
        srcs = [_source(s, slug) for slug in ("koha", "telegrafi", "zeri", "kallxo", "rtsh")]
        return {
            "sources": [x.id for x in srcs],
            "two": _story(s, srcs[:2]),
            "five": _story(s, srcs, title="Kuvendi i Kosovës miraton buxhetin"),
            "one": _story(s, srcs[:1], title="Lajm i vetëm"),
            "old": _story(s, srcs[:3], days_ago=5, title="Lajm i vjetër"),
        }


def _chain(provider: Any, settings: Settings) -> list[tuple[Any, QuotaConfig]]:
    return [(provider, QuotaConfig.for_model(settings))]


def test_due_stories_are_the_front_pages_most_covered_first(db, settings, stories) -> None:
    with db() as s:
        due = due_stories(s, settings, limit=10)
    assert due == [(stories["five"], 5), (stories["two"], 2)]  # not one outlet, not old


def test_a_summary_is_stored_and_shown_as_the_storys(db, settings, stories) -> None:
    provider = Scripted([GOOD])
    stats = summarize_stage(db, settings, _chain(provider, settings))
    assert stats["stored"] == 2 and stats["requests"] == 2 and stats["due"] == 2
    assert 'outlet="Koha"' in provider.calls[0] and "<headline>" in provider.calls[0]
    with db() as s:
        story = s.get(Story, stories["two"])
        assert story is not None and story.summary_sq == GOOD["summary_sq"]
        assert story.summary_outlets == 2 and story.summary_model == "free-model"
        quota = s.scalar(select(LLMQuota).where(LLMQuota.model == "free-model"))
        assert quota is not None and quota.requests == 2  # counted in the model's quota
    client = TestClient(create_app(settings, db))
    body = client.get(f"/api/v1/stories/{stories['two']}").json()
    assert body["summary_scope"] == "story" and body["summary_outlets"] == 2
    assert body["summary_sq"] == GOOD["summary_sq"]
    # nothing is due again until more outlets join
    assert summarize_stage(db, settings, _chain(Scripted([GOOD]), settings))["due"] == 0


def test_a_grown_story_is_written_again(db, settings, stories) -> None:
    summarize_stage(db, settings, _chain(Scripted([GOOD]), settings))
    with db() as s, s.begin():
        s.execute(
            update(Story)
            .where(Story.id == stories["two"])
            .values(summary_at=datetime.now(UTC) - timedelta(hours=3))
        )
        joining = Article.source_id.in_(stories["sources"][2:])
        s.execute(
            update(Article)
            .where(Article.story_id == stories["five"], joining)
            .values(story_id=stories["two"])
        )
    stats = summarize_stage(db, settings, _chain(Scripted([GOOD]), settings))
    assert stats["stored"] == 1 and stats["rewritten"] == 1
    with db() as s:
        story = s.get(Story, stories["two"])
        assert story is not None and story.summary_outlets == 5


def test_an_invented_name_is_not_stored(db, settings, stories) -> None:
    invented = {**GOOD, "summary_sq": "Albin Kurti njoftoi se Qeveria ndaloi tregtimin e "
                "energjisë me kompanitë serbe."}  # fmt: skip
    stats = summarize_stage(db, settings, _chain(Scripted([invented]), settings))
    assert stats["stored"] == 0 and stats["rejected"] == {"not in the reports": 2}
    with db() as s:
        assert s.get(Story, stories["two"]).summary_sq is None  # type: ignore[union-attr]
    client = TestClient(create_app(settings, db))
    body = client.get(f"/api/v1/stories/{stories['two']}").json()
    assert body["summary_scope"] is None  # no article summary either: no model analysed them


def test_a_used_up_quota_hands_over_to_the_next_model(db, settings, stories) -> None:
    first = Scripted([LLMError("rate_limited", "429 for the day", retryable=True)])
    second = Scripted([GOOD], model="second-model")
    config = QuotaConfig.for_model(settings)
    stats = summarize_stage(db, settings, [(first, config), (second, config)])
    assert stats["rate_limited"] and stats["stored"] == 2
    assert stats["models"] == {"second-model": 2}
    with db() as s:
        limited = s.scalar(select(LLMQuota).where(LLMQuota.model == "free-model"))
        assert limited is not None and limited.limited_at is not None


def test_the_run_cap_and_the_rules(db, settings, stories) -> None:
    capped = settings.model_copy(update={"story_summary_max_per_run": 1})
    stats = summarize_stage(db, capped, _chain(Scripted([GOOD]), capped))
    assert stats["stored"] == 1 and stats["due"] == 1
    rules = summarize_stage(db, settings, _chain(FakeProvider(), settings))
    assert rules["stored"] == 0 and "keyword rules" in rules["skipped"]


def test_the_pipeline_runs_the_stage_before_enrich(db, settings, stories) -> None:
    from gjurme.pipeline.runner import ALL_STAGES, run_pipeline

    assert ALL_STAGES.index("summarize") < ALL_STAGES.index("enrich")
    result = run_pipeline(settings, db, trigger="test", stages=["summarize"])
    assert result.status == "succeeded"
    assert "keyword rules" in result.stats["summarize"]["skipped"]
