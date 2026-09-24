from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from gjurme.config import Settings
from gjurme.db.models import Article, ArticleEntity, ArticleTopic, Enrichment, Entity
from gjurme.enrichment.pricing import Usage
from gjurme.enrichment.prompt import PROMPT_VERSION
from gjurme.enrichment.providers import FakeProvider, LLMError, LLMResult
from gjurme.enrichment.service import requeue, run_enrichment
from gjurme.ingestion.normalize import normalize_key, sha256_hex
from gjurme.runtime_settings import ENRICHMENT_PAUSE, put_setting
from tests.integration.helpers import add_source

pytestmark = pytest.mark.integration

GOOD = {
    "language": "sq",
    "primary_topic": "crime_justice",
    "secondary_topics": ["politics"],
    "sentiment": "negative",
    "sentiment_score": -0.6,
    "event_type": "investigation_arrest",
    "summary_en": "Police in Prizren arrested two people suspected of smuggling.",
    "entities": [
        {"name": "Policia e Kosovës", "type": "organization"},
        {"name": "Prizren", "type": "location"},
        {"name": "Hashim Invented", "type": "person"},
    ],
    "countries": ["XK"],
    "confidence": 0.85,
}


@dataclass
class ScriptedProvider:
    """Provider returning scripted outcomes; each call pops the next one (repeats the last)."""

    outcomes: list[Any]
    model: str = "claude-sonnet-5"
    name: str = "anthropic"
    calls: int = 0
    usage: Usage = field(
        default_factory=lambda: Usage(input_tokens=300, output_tokens=200, cache_read_tokens=1400)
    )

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        text = outcome if isinstance(outcome, str) else json.dumps(outcome)
        return LLMResult(
            text=text, model=self.model, usage=self.usage, latency_ms=42, request_id="req_x"
        )


def _articles(db: sessionmaker[Session], n: int, *, same_text: bool = False) -> list[int]:
    ids = []
    with db() as s, s.begin():
        src = add_source(s, "src")
        for i in range(n):
            title = (
                "Policia arreston dy persona në Prizren"
                if same_text
                else (f"Policia arreston dy persona në Prizren, rasti {i}")
            )
            art = Article(
                source_id=src.id,
                url=f"https://src.example.com/{i}",
                canonical_url=f"https://src.example.com/{i}",
                url_hash=sha256_hex(str(i)),
                title=title,
                title_normalized=normalize_key(title),
                title_hash=sha256_hex(title),
                excerpt="Policia e Kosovës njoftoi arrestimin për kontrabandë.",
                language="sq",
                published_at=datetime(2026, 9, 24, 10, i % 60, tzinfo=UTC),
                published_date=date(2026, 9, 24),
                content_hash=sha256_hex(title, str(i)),
            )
            s.add(art)
            s.flush()
            ids.append(art.id)
    return ids


def test_successful_enrichment_persists_everything(db, settings: Settings) -> None:
    [aid] = _articles(db, 1)
    stats = run_enrichment(db, settings, ScriptedProvider([GOOD]))
    assert stats.succeeded == 1 and stats.entities_dropped_ungrounded == 1
    with db() as s:
        art = s.get(Article, aid)
        assert art is not None
        assert art.enrichment_status == "succeeded" and art.sentiment_label == "negative"
        assert art.primary_topic is not None and art.primary_topic.slug == "crime_justice"
        assert art.countries == ["XK"] and art.summary_en.startswith("Police in Prizren")
        topics = s.execute(select(ArticleTopic.topic_id, ArticleTopic.is_primary)).all()
        assert len(topics) == 2 and sum(p for _, p in topics) == 1
        names = set(s.scalars(select(Entity.name)))
        assert names == {"Policia e Kosovës", "Prizren"}  # invented person dropped
        enr = s.scalar(select(Enrichment))
        assert enr is not None and enr.is_current and enr.status == "succeeded"
        assert enr.prompt_version == PROMPT_VERSION and enr.model == "claude-sonnet-5"
        assert enr.cost_usd > 0 and enr.latency_ms == 42 and enr.request_id == "req_x"
        assert enr.quality_flags == {"entities_ungrounded": ["Hashim Invented"]}


def test_entities_are_shared_across_articles(db, settings) -> None:
    _articles(db, 3)
    run_enrichment(db, settings, ScriptedProvider([GOOD]))
    with db() as s:
        assert s.scalar(select(func.count()).select_from(Entity)) == 2
        assert s.scalar(select(func.count()).select_from(ArticleEntity)) == 6


def test_identical_content_is_served_from_cache(db, settings) -> None:
    _articles(db, 3, same_text=True)
    provider = ScriptedProvider([GOOD])
    stats = run_enrichment(db, settings.model_copy(update={"enrich_concurrency": 1}), provider)
    assert provider.calls == 1 and stats.cached == 2 and stats.succeeded == 1
    with db() as s:
        statuses = sorted(s.scalars(select(Enrichment.status)))
        assert statuses == ["cached", "cached", "succeeded"]
        assert (
            s.scalar(select(func.sum(Enrichment.cost_usd)).where(Enrichment.status == "cached"))
            == 0
        )


