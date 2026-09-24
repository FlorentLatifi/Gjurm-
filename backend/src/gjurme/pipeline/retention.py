"""Retention / data minimisation.

Policy (documented in docs/DATA_MODEL.md#retention):

| Data                              | Kept     | Why                                          |
|-----------------------------------|----------|----------------------------------------------|
| raw.feed_items.payload            | 30 days  | replay window for reprocessing; minimisation |
| core.articles.excerpt             | 90 days  | re-enrichment window; publisher text          |
| core.enrichments.raw_response     | 90 days  | debugging failed outputs                     |
| raw.feed_fetches                  | 90 days  | source-health history                        |
| ops.pipeline_runs (+ DQ results)  | 180 days | operational history                          |
| ops.alert_events                  | 180 days | incident history                             |
| articles, enrichments, entities   | forever  | the analytical product (metadata only)       |
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from gjurme.config import Settings

log = logging.getLogger(__name__)


# name → (action, table, SET clause or None for DELETE, WHERE predicate)
_RULES: dict[str, tuple[str, str, str | None, str]] = {
    "raw_payloads_purged": (
        "update",
        "raw.feed_items",
        "payload = NULL",
        "payload IS NOT NULL AND processed_at IS NOT NULL "
        "AND first_seen_at < now() - make_interval(days => :raw_days)",
    ),
    "excerpts_purged": (
        "update",
        "core.articles",
        "excerpt = NULL",
        "excerpt IS NOT NULL AND enrichment_status IN ('succeeded', 'skipped') "
        "AND ingested_at < now() - make_interval(days => :excerpt_days)",
    ),
    "raw_responses_purged": (
        "update",
        "core.enrichments",
        "raw_response = NULL",
        "raw_response IS NOT NULL AND created_at < now() - interval '90 days'",
    ),
    "fetches_deleted": (
        "delete",
        "raw.feed_fetches",
        None,
        "started_at < now() - interval '90 days'",
    ),
    "runs_deleted": (
        "delete",
        "ops.pipeline_runs",
        None,
        "started_at < now() - interval '180 days'",
    ),
    "alerts_deleted": (
        "delete",
        "ops.alert_events",
        None,
        "created_at < now() - interval '180 days'",
    ),
}


def apply_retention(
    session: Session, settings: Settings, *, dry_run: bool = False
) -> dict[str, Any]:
    params = {
        "raw_days": settings.retention_raw_payload_days,
        "excerpt_days": settings.retention_excerpt_days,
    }
    result: dict[str, Any] = {"dry_run": dry_run}
    for name, (action, table, set_clause, where) in _RULES.items():
        if dry_run:
            sql = f"SELECT count(*) FROM {table} WHERE {where}"  # noqa: S608 - static strings
            result[name] = session.execute(text(sql), params).scalar_one()
            continue
        if action == "update":
            sql = f"UPDATE {table} SET {set_clause} WHERE {where}"  # noqa: S608
        else:
            sql = f"DELETE FROM {table} WHERE {where}"  # noqa: S608
        result[name] = session.execute(text(sql), params).rowcount  # type: ignore[attr-defined]
    log.info("retention applied", extra=result)
    return result
