from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from gjurme.alerts.engine import Alert, AlertDispatcher, evaluate_run
from gjurme.config import Settings
from gjurme.db.models import (
    AlertEvent,
    Article,
    DataQualityResult,
    Enrichment,
    FeedFetch,
    FeedItem,
    PipelineRun,
    Source,
)
from gjurme.enrichment.providers import FakeProvider
from gjurme.enrichment.service import requeue
from gjurme.pipeline.locking import PIPELINE_LOCK_KEY, advisory_lock
from gjurme.pipeline.retention import apply_retention
from gjurme.pipeline.runner import run_pipeline
from gjurme.pipeline.scheduler import HEARTBEAT_KEY, Scheduler
from gjurme.quality.checks import (
    check_enrichment_backlog,
    check_enrichment_failure_rate,
    check_feed_overflow,
    check_source_freshness,
    run_checks,
)
from gjurme.runtime_settings import RUN_REQUEST, get_setting, put_setting
from tests.conftest import feed_server, fixture_bytes
from tests.integration.helpers import add_source, pubdate, rss

pytestmark = pytest.mark.integration


def _sources(db: sessionmaker[Session], make_fetcher, *, ok: bool = True):  # type: ignore[no-untyped-def]
    with db() as s, s.begin():
        add_source(s, "one", "https://one.example.com/feed/")
        add_source(s, "two", "https://two.example.com/feed/")
    items = [
        {
            "title": f"Lajmi numër {i} për ekonominë e Kosovës",
            "guid": f"g{i}",
            "link": f"https://one.example.com/{i}",
            "pubDate": pubdate(i),
        }
        for i in range(5)
    ]
    routes = {
        "https://one.example.com/feed/": (200 if ok else 500, rss(items), {}),
        "https://two.example.com/feed/": (
            200 if ok else 500,
            fixture_bytes("wordpress_sq.xml", fresh=True),
            {},
        ),
    }
    return make_fetcher(feed_server(routes))


def test_full_run_succeeds_and_is_recorded(db, settings: Settings, make_fetcher) -> None:
    fetcher = _sources(db, make_fetcher)
    result = run_pipeline(settings, db, trigger="test", provider=FakeProvider(), fetcher=fetcher)
    assert result.status == "succeeded"
    assert result.stats["ingest"]["items_new"] == 8
    assert result.stats["process"]["accepted"] == 8
    assert result.stats["enrich"]["succeeded"] == 8
    assert "results" in result.stats["quality"]
    with db() as s:
        run = s.get(PipelineRun, result.run_id)
        assert run is not None and run.status == "succeeded" and run.finished_at
        assert run.stats["enrich"]["succeeded"] == 8
        assert s.scalar(
            select(DataQualityResult.id).where(DataQualityResult.run_id == result.run_id).limit(1)
        )

    again = run_pipeline(settings, db, trigger="test", provider=FakeProvider(), fetcher=fetcher)
    assert again.stats["ingest"]["items_new"] == 0 and again.stats["enrich"]["queued"] == 0


def test_overlapping_run_is_skipped(db, settings, make_fetcher) -> None:
    fetcher = _sources(db, make_fetcher)
    engine = db.kw["bind"]
    with advisory_lock(engine, PIPELINE_LOCK_KEY) as held:
        assert held
        result = run_pipeline(
            settings, db, trigger="test", provider=FakeProvider(), fetcher=fetcher
        )
    assert result.status == "skipped_locked"
    with db() as s:
        assert s.scalar(select(func_count(PipelineRun))) == 1
        assert s.scalar(select(func_count(Article))) == 0  # nothing ran


def func_count(model):  # type: ignore[no-untyped-def]
    from sqlalchemy import func

    return func.count(model.id)


def test_abandoned_runs_are_closed(db, settings, make_fetcher) -> None:
    with db() as s, s.begin():
        s.add(
            PipelineRun(
                trigger="schedule",
                stages=["ingest"],
                status="running",
                started_at=datetime.now(UTC) - timedelta(hours=3),
            )
        )
    fetcher = _sources(db, make_fetcher)
    result = run_pipeline(settings, db, trigger="test", provider=FakeProvider(), fetcher=fetcher)
    assert result.stats["abandoned_runs_closed"] == 1
    with db() as s:
        statuses = sorted(s.scalars(select(PipelineRun.status)))
        assert statuses == ["abandoned", "succeeded"]