def test_invalid_output_recorded_and_retried_later(db, settings) -> None:
    [aid] = _articles(db, 1)
    stats = run_enrichment(db, settings, ScriptedProvider(["{not json"]))
    assert stats.failed == {"invalid": 1}
    with db() as s:
        art = s.get(Article, aid)
        enr = s.scalar(select(Enrichment))
        assert (
            art is not None and art.enrichment_status == "failed" and art.enrichment_attempts == 1
        )
        assert (
            enr is not None
            and enr.raw_response == "{not json"
            and "malformed JSON" in (enr.error or "")
        )
    # next run retries and succeeds
    run_enrichment(db, settings, ScriptedProvider([GOOD]))
    with db() as s:
        art = s.get(Article, aid)
        assert (
            art is not None
            and art.enrichment_status == "succeeded"
            and art.enrichment_attempts == 2
        )


def test_attempts_exhausted_stop_retries(db, settings) -> None:
    _articles(db, 1)
    cfg = settings.model_copy(update={"enrich_max_attempts": 2})
    for _ in range(4):
        run_enrichment(db, cfg, ScriptedProvider(["garbage"]))
    with db() as s:
        assert s.scalar(select(func.count()).select_from(Enrichment)) == 2


def test_refusal_is_terminal(db, settings) -> None:
    [aid] = _articles(db, 1)
    run_enrichment(
        db,
        settings,
        ScriptedProvider(
            [LLMError("refused", "declined", retryable=False, usage=Usage(input_tokens=100))]
        ),
    )
    with db() as s:
        art = s.get(Article, aid)
        assert art is not None and art.enrichment_status == "skipped"
    assert run_enrichment(db, settings, ScriptedProvider([GOOD])).queued == 0


def test_circuit_breaker_stops_the_stage(db, settings) -> None:
    _articles(db, 20)
    cfg = settings.model_copy(
        update={"enrich_circuit_breaker_threshold": 3, "enrich_concurrency": 1}
    )
    provider = ScriptedProvider([LLMError("overloaded", "529", retryable=True)])
    stats = run_enrichment(db, cfg, provider)
    assert stats.circuit_open and provider.calls == 3


def test_fatal_error_stops_immediately_and_keeps_attempts(db, settings) -> None:
    _articles(db, 5)
    cfg = settings.model_copy(update={"enrich_concurrency": 1})
    provider = ScriptedProvider(
        [LLMError("auth", "invalid x-api-key", retryable=False, fatal=True)]
    )
    stats = run_enrichment(db, cfg, provider)
    assert stats.fatal_error and provider.calls == 1
    with db() as s:
        assert set(s.scalars(select(Article.enrichment_attempts))) == {0}
        assert set(s.scalars(select(Article.enrichment_status))) == {"pending"}


def test_daily_budget_is_enforced(db, settings) -> None:
    _articles(db, 50)
    # Each call's pessimistic estimate is ~$0.018 for sonnet-5 (1500 max output tokens), so a
    # $0.05 budget admits only a couple of calls; the rest stay pending.
    cfg = settings.model_copy(update={"llm_daily_budget_usd": 0.05, "enrich_concurrency": 1})
    provider = ScriptedProvider([GOOD])
    stats = run_enrichment(db, cfg, provider)
    assert stats.budget_exhausted
    assert 1 <= provider.calls <= 20
    with db() as s:
        spent = s.scalar(select(func.sum(Enrichment.cost_usd)))
        assert spent is not None and spent <= Decimal("0.05")
        assert s.scalar(select(func.count()).where(Article.enrichment_status == "pending")) > 0


def test_budget_counts_spend_from_earlier_runs(db, settings) -> None:
    _articles(db, 10)
    cfg = settings.model_copy(update={"llm_daily_budget_usd": 0.04, "enrich_concurrency": 1})
    run_enrichment(db, cfg, ScriptedProvider([GOOD]))
    second = ScriptedProvider([GOOD])
    stats = run_enrichment(db, cfg, second)
    assert stats.budget_exhausted and stats.spent_today_usd > 0


def test_kill_switch(db, settings) -> None:
    _articles(db, 3)
    with db() as s, s.begin():
        put_setting(s, ENRICHMENT_PAUSE, {"paused": True, "reason": "cost review"}, "test")
    provider = ScriptedProvider([GOOD])
    stats = run_enrichment(db, settings, provider)
    assert provider.calls == 0 and "cost review" in (stats.skipped_reason or "")


def test_reenrichment_keeps_history_and_single_current(db, settings) -> None:
    [aid] = _articles(db, 1)
    run_enrichment(db, settings, ScriptedProvider([GOOD]))
    with db() as s, s.begin():
        assert requeue(s, article_ids=[aid]) == 1
    changed = {**GOOD, "primary_topic": "politics", "sentiment": "neutral", "sentiment_score": 0.0}
    run_enrichment(db, settings, ScriptedProvider([changed]))
    with db() as s:
        rows = s.execute(select(Enrichment.is_current, Enrichment.status)).all()
        assert len(rows) == 2 and sum(r.is_current for r in rows) == 1
        art = s.get(Article, aid)
        assert art is not None and art.primary_topic is not None
        assert art.primary_topic.slug == "politics" and art.sentiment_label == "neutral"


def test_hidden_articles_are_never_sent(db, settings) -> None:
    [aid] = _articles(db, 1)
    with db() as s, s.begin():
        art = s.get(Article, aid)
        assert art is not None
        art.is_hidden = True
    assert run_enrichment(db, settings, ScriptedProvider([GOOD])).queued == 0


def test_fake_provider_end_to_end(db, settings) -> None:
    _articles(db, 5)
    stats = run_enrichment(db, settings, FakeProvider())
    assert stats.succeeded == 5 and stats.cost_usd == 0
