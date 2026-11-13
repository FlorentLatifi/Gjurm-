from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from gjurme.config import Settings
from gjurme.db.models import Article, ArticleEntity, ArticleTopic, Enrichment, Entity
from gjurme.enrichment.pricing import Usage
from gjurme.enrichment.prompt import PROMPT_VERSION
from gjurme.enrichment.providers import FakeProvider, LLMError, LLMResult
from gjurme.enrichment.service import enrich_stage, requeue, run_enrichment
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
    "summary_sq": "Policia në Prizren arrestoi dy persona të dyshuar për kontrabandë.",
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
        assert art.summary_sq is not None and art.summary_sq.startswith("Policia në Prizren")
        topics = s.execute(select(ArticleTopic.topic_id, ArticleTopic.is_primary)).all()
        assert len(topics) == 2 and sum(p for _, p in topics) == 1
        names = set(s.scalars(select(Entity.name)))
        assert names == {"Policia e Kosovës", "Prizren"}  # invented person dropped
        enr = s.scalar(select(Enrichment))
        assert enr is not None and enr.is_current and enr.status == "succeeded"
        assert enr.prompt_version == PROMPT_VERSION and enr.model == "claude-sonnet-5"
        assert enr.cost_usd > 0 and enr.latency_ms == 42 and enr.request_id == "req_x"
        assert enr.quality_flags == {"entities_ungrounded": ["Hashim Invented"]}


def test_common_nouns_are_dropped_and_flagged(db, settings: Settings) -> None:
    _articles(db, 1)
    out = {
        **GOOD,
        "entities": [
            {"name": "Prizren", "type": "location"},
            {"name": "policët", "type": "person"},
            {"name": "qytetarëve", "type": "person"},
        ],
    }
    stats = run_enrichment(db, settings, ScriptedProvider([out]))
    assert stats.succeeded == 1 and stats.entities_dropped_not_proper == 2
    with db() as s:
        assert set(s.scalars(select(Entity.name))) == {"Prizren"}
        enr = s.scalar(select(Enrichment))
        assert enr is not None
        assert enr.quality_flags == {"entities_not_proper": ["policët", "qytetarëve"]}


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


def test_low_confidence_counts_a_model_not_the_keyword_rules(db, settings) -> None:
    """The keyword rules are unsure by design and say so on the page; the check is for a model."""
    from gjurme.quality.checks import check_low_confidence

    ids = _articles(db, 4)
    run_enrichment(db, settings, FakeProvider(), article_ids=ids[:2])
    with db() as s:
        rules_only = check_low_confidence(s)
    assert rules_only.status == "pass" and rules_only.details["rule_based"] == 2
    unsure = {**GOOD, "confidence": 0.2}
    run_enrichment(db, settings, ScriptedProvider([unsure]), article_ids=ids[2:])
    with db() as s:
        result = check_low_confidence(s)
    assert (result.status, result.observed) == ("warn", 1.0)
    assert result.details == {"low_confidence": 2, "enriched": 2, "rule_based": 2}


def test_a_used_up_quota_is_not_a_failure_rate(db, settings) -> None:
    """A free tier's quota runs out daily (429): the check is for a model that really fails."""
    from gjurme.quality.checks import check_enrichment_failure_rate

    ids = _articles(db, 4)
    run_enrichment(db, settings, ScriptedProvider([GOOD, GOOD]), article_ids=ids[:2])
    quota = LLMError("rate_limited", "HTTP 429: quota", retryable=True)
    run_enrichment(db, settings, ScriptedProvider([quota]), article_ids=ids[2:3])
    with db() as s:
        result = check_enrichment_failure_rate(s)
    assert (result.status, result.observed) == ("pass", 0.0)
    assert result.details == {"failed": 0, "attempts": 2, "rate_limited": 1}
    broken = LLMError("server_error", "HTTP 500", retryable=True)
    run_enrichment(db, settings, ScriptedProvider([broken]), article_ids=ids[3:])
    with db() as s:
        result = check_enrichment_failure_rate(s)
    assert result.status == "fail" and result.details["failed"] == 1


