"""Retention keeps the product and drops only what no page shows (docs/DATA_MODEL.md#retention).

The decisive test reads every public API answer before and after retention with free-hosting
settings and requires them to be identical."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from gjurme.api.app import create_app
from gjurme.config import Settings
from gjurme.db.models import (
    AlertEvent,
    Article,
    DataQualityResult,
    Enrichment,
    FeedFetch,
    FeedItem,
    PipelineRun,
)
from gjurme.enrichment.providers import FakeProvider
from gjurme.pipeline.retention import apply_retention
from gjurme.pipeline.runner import run_pipeline
from tests.integration.test_runner_ops import _sources

pytestmark = pytest.mark.integration

# free-hosting.yml
FREE = {
    "retention_raw_payload_days": 7,
    "retention_feed_item_days": 14,
    "retention_excerpt_days": 30,
    "retention_superseded_enrichment_days": 14,
    "retention_raw_response_days": 14,
    "retention_fetch_days": 30,
    "retention_run_days": 30,
}
LISTS = (
    "/api/v1/stories",
    "/api/v1/stories/blindspots",
    "/api/v1/articles",
    "/api/v1/entities",
    "/api/v1/sources",
    "/api/v1/topics",
    "/api/v1/topics/taxonomy",
    "/api/v1/analytics/overview",
    "/api/v1/analytics/volume",
    "/api/v1/analytics/sentiment",
    "/api/v1/analytics/sentiment/shift",
    "/api/v1/analytics/trends/topics",
    "/api/v1/analytics/trends/entities",
    "/api/v1/analytics/cooccurrence",
    "/api/share/sitemap.xml",
)


def _ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _items(body: Any) -> list[dict[str, Any]]:
    return body["items"] if isinstance(body, dict) and "items" in body else body


def _site(client: TestClient) -> dict[str, Any]:
    """Every public answer: the lists, and the detail page of everything they link to."""
    seen: dict[str, Any] = {}
    for path in LISTS:
        r = client.get(path)
        assert r.status_code == 200, path
        seen[path] = r.text if path.endswith(".xml") else r.json()
    details = [f"/api/v1/stories/{s['id']}" for s in _items(seen["/api/v1/stories"])]
    details += [f"/api/v1/articles/{a['id']}" for a in _items(seen["/api/v1/articles"])]
    details += [f"/api/v1/entities/{e['id']}" for e in _items(seen["/api/v1/entities"])]
    details += [f"/api/v1/sources/{s['slug']}" for s in seen["/api/v1/sources"]]
    details += [f"/api/v1/topics/{t['slug']}" for t in _items(seen["/api/v1/topics"])]
    details += [f"/api/share/stories/{s['id']}" for s in _items(seen["/api/v1/stories"])]
    assert len(details) > 10
    for path in details:
        r = client.get(path)
        assert r.status_code == 200, path
        seen[path] = r.text if path.startswith("/api/share/") else r.json()
    status = client.get("/api/v1/status").json()
    # the latest run and the sources' health; the minutes since then move with the clock
    seen["status"] = {k: v for k, v in status.items() if k != "minutes_since_success"}
    return seen


def _enrichment(article_id: int, *, days: float, **values: Any) -> Enrichment:
    row: dict[str, Any] = {
        "article_id": article_id,
        "provider": "fake",
        "model": "keyword-rules",
        "prompt_version": "test",
        "schema_version": "test",
        "status": "succeeded",
        "attempt": 1,
        "input_hash": "h" * 64,
        "created_at": _ago(days),
        "is_current": False,
    }
    return Enrichment(**(row | values))


def _count(s: Session, model: Any, *where: Any) -> int:
    return int(s.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def test_free_hosting_retention_changes_no_public_answer(
    db: sessionmaker[Session], settings: Settings, make_fetcher: Any
) -> None:
    fetcher = _sources(db, make_fetcher)
    run_pipeline(settings, db, trigger="test", provider=FakeProvider(), fetcher=fetcher)
    with db() as s, s.begin():
        articles = list(s.scalars(select(Article.id).order_by(Article.id)))
        first, second = articles[0], articles[1]
        # The whole first run happened 40 days ago: its fetches, its feed entries (which the
        # feeds have not listed since) and every article's current analysis.
        s.execute(update(FeedFetch).values(started_at=_ago(40)))
        old_items = list(s.scalars(select(FeedItem.id).order_by(FeedItem.id).limit(4)))
        s.execute(
            update(FeedItem)
            .where(FeedItem.id.in_(old_items))
            .values(first_seen_at=_ago(40), last_seen_at=_ago(20))
        )
        # an old entry still waiting for PROCESS, and an old one its feed still lists
        s.execute(
            update(FeedItem)
            .where(FeedItem.id == old_items[0])
            .values(processed_at=None, process_status="pending")
        )
        s.execute(update(FeedItem).where(FeedItem.id == old_items[1]).values(last_seen_at=_ago(1)))
        s.execute(update(Enrichment).values(created_at=_ago(40)))
        old_run = PipelineRun(
            trigger="test", stages=["ingest"], status="succeeded", started_at=_ago(40)
        )
        s.add(old_run)
        s.flush()
        s.execute(
            update(Enrichment).where(Enrichment.article_id == first).values(run_id=old_run.id)
        )
        s.add(DataQualityResult(run_id=old_run.id, check_name="x", severity="info", status="pass"))
        s.add(
            AlertEvent(
                alert_key="old", severity="info", title="t", message="m", created_at=_ago(40)
            )
        )
        s.add_all(
            [
                # replaced by the current analysis, failed tries: free, old → deleted
                _enrichment(first, days=20),
                _enrichment(first, days=20, status="failed", raw_response="{broken"),
                # a paid try is kept for the cost history; only its raw response goes
                _enrichment(
                    second,
                    days=20,
                    status="invalid",
                    provider="anthropic",
                    cost_usd=Decimal("0.001"),
                    raw_response="{broken",
                ),
                # recent → kept
                _enrichment(second, days=2, status="failed", raw_response="{broken"),
            ]
        )
    client = TestClient(create_app(settings.model_copy(update={"api_cache_ttl_seconds": 0}), db))
    before = _site(client)
    free = settings.model_copy(update=FREE)
    with db() as s, s.begin():
        counts = {
            "items": _count(s, FeedItem),
            "enrichments": _count(s, Enrichment),
            "current": _count(s, Enrichment, Enrichment.is_current),
            "articles": _count(s, Article),
            "fetches": _count(s, FeedFetch),
        }
        dry = apply_retention(s, free, dry_run=True)
    with db() as s, s.begin():
        applied = apply_retention(s, free)
    # A dry run counts each rule alone: a failed try's raw response counts there although
    # the try itself is deleted first.
    for rule, n in applied.items():
        if rule != "dry_run":
            assert n == dry[rule] or (rule == "raw_responses_purged" and n < dry[rule]), rule
    assert applied["feed_items_deleted"] == 2  # not the pending one, not the one still listed
    assert applied["superseded_enrichments_deleted"] == 2
    assert applied["raw_responses_purged"] == 1  # the paid one's
    assert applied["fetches_deleted"] == counts["fetches"]
    assert applied["runs_deleted"] == 1 and applied["alerts_deleted"] == 1

    assert _site(client) == before  # not one public answer changed

    with db() as s:
        assert _count(s, Article) == counts["articles"]
        assert _count(s, Enrichment, Enrichment.is_current) == counts["current"]
        assert _count(s, Enrichment) == counts["enrichments"] - 2
        assert _count(s, FeedItem) == counts["items"] - 2
        assert _count(s, FeedItem, FeedItem.processed_at.is_(None)) == 1
        assert _count(s, FeedItem, FeedItem.first_fetch_id.is_not(None)) == 0  # SET NULL
        assert _count(s, FeedFetch) == 0
        assert _count(s, DataQualityResult, DataQualityResult.check_name == "x") == 0
        # the run is gone; the analysis it produced stays, without its run
        assert (
            s.scalar(
                select(Enrichment.run_id).where(
                    Enrichment.article_id == first, Enrichment.is_current
                )
            )
            is None
        )
        paid = s.scalars(select(Enrichment).where(Enrichment.cost_usd > 0)).one()
        assert paid.raw_response is None
        assert _count(s, Enrichment, Enrichment.raw_response.is_not(None)) == 1  # the recent one


def test_server_defaults_keep_what_free_hosting_drops(
    db: sessionmaker[Session], settings: Settings, make_fetcher: Any
) -> None:
    """Without the free-hosting variables, 20- and 40-day-old history is still inside the
    server's 90/180-day windows."""
    fetcher = _sources(db, make_fetcher)
    run_pipeline(settings, db, trigger="test", provider=FakeProvider(), fetcher=fetcher)
    with db() as s, s.begin():
        article = s.scalars(select(Article.id).limit(1)).one()
        s.execute(update(FeedFetch).values(started_at=_ago(40)))
        s.execute(update(FeedItem).values(last_seen_at=_ago(40)))
        s.add(_enrichment(article, days=40))
        s.execute(update(PipelineRun).values(started_at=_ago(40)))
    with db() as s, s.begin():
        result = apply_retention(s, settings)
    for rule in (
        "feed_items_deleted",
        "superseded_enrichments_deleted",
        "fetches_deleted",
        "runs_deleted",
    ):
        assert result[rule] == 0, rule


def test_retention_deletes_follow_indexed_foreign_keys(db: sessionmaker[Session]) -> None:
    """Every foreign key that a retention DELETE sets to NULL or cascades through has an index
    on the referencing column: otherwise each deleted row scans the referencing table."""
    with db() as s:
        rows = s.execute(
            text("""
            SELECT c.conrelid::regclass::text AS tbl, a.attname AS col
            FROM pg_constraint c
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
            WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 1
              AND c.confrelid::regclass::text IN
                  ('raw.feed_items', 'raw.feed_fetches', 'core.enrichments',
                   'ops.pipeline_runs', 'ops.alert_events')
              AND NOT EXISTS (
                  SELECT 1 FROM pg_index i
                  WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1])
        """)
        ).all()
    assert [(r.tbl, r.col) for r in rows] == []