def test_all_sources_down_is_partial_and_alerts(db, settings, make_fetcher) -> None:
    fetcher = _sources(db, make_fetcher, ok=False)
    sent: list[httpx.Request] = []

    def hook(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200)

    cfg = settings.model_copy(
        update={"alert_webhook_url": SecretStr("https://hooks.example.com/x")}
    )
    dispatcher = AlertDispatcher(cfg, client=httpx.Client(transport=httpx.MockTransport(hook)))
    result = run_pipeline(
        cfg, db, trigger="test", provider=FakeProvider(), fetcher=fetcher, dispatcher=dispatcher
    )
    assert result.status == "partial"
    assert "all_sources_down" in result.stats["alerts"]
    assert len(sent) >= 1
    # the same condition on the next run is de-duplicated, not re-sent
    run_pipeline(
        cfg, db, trigger="test", provider=FakeProvider(), fetcher=fetcher, dispatcher=dispatcher
    )
    with db() as s:
        events = (
            s.execute(
                select(AlertEvent.suppressed)
                .where(AlertEvent.alert_key == "all_sources_down")
                .order_by(AlertEvent.id)
            )
            .scalars()
            .all()
        )
        assert events == [False, True]


def test_stage_crash_marks_run_failed(db, settings, make_fetcher) -> None:
    fetcher = _sources(db, make_fetcher)

    class Boom:
        model = "fake"
        name = "fake"

        def complete(self, *a, **k):  # type: ignore[no-untyped-def]
            raise RuntimeError("unexpected")

    # A provider exception is contained per-article; to crash the *stage* break the database.
    with db() as s, s.begin():
        s.execute(text("ALTER TABLE core.enrichments RENAME TO enrichments_broken"))
    try:
        result = run_pipeline(settings, db, trigger="test", provider=Boom(), fetcher=fetcher)
    finally:
        with db() as s, s.begin():
            s.execute(text("ALTER TABLE core.enrichments_broken RENAME TO enrichments"))
    assert result.status == "failed"
    assert "enrich" in result.stats["stage_errors"]
    assert result.stats["ingest"]["items_new"] == 8  # earlier stages' work is kept
    assert "pipeline_failed" in result.stats["alerts"]


def test_quality_checks_persist_results(db, settings, make_fetcher) -> None:
    fetcher = _sources(db, make_fetcher)
    run_pipeline(
        settings,
        db,
        trigger="test",
        provider=FakeProvider(),
        fetcher=fetcher,
        stages=["ingest", "process"],
    )
    with db() as s, s.begin():
        results = {r.name: r for r in run_checks(s, None)}
    assert results["raw_rejection_rate_24h"].status == "pass"
    assert results["enrichment_backlog_6h"].status == "pass"
    assert results["enrichment_consistency"].status == "pass"
    assert results["article_volume_anomaly"].details["reason"] == "insufficient history"
    with db() as s, s.begin():
        s.execute(update(Article).values(enrichment_status="succeeded"))  # inconsistent state
        results = {r.name: r for r in run_checks(s, None)}
    assert results["enrichment_consistency"].status == "fail"


def test_backlog_counts_only_articles_still_due_an_analysis(db, settings, make_fetcher) -> None:
    fetcher = _sources(db, make_fetcher)
    run_pipeline(
        settings,
        db,
        trigger="test",
        provider=FakeProvider(),
        fetcher=fetcher,
        stages=["ingest", "process"],
    )
    old = datetime.now(UTC) - timedelta(hours=7)
    with db() as s, s.begin():
        ids = list(s.scalars(select(Article.id).order_by(Article.id)))
        s.execute(update(Article).values(ingested_at=old))
        s.execute(  # attempts used up: nothing will analyse these any more
            update(Article)
            .where(Article.id.in_(ids[:3]))
            .values(enrichment_status="failed", enrichment_attempts=settings.enrich_max_attempts)
        )
        s.execute(  # failed once, will be retried
            update(Article)
            .where(Article.id == ids[3])
            .values(enrichment_status="failed", enrichment_attempts=1)
        )
        backlog = check_enrichment_backlog(s)
    assert backlog.observed == len(ids) - 3