def test_rule_based_share_warns_only_where_a_model_is_configured(
    db, settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every article ends up analysed whichever model stopped, so the share of the keyword
    rules is the only sign that the models no longer cover the news."""
    from gjurme.quality import checks

    ids = _articles(db, 20)
    model = settings.model_copy(update={"llm_provider": "openai_compatible"})
    monkeypatch.setattr(checks, "get_settings", lambda: model)
    run_enrichment(db, settings, ScriptedProvider([GOOD] * 8), article_ids=ids[:8])
    run_enrichment(db, settings, FakeProvider(), article_ids=ids[8:])
    with db() as s:
        mixed = checks.check_rule_based_share(s)
    assert (mixed.status, mixed.observed) == ("warn", 0.6)
    assert mixed.details == {"rule_based": 12, "analysed": 20}

    run_enrichment(db, settings, FakeProvider(), article_ids=ids[:7])
    with db() as s:
        assert checks.check_rule_based_share(s).status == "fail"  # 19 of 20: alerts
        rules_mode = settings.model_copy(update={"llm_provider": "fake"})
        monkeypatch.setattr(checks, "get_settings", lambda: rules_mode)
        chosen = checks.check_rule_based_share(s)
    assert (chosen.status, chosen.severity, chosen.observed) == ("pass", "info", 0.95)


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


def test_used_up_rate_limit_stops_and_keeps_attempts(db, settings) -> None:
    """A free tier's daily quota (429 after the provider's own retries) is not the articles'
    fault: the stage stops, and no article loses an attempt to it."""
    _articles(db, 5)
    cfg = settings.model_copy(update={"enrich_concurrency": 1})
    provider = ScriptedProvider([LLMError("rate_limited", "HTTP 429: quota", retryable=True)])
    stats = run_enrichment(db, cfg, provider)
    assert stats.rate_limited and not stats.circuit_open and provider.calls == 1
    assert stats.as_dict()["rate_limited"] is True
    with db() as s:
        assert set(s.scalars(select(Article.enrichment_attempts))) == {0}
        assert set(s.scalars(select(Article.enrichment_status))) == {"pending"}
    # the next run, with quota again, analyses them all
    assert run_enrichment(db, cfg, ScriptedProvider([GOOD])).succeeded == 5


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


def test_local_model_end_to_end_is_free_and_counted_as_ai(db, settings) -> None:
    """A local model over the OpenAI-compatible API: stored like Claude, priced at zero."""
    import httpx

    from gjurme.analytics.queries import analysis_mode
    from gjurme.enrichment.pricing import register_price
    from gjurme.enrichment.providers import OpenAICompatibleProvider

    def answer(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(GOOD)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1900, "completion_tokens": 260},
            },
        )

    register_price("local-test:4b", 0, 0)
    provider = OpenAICompatibleProvider(
        base_url="http://ollama:11434/v1",
        model="local-test:4b",
        max_output_tokens=1500,
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(answer),
    )
    ids = _articles(db, 3)
    stats = run_enrichment(db, settings, provider)
    assert stats.succeeded == 3 and stats.cost_usd == 0 and stats.entities_dropped_ungrounded == 3

    with db() as s:
        rows = s.scalars(select(Enrichment).where(Enrichment.article_id.in_(ids))).all()
        assert {(r.provider, r.model, r.cost_usd) for r in rows} == {
            ("openai_compatible", "local-test:4b", Decimal(0))
        }
        assert s.get(Article, ids[0]).enrichment_status == "succeeded"
        mode = analysis_mode(s, date(2026, 9, 25))
        assert mode["mode"] == "ai" and mode["model"] == "local-test:4b"


def test_two_runs_at_once_record_every_call(db, settings) -> None:
    """A unique index allows one current analysis per article; the second run's insert used to
    raise, fail the stage and drop paid calls from the day's spend."""
    import threading
    import time

    ids = _articles(db, 12)

    class Slow(ScriptedProvider):
        def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
            time.sleep(0.03)  # both runs are mid-call on the same articles
            return super().complete(system, user, schema)

    providers = [Slow([GOOD]), Slow([GOOD])]
    errors: list[BaseException] = []

    def run(provider: Slow) -> None:
        try:
            run_enrichment(db, settings.model_copy(update={"enrich_concurrency": 4}), provider)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(p,)) for p in providers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with db() as s:
        recorded = s.scalar(select(func.count()).select_from(Enrichment))
        current = s.execute(
            select(Enrichment.article_id, func.count())
            .where(Enrichment.is_current.is_(True))
            .group_by(Enrichment.article_id)
        ).all()
    assert recorded == sum(p.calls for p in providers)  # every paid call is in the spend
    assert sorted(a for a, _ in current) == ids and all(n == 1 for _, n in current)


def test_time_limit_leaves_the_rest_for_the_next_run(db, settings) -> None:
    import time

    _articles(db, 6)

    class Slow(ScriptedProvider):
        def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
            time.sleep(0.6)
            return super().complete(system, user, schema)

    cfg = settings.model_copy(update={"enrich_max_seconds": 1, "enrich_concurrency": 1})
    stats = run_enrichment(db, cfg, Slow([GOOD]))
    assert stats.time_limited and stats.queued == 6 and 1 <= stats.attempted < 6
    with db() as s:
        waiting = s.scalar(
            select(func.count()).select_from(Article).where(Article.enrichment_status == "pending")
        )
    assert waiting == 6 - stats.attempted


