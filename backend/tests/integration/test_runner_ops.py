from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session, sessionmaker

from gjurme.alerts.engine import Alert, AlertDispatcher
from gjurme.config import Settings
from gjurme.db.models import AlertEvent, Article, DataQualityResult, FeedItem, PipelineRun
from gjurme.enrichment.providers import FakeProvider
from gjurme.pipeline.locking import PIPELINE_LOCK_KEY, advisory_lock
from gjurme.pipeline.retention import apply_retention
from gjurme.pipeline.runner import run_pipeline
from gjurme.pipeline.scheduler import HEARTBEAT_KEY, Scheduler
from gjurme.quality.checks import run_checks
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
            fixture_bytes("wordpress_sq.xml"),
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
            s.scalars(select(Article.id).where(Article.excerpt.is_not(None)).limit(2))
        )
        s.execute(
            update(Article)
            .where(Article.id.in_(with_excerpt))
            .values(ingested_at=datetime.now(UTC) - timedelta(days=100))
        )
        dry = apply_retention(s, settings, dry_run=True)
    assert dry["raw_payloads_purged"] == 3 and dry["excerpts_purged"] == 2
    with db() as s, s.begin():
        apply_retention(s, settings)
    with db() as s:
        assert s.scalar(select(func_count(FeedItem)).where(FeedItem.payload.is_(None))) == 3
        assert s.scalar(select(func_count(Article)).where(Article.excerpt.is_(None))) >= 2
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