def test_a_source_failing_once_is_no_partial_run_failing_again_is(
    db, settings, make_fetcher
) -> None:
    """An outlet that times out once is back on the next run; SOURCE_FAILURE_PARTIAL_THRESHOLD
    failures in a row are a source failing, and the run says so."""
    with db() as s, s.begin():
        for slug in ("aa", "bb", "cc"):
            add_source(s, slug, f"https://{slug}.example.com/feed/")
    routes = {
        f"https://{slug}.example.com/feed/": (200, fixture_bytes("atom.xml"), {})
        for slug in ("aa", "bb")
    }
    routes["https://cc.example.com/feed/"] = (503, b"busy", {})
    fetcher = make_fetcher(feed_server(routes))
    threshold = settings.source_failure_partial_threshold
    statuses = []
    for _ in range(threshold):
        result = run_pipeline(
            settings,
            db,
            trigger="test",
            provider=FakeProvider(),
            fetcher=fetcher,
            stages=["ingest"],
        )
        statuses.append(result.status)
    assert statuses == ["succeeded"] * (threshold - 1) + ["partial"]
    assert result.stats["ingest"]["sources_failing"] == ["cc"]
    assert result.stats["ingest"]["sources_failed"] == 1


def test_an_auto_disabled_source_probed_again_is_no_partial_run(db, settings, make_fetcher) -> None:
    """An auto-disabled source is fetched again every 6 hours; that it still fails was reported
    when it was disabled, and the freshness check names it with its last error."""
    with db() as s, s.begin():
        add_source(s, "aa", "https://aa.example.com/feed/")
        dead = add_source(s, "dd", "https://dd.example.com/feed/", active=False)
        dead.disabled_reason = (
            "auto-disabled after 20 consecutive failures (last: http_error: HTTP 404)"
        )
        dead.consecutive_failures = 20
        dead.last_fetch_at = datetime.now(UTC) - timedelta(hours=7)
    fetcher = make_fetcher(
        feed_server({"https://aa.example.com/feed/": (200, fixture_bytes("atom.xml"), {})})
    )
    result = run_pipeline(
        settings, db, trigger="test", provider=FakeProvider(), fetcher=fetcher, stages=["ingest"]
    )
    probe = {x["slug"]: x for x in result.stats["ingest"]["per_source"]}["dd"]
    assert probe["reprobe"] and probe["status"] == "http_error"
    assert result.status == "succeeded" and result.stats["ingest"]["sources_failing"] == []
    with db() as s:
        freshness = check_source_freshness(s)
    assert freshness.status == "warn" and freshness.details["auto_disabled"] == ["dd"]
    assert freshness.summary.startswith("not collected: dd auto-disabled (http_error: HTTP 404;")
    # the operator's answer, enabled: false in sources.yaml, ends the warning and the probes
    with db() as s, s.begin():
        s.execute(
            update(Source)
            .where(Source.slug == "dd")
            .values(disabled_reason="disabled in sources.yaml")
        )
        assert check_source_freshness(s).status == "pass"


def test_backlog_leaves_out_articles_queued_again_for_a_better_analysis(
    db, settings, make_fetcher
) -> None:
    """The workflow's "reanalyse" puts every rules-analysed article back in the queue for a
    model; they keep their analysis meanwhile, and with a free quota wait for days by design."""
    fetcher = _sources(db, make_fetcher)
    run_pipeline(settings, db, trigger="test", provider=FakeProvider(), fetcher=fetcher)
    with db() as s, s.begin():
        requeued = requeue(s, provider=FakeProvider.name)
        s.execute(update(Article).values(ingested_at=datetime.now(UTC) - timedelta(hours=7)))
        backlog = check_enrichment_backlog(s)
        assert requeued > 0
        assert backlog.status == "pass" and backlog.observed == 0
        assert backlog.details["awaiting_better_analysis"] == requeued
        # an article that never got any analysis is backlog
        s.execute(
            update(Enrichment)
            .where(Enrichment.article_id == s.scalar(select(func.min(Article.id))))
            .values(is_current=False)
        )
        assert check_enrichment_backlog(s).observed == 1


