"""Retention / data minimisation.

Policy (documented in docs/DATA_MODEL.md#retention). Days are settings; the defaults are for a
server, and free hosting shortens them (``free-hosting.yml``) to stay inside Neon's 1 GB.

| Data                                      | Server / free | Why                          |
|-------------------------------------------|---------------|------------------------------|
| raw.feed_items.payload                    | 30 / 7 days   | replay window                |
| raw.feed_items rows: processed, and not   | 90 / 14 days  | L1 dedup of what the feeds   |
|   listed by their feed since              |               |   still list                 |
| core.articles.excerpt                     | 90 / 30 days  | re-enrichment window         |
| core.enrichments: attempts that are not   | 90 / 14 days  | debugging; attempts that     |
|   the article's current analysis          |               |   cost money are kept        |
| core.enrichments.raw_response             | 90 / 14 days  | debugging failed outputs     |
| raw.feed_fetches                          | 90 / 30 days  | source-health history        |
| ops.pipeline_runs (+ DQ results), alerts  | 180 / 30 days | operational history          |
| articles, current analyses, bridges,      | forever       | the product                  |
|   entities, stories, sources              |               |                              |

Nothing here touches what a page shows: an article keeps its metadata, its current analysis,
its topics, names and story; the public status reads only the latest run. The rules run in the
order listed: entries before the fetches they point to, runs last.
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
    # A processed entry its feed stopped listing long ago: its article (if any) is in
    # core.articles; the row only served L1 dedup of the feed's current entries. Pending
    # entries stay whatever their age.
    "feed_items_deleted": (
        "delete",
        "raw.feed_items",
        None,
        "processed_at IS NOT NULL "
        "AND last_seen_at < now() - make_interval(days => :feed_item_days)",
    ),
    "excerpts_purged": (
        "update",
        "core.articles",
        "excerpt = NULL",
        # Whatever the analysis status: publisher text is kept 90 days, not "until analysed".
        "excerpt IS NOT NULL AND ingested_at < now() - make_interval(days => :excerpt_days)",
    ),
    # Failed tries and analyses replaced by a newer one (the keyword rules' by a model's). The
    # current analysis is never one of them; rows that recorded spending stay for the cost
    # history.
    "superseded_enrichments_deleted": (
        "delete",
        "core.enrichments",
        None,
        "NOT is_current AND cost_usd = 0 "
        "AND created_at < now() - make_interval(days => :superseded_days)",
    ),
    "raw_responses_purged": (
        "update",
        "core.enrichments",
        "raw_response = NULL",
        "raw_response IS NOT NULL "
        "AND created_at < now() - make_interval(days => :raw_response_days)",
    ),
    "fetches_deleted": (
        "delete",
        "raw.feed_fetches",
        None,
        "started_at < now() - make_interval(days => :fetch_days)",
    ),
    "runs_deleted": (
        "delete",
        "ops.pipeline_runs",
        None,
        "started_at < now() - make_interval(days => :run_days) AND status <> 'running'",
    ),
    "alerts_deleted": (
        "delete",
        "ops.alert_events",
        None,
        "created_at < now() - make_interval(days => :run_days)",
    ),
}


def retention_params(settings: Settings) -> dict[str, int]:
    return {
        "raw_days": settings.retention_raw_payload_days,
        "feed_item_days": settings.retention_feed_item_days,
        "excerpt_days": settings.retention_excerpt_days,
        "superseded_days": settings.retention_superseded_enrichment_days,
        "raw_response_days": settings.retention_raw_response_days,
        "fetch_days": settings.retention_fetch_days,
        "run_days": settings.retention_run_days,
    }


def apply_retention(
    session: Session, settings: Settings, *, dry_run: bool = False
) -> dict[str, Any]:
    params = retention_params(settings)
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
