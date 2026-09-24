"""INGEST stage: feeds → ``raw.feed_fetches`` + ``raw.feed_items``.

Network I/O runs concurrently (bounded thread pool); database writes happen per source in their
own transaction, so one failing source — network, parse or DB error — never affects another.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from gjurme.config import Settings
from gjurme.db.models import FeedFetch, FeedItem, Source
from gjurme.ingestion.feed_parser import parse_feed
from gjurme.ingestion.fetcher import FeedFetcher, FetchResult
from gjurme.ingestion.normalize import clean_text, item_key, sha256_hex

log = logging.getLogger(__name__)

SUCCESS_STATUSES = ("ok", "not_modified")


@dataclass(slots=True)
class SourceIngestStats:
    slug: str
    status: str
    http_status: int | None = None
    items_seen: int = 0
    items_new: int = 0
    items_changed: int = 0
    malformed: bool = False
    duration_ms: int = 0
    error: str | None = None
    auto_disabled: bool = False


@dataclass(slots=True)
class IngestStats:
    sources: list[SourceIngestStats] = field(default_factory=list)

    @property
    def sources_ok(self) -> int:
        return sum(1 for s in self.sources if s.status in SUCCESS_STATUSES)

    @property
    def sources_failed(self) -> int:
        return len(self.sources) - self.sources_ok

    @property
    def items_new(self) -> int:
        return sum(s.items_new for s in self.sources)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sources_total": len(self.sources),
            "sources_ok": self.sources_ok,
            "sources_failed": self.sources_failed,
            "items_seen": sum(s.items_seen for s in self.sources),
            "items_new": self.items_new,
            "items_changed": sum(s.items_changed for s in self.sources),
            "auto_disabled": [s.slug for s in self.sources if s.auto_disabled],
            "per_source": [asdict(s) for s in self.sources],
        }


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    id: int
    slug: str
    feed_url: str
    etag: str | None
    last_modified: str | None


def _prepare_items(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Compute identity + content hash for each entry; last occurrence wins on duplicates."""
    prepared: dict[str, dict[str, Any]] = {}
    for payload in entries:
        title = clean_text(payload.get("title"))
        key = item_key(payload.get("id"), payload.get("link"), title, payload.get("published_iso"))
        content_hash = sha256_hex(
            title, clean_text(payload.get("summary")), payload.get("link") or ""
        )
        prepared[key] = {
            "item_key": key,
            "guid": (payload.get("id") or None),
            "link": (payload.get("link") or None),
            "payload": payload,
            "content_hash": content_hash,
        }
    return prepared