def test_failure_rate_counts_model_calls_not_quotas_or_rules(db, settings, make_fetcher) -> None:
    fetcher = _sources(db, make_fetcher)
    run_pipeline(
        settings,
        db,
        trigger="test",
        provider=FakeProvider(),
        fetcher=fetcher,
        stages=["ingest", "process"],
    )
    with db() as s, s.begin():
        article_id = s.scalar(select(func.min(Article.id)))
        assert article_id is not None
        made = 0

        def calls(n: int, provider: str, model: str, status: str, error: str | None = None) -> None:
            nonlocal made
            for _ in range(n):
                made += 1
                s.add(
                    Enrichment(
                        article_id=article_id,
                        provider=provider,
                        model=model,
                        prompt_version="v1.0",
                        schema_version="test",
                        status=status,
                        attempt=1,
                        input_hash=f"h{made}",
                        error=error,
                        is_current=False,
                    )
                )
            s.flush()

        calls(60, "fake", "keyword-rules", "succeeded")  # the rules cannot fail
        calls(15, "openai_compatible", "gemini", "failed", "rate_limited: HTTP 429: quota")
        calls(3, "openai_compatible", "gemini", "failed", "server_error: HTTP 503: overloaded")
        few = check_enrichment_failure_rate(s)
        assert few.status == "pass" and "fewer than" in few.details["reason"]  # 3 calls: no rate
        calls(16, "openai_compatible", "gemini", "succeeded")
        calls(1, "openai_compatible", "gemini", "invalid", "missing field")
        result = check_enrichment_failure_rate(s)
    # 4 of 20 model calls; counted with the rules' 60 successes it read 5 %
    assert result.status == "warn" and result.observed == 0.2
    assert result.details["rate_limited"] == 15
    assert result.details["failed_by"] == {"gemini: server_error": 3, "gemini: invalid": 1}
    assert result.summary.startswith("4 of 20 model calls failed (gemini: server_error ×3")


def test_feed_overflow_flags_fetches_where_every_item_was_new(db, settings, make_fetcher) -> None:
    fetcher = _sources(db, make_fetcher)
    run_pipeline(
        settings, db, trigger="test", provider=FakeProvider(), fetcher=fetcher, stages=["ingest"]
    )
    with db() as s, s.begin():
        assert check_feed_overflow(s).status == "pass"  # a source's first fetch is all new
        first = s.scalar(select(FeedFetch).order_by(FeedFetch.id))
        assert first is not None and first.items_seen >= 5
        s.add(
            FeedFetch(
                source_id=first.source_id,
                started_at=datetime.now(UTC),
                duration_ms=10,
                status="ok",
                items_seen=10,
                items_new=10,
            )
        )
        s.flush()
        result = check_feed_overflow(s)
    assert result.status == "warn" and result.details["sources"][0]["fetches"] == 1
    assert result.summary.startswith("published more between two runs than the feed lists: ")