def test_first_claude_call_of_a_run_goes_alone(db, settings) -> None:
    """The cached system prompt is readable only once a response has started: sent together,
    the first calls of a run would each pay a cache write."""
    import threading
    import time

    _articles(db, 5)
    spans: list[tuple[float, float]] = []
    lock = threading.Lock()

    class Timed(ScriptedProvider):
        def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
            start = time.monotonic()
            time.sleep(0.05)
            result = super().complete(system, user, schema)
            with lock:
                spans.append((start, time.monotonic()))
            return result

    run_enrichment(db, settings.model_copy(update={"enrich_concurrency": 4}), Timed([GOOD]))
    spans.sort()
    first_end = spans[0][1]
    assert len(spans) == 5 and all(start >= first_end for start, _ in spans[1:])
    assert any(b[0] < a[1] for a, b in pairwise(spans[1:]))  # then in parallel


# --- the fallback chain: first model, fallback model, keyword rules ---------------------------
QUOTA = LLMError("rate_limited", "HTTP 429: quota", retryable=True)


def _age(db: sessionmaker[Session], ids: list[int], hours: float) -> None:
    with db() as s, s.begin():
        s.execute(
            update(Article)
            .where(Article.id.in_(ids))
            .values(ingested_at=datetime.now(UTC) - timedelta(hours=hours))
        )


def _with_fallback(settings: Settings, monkeypatch: pytest.MonkeyPatch, fallback: Any) -> Settings:
    monkeypatch.setattr("gjurme.enrichment.service.build_fallback_provider", lambda _s: fallback)
    return settings.model_copy(update={"enrich_concurrency": 1})


def test_fallback_model_takes_over_when_the_quota_is_used_up(db, settings, monkeypatch) -> None:
    ids = _articles(db, 4)
    backup = ScriptedProvider([GOOD], model="llama-backup", name="openai_compatible")
    cfg = _with_fallback(settings, monkeypatch, backup)
    result = enrich_stage(db, cfg, ScriptedProvider([QUOTA]))
    assert result["rate_limited"] and not result["circuit_open"]
    assert result["fallback"]["succeeded"] == 4 and backup.calls == 4
    assert "rules" not in result
    with db() as s:
        models = set(s.scalars(select(Enrichment.model).where(Enrichment.is_current)))
        assert models == {"llama-backup"}
        assert {s.get(Article, i).enrichment_status for i in ids} == {"succeeded"}  # type: ignore[union-attr]


def test_no_fallback_while_the_first_model_works(db, settings, monkeypatch) -> None:
    _articles(db, 3)
    backup = ScriptedProvider([GOOD], model="llama-backup", name="openai_compatible")
    cfg = _with_fallback(settings, monkeypatch, backup)
    result = enrich_stage(db, cfg, ScriptedProvider([GOOD]))
    assert result["succeeded"] == 3 and "fallback" not in result and backup.calls == 0


def test_rules_analyse_what_no_model_could_in_time(db, settings, monkeypatch) -> None:
    old = _articles(db, 3)
    _age(db, old[:2], hours=2)
    cfg = _with_fallback(settings, monkeypatch, None).model_copy(
        update={"enrich_rules_after_minutes": 60}
    )
    result = enrich_stage(db, cfg, ScriptedProvider([QUOTA]))
    assert result["rules"]["succeeded"] == 2
    with db() as s:
        providers = dict(
            s.execute(
                select(Enrichment.article_id, Enrichment.provider).where(Enrichment.is_current)
            ).all()
        )
        assert providers == {old[0]: "fake", old[1]: "fake"}
        fresh = s.get(Article, old[2])
        assert fresh is not None and fresh.enrichment_status == "pending"  # still the model's


def test_rules_leave_articles_that_wait_for_a_better_analysis(db, settings, monkeypatch) -> None:
    """After `reanalyse`, articles keep their rule analysis until the model reaches them; the
    rules must not take them back."""
    ids = _articles(db, 2)
    run_enrichment(db, settings, FakeProvider())
    with db() as s, s.begin():
        assert requeue(s, provider="fake") == 2
    _age(db, ids, hours=5)
    cfg = _with_fallback(settings, monkeypatch, None).model_copy(
        update={"enrich_rules_after_minutes": 60}
    )
    result = enrich_stage(db, cfg, ScriptedProvider([QUOTA]))
    assert "rules" not in result
    with db() as s:
        assert set(s.scalars(select(Article.enrichment_status))) == {"pending"}


def test_rules_never_run_when_the_rules_are_the_model(db, settings, monkeypatch) -> None:
    ids = _articles(db, 2)
    _age(db, ids, hours=2)
    cfg = settings.model_copy(update={"enrich_rules_after_minutes": 60})
    result = enrich_stage(db, cfg, FakeProvider())
    assert result["succeeded"] == 2 and "rules" not in result and "fallback" not in result
