"""``gjurme db-usage``: sizes, stage durations and the pipeline's compute (db/usage.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from gjurme.config import Settings
from gjurme.db.models import PipelineRun
from gjurme.db.usage import Span, awake_seconds, database_usage, format_usage
from gjurme.enrichment.providers import FakeProvider
from gjurme.pipeline.runner import run_pipeline
from tests.integration.test_runner_ops import _sources

T0 = datetime(2026, 11, 18, 16, 1, tzinfo=UTC)


def _span(start_min: float, minutes: float) -> Span:
    start = T0 + timedelta(minutes=start_min)
    return Span(start, start + timedelta(minutes=minutes))


def test_awake_time_is_each_run_plus_five_minutes_overlaps_once() -> None:
    assert awake_seconds([]) == 0
    assert awake_seconds([_span(0, 4)]) == 9 * 60
    # 30 minutes apart: two separate wake-ups
    assert awake_seconds([_span(30, 4), _span(0, 4)]) == 18 * 60
    # the second starts while the database is still awake from the first: 0 → 6 + 5
    assert awake_seconds([_span(0, 4), _span(6, 0)]) == 11 * 60
    assert awake_seconds([_span(0, 10), _span(2, 1)]) == 15 * 60  # inside the first


@pytest.mark.integration
def test_report_lists_tables_stages_and_the_pipelines_compute(
    db: sessionmaker[Session], settings: Settings, make_fetcher: Any
) -> None:
    fetcher = _sources(db, make_fetcher)
    run_pipeline(settings, db, trigger="test", provider=FakeProvider(), fetcher=fetcher)
    with db() as s, s.begin():
        # pretend the run took 4 minutes, so the compute figure is predictable
        s.execute(
            update(PipelineRun).values(
                started_at=datetime.now(UTC) - timedelta(hours=2),
                finished_at=datetime.now(UTC) - timedelta(hours=2) + timedelta(minutes=4),
                duration_ms=240_000,
            )
        )
    with db() as s:
        usage = database_usage(s, days=7)
    names = [t["name"] for t in usage["tables"]]
    assert {"core.articles", "raw.feed_items", "core.enrichments", "ops.pipeline_runs"} <= set(
        names
    )
    sizes = [t["total_bytes"] for t in usage["tables"]]
    assert sizes == sorted(sizes, reverse=True) and usage["database_bytes"] >= sum(sizes)
    articles = next(t for t in usage["tables"] if t["name"] == "core.articles")
    assert articles["total_bytes"] >= articles["table_bytes"] + articles["index_bytes"] > 0
    assert len(usage["largest_indexes"]) == 10
    assert [s["stage"] for s in usage["stages"]] == [
        "ingest",
        "process",
        "enrich",
        "cluster",
        "quality",
    ]
    assert all(s["runs"] == 1 and s["max_seconds"] >= s["avg_seconds"] for s in usage["stages"])
    runs = usage["runs"]
    assert runs["count"] == 1 and runs["avg_seconds"] == 240
    # one run of 4 minutes + 5 awake, observed over its own hour (a young database): 9 min/day
    # scaled to a day of such hours
    assert runs["awake_minutes_per_day"] == 9 * 24
    report = format_usage(usage)
    assert report.startswith("database: ") and "core.articles" in report
    assert "CU-hours in 30 days" in report and "enrich" in report