def store_fetch_result(
    session: Session,
    source: Source,
    result: FetchResult,
    *,
    run_id: int | None,
    started_at: datetime,
    failure_threshold: int,
) -> SourceIngestStats:
    """Persist one fetch outcome and its items. Runs inside the caller's transaction."""
    stats = SourceIngestStats(
        slug=source.slug,
        status=result.status,
        http_status=result.http_status,
        duration_ms=result.duration_ms,
        error=result.error,
    )
    parsed = None
    if result.status == "ok" and result.body is not None:
        parsed = parse_feed(
            result.body, response_headers={"content-type": result.content_type or "application/xml"}
        )
        if not parsed.is_feed or (parsed.malformed and not parsed.entries):
            stats.status = "parse_error"
            stats.error = parsed.malformed_reason or "response is not an RSS/Atom feed"
            parsed = None
        else:
            stats.malformed = parsed.malformed

    fetch = FeedFetch(
        run_id=run_id,
        source_id=source.id,
        started_at=started_at,
        duration_ms=result.duration_ms,
        status=stats.status,
        http_status=result.http_status,
        bytes=len(result.body) if result.body is not None else None,
        malformed=stats.malformed,
        malformed_reason=parsed.malformed_reason if parsed and parsed.malformed else None,
        error=stats.error,
    )
    session.add(fetch)
    session.flush()

    now = datetime.now(UTC)
    source.last_fetch_at = now
    if stats.status in SUCCESS_STATUSES:
        source.consecutive_failures = 0
        source.last_success_at = now
        if result.status == "ok":
            source.etag = result.etag
            source.last_modified = result.last_modified
        if source.verification_status == "failing":
            source.verification_status = "verified"
    else:
        source.consecutive_failures += 1
        if source.consecutive_failures >= failure_threshold and source.is_active:
            source.is_active = False
            source.verification_status = "failing"
            source.disabled_reason = (
                f"auto-disabled after {source.consecutive_failures} consecutive failures "
                f"(last: {stats.status}: {stats.error})"
            )
            stats.auto_disabled = True
            log.warning("source auto-disabled", extra={"source": source.slug})

    if parsed is not None:
        prepared = _prepare_items(parsed.entries)
        stats.items_seen = len(prepared)
        if prepared:
            existing: dict[str, str] = dict(
                session.execute(  # type: ignore[arg-type]
                    select(FeedItem.item_key, FeedItem.content_hash).where(
                        tuple_(FeedItem.source_id, FeedItem.item_key).in_(
                            [(source.id, k) for k in prepared]
                        )
                    )
                ).all()
            )
            rows = []
            for key, item in prepared.items():
                if key not in existing:
                    stats.items_new += 1
                elif existing[key] != item["content_hash"]:
                    stats.items_changed += 1
                rows.append(
                    {
                        **item,
                        "source_id": source.id,
                        "first_fetch_id": fetch.id,
                        "first_seen_at": now,
                        "last_seen_at": now,
                    }
                )
            stmt = insert(FeedItem).values(rows)
            changed = FeedItem.content_hash != stmt.excluded.content_hash
            stmt = stmt.on_conflict_do_update(
                index_elements=[FeedItem.source_id, FeedItem.item_key],
                set_={
                    "last_seen_at": stmt.excluded.last_seen_at,
                    "payload": case((changed, stmt.excluded.payload), else_=FeedItem.payload),
                    "content_hash": stmt.excluded.content_hash,
                    "processed_at": case((changed, None), else_=FeedItem.processed_at),
                    "process_status": case((changed, "pending"), else_=FeedItem.process_status),
                },
            )
            session.execute(stmt)
    fetch.items_seen = stats.items_seen
    fetch.items_new = stats.items_new
    fetch.items_changed = stats.items_changed
    return stats


def ingest_all(
    session_factory: Callable[[], Session],
    fetcher: FeedFetcher,
    settings: Settings,
    *,
    run_id: int | None = None,
    only_slugs: list[str] | None = None,
) -> IngestStats:
    with session_factory() as session:
        query = select(Source).where(Source.is_active.is_(True), Source.feed_url.is_not(None))
        if only_slugs:
            query = query.where(Source.slug.in_(only_slugs))
        snapshots = [
            _SourceSnapshot(s.id, s.slug, s.feed_url or "", s.etag, s.last_modified)
            for s in session.scalars(query.order_by(Source.id))
        ]

    stats = IngestStats()
    if not snapshots:
        log.warning("no active sources to ingest")
        return stats

    def _fetch(snap: _SourceSnapshot) -> tuple[_SourceSnapshot, datetime, FetchResult]:
        started = datetime.now(UTC)
        return snap, started, fetcher.fetch(snap.feed_url, snap.etag, snap.last_modified)

    with ThreadPoolExecutor(
        max_workers=settings.fetch_concurrency, thread_name_prefix="fetch"
    ) as pool:
        results = list(pool.map(_fetch, snapshots))

    for snap, started, result in results:
        try:
            with session_factory() as session, session.begin():
                source = session.get(Source, snap.id)
                if source is None:
                    continue
                source_stats = store_fetch_result(
                    session,
                    source,
                    result,
                    run_id=run_id,
                    started_at=started,
                    failure_threshold=settings.source_failure_disable_threshold,
                )
        except Exception as exc:  # isolate: a DB/parse bug on one source must not stop others
            log.exception("storing fetch result failed", extra={"source": snap.slug})
            source_stats = SourceIngestStats(
                slug=snap.slug, status="parse_error", error=f"{type(exc).__name__}: {exc}"[:500]
            )
        stats.sources.append(source_stats)
        log.info(
            "source ingested",
            extra={
                "source": snap.slug,
                "status": source_stats.status,
                "items_seen": source_stats.items_seen,
                "items_new": source_stats.items_new,
                "duration_ms": source_stats.duration_ms,
            },
        )
    return stats