def test_a_busy_short_feed_is_read_again_at_the_end_of_the_run(db, settings, make_fetcher) -> None:
    """Zëri lists 10 items without a page 2, and was all new one run after the previous one:
    it is read once more at the end of each run, so the next overflow has less time to happen.
    Other sources are read once."""
    with db() as s, s.begin():
        busy = add_source(s, "busy", "https://busy.example.com/rss/")
        add_source(s, "calm", "https://calm.example.com/feed/")
        now = datetime.now(UTC)
        for minutes_ago, new in ((40, 3), (25, 10)):  # 10 of 10 new, one run after the last
            s.add(
                FeedFetch(
                    source_id=busy.id,
                    started_at=now - timedelta(minutes=minutes_ago),
                    duration_ms=10,
                    status="ok",
                    items_seen=10,
                    items_new=new,
                )
            )
    items = [
        {
            "title": f"Lajmi {i} nga Prishtina për zgjedhjet",
            "guid": f"z{i}",
            "link": f"https://busy.example.com/{i}",
            "pubDate": pubdate(i / 10),
        }
        for i in range(10)
    ]
    routes = {
        "https://busy.example.com/rss/": (200, rss(items), {}),
        "https://calm.example.com/feed/": (200, fixture_bytes("atom.xml"), {}),
    }
    requested: list[str] = []
    serve = feed_server(routes)

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return serve(request)

    off = settings.model_copy(update={"ingest_second_read": False})
    result = run_pipeline(
        off, db, trigger="test", provider=FakeProvider(), fetcher=make_fetcher(handler)
    )
    assert "second_read" not in result.stats

    on = settings.model_copy(update={"ingest_second_read_after_minutes": 0})
    requested.clear()
    result = run_pipeline(
        on, db, trigger="test", provider=FakeProvider(), fetcher=make_fetcher(handler)
    )
    assert result.stats["second_read"]["sources"] == ["busy"]
    assert result.stats["second_read"]["per_source"] == {"busy": "ok"}
    assert requested.count("https://busy.example.com/rss/") == 2
    assert requested.count("https://calm.example.com/feed/") == 1
    with db() as s:
        reads = s.scalars(
            select(FeedFetch.status).where(
                FeedFetch.run_id == result.run_id, FeedFetch.source_id == busy.id
            )
        ).all()
    assert list(reads) == ["ok", "ok"]


def test_feed_overflow_after_a_gap_says_nothing_about_the_feed(db, settings, make_fetcher) -> None:
    """Nov 2026: Dukagjini, re-enabled after hours auto-disabled, was all new (50 of 50). The gap
    was the problem, and the freshness check reported it; the feed lists enough."""
    fetcher = _sources(db, make_fetcher)
    run_pipeline(
        settings, db, trigger="test", provider=FakeProvider(), fetcher=fetcher, stages=["ingest"]
    )
    with db() as s, s.begin():
        s.execute(update(FeedFetch).values(started_at=FeedFetch.started_at - timedelta(hours=5)))
        first = s.scalar(select(FeedFetch).order_by(FeedFetch.id))
        assert first is not None
        s.add(
            FeedFetch(
                source_id=first.source_id,
                started_at=datetime.now(UTC),
                duration_ms=10,
                status="ok",
                items_seen=50,
                items_new=50,
            )
        )
        s.flush()
        result = check_feed_overflow(s)
    assert result.status == "pass" and result.summary == ""
    assert [r["after_gap"] for r in result.details["after_gap"]] == [1]


def test_retention_purges_only_old_data(db, settings, make_fetcher) -> None:
    fetcher = _sources(db, make_fetcher)
    run_pipeline(settings, db, trigger="test", provider=FakeProvider(), fetcher=fetcher)
    with db() as s, s.begin():
        s.execute(
            update(FeedItem)
            .where(FeedItem.id <= 3)
            .values(first_seen_at=datetime.now(UTC) - timedelta(days=40))
        )
        with_excerpt = list(
            s.scalars(select(Article.id).where(Article.excerpt.is_not(None)).limit(3))
        )
        s.execute(
            update(Article)
            .where(Article.id.in_(with_excerpt))
            .values(ingested_at=datetime.now(UTC) - timedelta(days=100))
        )
        # never analysed (attempts used up): its publisher text goes after 90 days all the same
        s.execute(
            update(Article)
            .where(Article.id == with_excerpt[2])
            .values(enrichment_status="failed", enrichment_attempts=3)
        )
        dry = apply_retention(s, settings, dry_run=True)
    assert dry["raw_payloads_purged"] == 3 and dry["excerpts_purged"] == 3
    with db() as s, s.begin():
        apply_retention(s, settings)
    with db() as s:
        assert s.scalar(select(func_count(FeedItem)).where(FeedItem.payload.is_(None))) == 3
        assert s.scalar(select(func_count(Article)).where(Article.excerpt.is_(None))) >= 3
        assert s.scalar(select(func_count(Article))) == 8  # metadata is kept forever


def test_scheduler_tick_runs_when_due_and_on_request(
    db, settings, make_fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "gjurme.pipeline.scheduler.run_pipeline", lambda _s, _f, trigger: calls.append(trigger)
    )
    sched = Scheduler(settings, db)
    assert sched.tick() is True  # first tick: due immediately
    assert sched.tick() is False  # not due again for SCHEDULER_INTERVAL_MINUTES
    with db() as s, s.begin():
        put_setting(s, RUN_REQUEST, {"pending": True, "by": "admin"}, "test")
    assert sched.tick() is True
    assert calls == ["schedule", "admin"]
    with db() as s:
        assert get_setting(s, HEARTBEAT_KEY) is not None
        assert get_setting(s, RUN_REQUEST)["pending"] is False  # type: ignore[index]
        assert get_setting(s, "retention_last_run") is not None


def test_database_size_check_warns_before_a_free_tier_is_full(
    db, settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from gjurme.quality.checks import check_database_size

    def with_limit(mb: int) -> None:
        cfg = settings.model_copy(update={"db_size_limit_mb": mb})
        monkeypatch.setattr("gjurme.quality.checks.get_settings", lambda: cfg)

    with db() as s:  # the real database: without a limit the size is only recorded
        with_limit(0)
        unlimited = check_database_size(s)
        assert unlimited.status == "pass" and unlimited.observed and unlimited.observed > 0

    def of_size(mb: float) -> Any:  # a session whose database is exactly this big
        return SimpleNamespace(
            execute=lambda _q: SimpleNamespace(scalar_one=lambda: mb * 1_048_576)
        )

    with_limit(1000)
    assert check_database_size(of_size(500)).status == "pass"
    warn = check_database_size(of_size(850))
    assert (warn.status, warn.observed, warn.threshold) == ("warn", 850.0, 800.0)
    assert warn.details == {"limit_mb": 1000, "used": 0.85}
    assert check_database_size(of_size(960)).status == "fail"
    alerts = evaluate_run(
        "succeeded",
        {
            "quality": {
                "results": [
                    {
                        "name": "database_size",
                        "status": "warn",
                        "observed": 850.0,
                        "threshold": 800.0,
                    }
                ]
            }
        },
    )
    assert [a.key for a in alerts] == ["dq:database_size"]  # the warning is the time to act


def test_dispatcher_records_delivery_failure(db, settings) -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    cfg = settings.model_copy(
        update={"alert_webhook_url": SecretStr("https://hooks.example.com/x")}
    )
    dispatcher = AlertDispatcher(cfg, client=httpx.Client(transport=httpx.MockTransport(failing)))
    with db() as s, s.begin():
        [event] = dispatcher.dispatch(s, [Alert("k", "warning", "T", "M")])
    assert not event.delivered and event.delivery_error == "HTTP 500"


def test_engine_session_defaults(engine) -> None:  # type: ignore[no-untyped-def]
    """Every app connection gets the guard rails and always plans with real parameters."""
    from gjurme.db.session import build_engine
    from tests.conftest import TEST_DATABASE_URL

    eng = build_engine(TEST_DATABASE_URL, statement_timeout_ms=1234)
    try:
        with eng.connect() as conn:
            got = conn.execute(
                text(
                    "SELECT current_setting('plan_cache_mode'), current_setting('TimeZone'), "
                    "current_setting('statement_timeout')"
                )
            ).one()
    finally:
        eng.dispose()
    assert tuple(got) == ("force_custom_plan", "UTC", "1234ms")


def test_dead_man_check_is_pinged_after_each_run(db, settings, make_fetcher, monkeypatch) -> None:
    pings: list[str] = []
    monkeypatch.setattr("gjurme.pipeline.runner.httpx.get", lambda url, **_: pings.append(url))
    cfg = settings.model_copy(update={"healthcheck_ping_url": "https://hc.example/abc/"})
    fetcher = _sources(db, make_fetcher)
    run_pipeline(cfg, db, trigger="test", provider=FakeProvider(), fetcher=fetcher)

    def broken(*_a: object, **_k: object) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("gjurme.pipeline.runner.process_pending", broken)
    assert run_pipeline(cfg, db, trigger="test", stages=["process"]).status == "failed"
    assert pings == ["https://hc.example/abc", "https://hc.example/abc/fail"]
