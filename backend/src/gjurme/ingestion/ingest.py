"""INGEST stage: feeds → ``raw.feed_fetches`` + ``raw.feed_items``.

Network I/O runs concurrently (bounded thread pool); database writes happen per source in their
own transaction, so one failing source — network, parse or DB error — never affects another.

A source is auto-disabled after ``source_failure_disable_threshold`` failures in a row, except
in runs where most sources fail at once: that is an outage on this side (DNS, egress), not the
outlets'. Auto-disabled sources are fetched again every ``REPROBE_AFTER`` and re-enabled when
the fetch succeeds.

A failed fetch is reported as a source *failing* (``IngestStats.failing``, which makes the run
``partial``) only from ``source_failure_partial_threshold`` failures in a row: an outlet that
times out once is back on the next run, and a run that says "partial" for it says nothing.

A feed lists only its latest items (10 for most outlets). When every item of a fetch is new
although the source was fetched before, the outlet published more since then than the feed
lists: its next pages are read (``?paged=2``, WordPress style) until they reach items already
stored, ``NEXT_PAGES_MAX`` at most, so the items in between are not missed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from gjurme.config import Settings
from gjurme.db.models import FeedFetch, FeedItem, Source
from gjurme.ingestion.feed_parser import parse_feed
from gjurme.ingestion.fetcher import FeedFetcher, FetchResult, next_page_url
from gjurme.ingestion.normalize import clean_text, item_key, sha256_hex

log = logging.getLogger(__name__)

SUCCESS_STATUSES = ("ok", "not_modified")
AUTO_DISABLED = "auto-disabled"  # prefix of Source.disabled_reason
REPROBE_AFTER = timedelta(hours=6)
# At least this many sources fetched, and at least this share of them failing: an outage here.
OUTAGE_MIN_SOURCES = 3
OUTAGE_FAILED_SHARE = 0.75
# A fetch of at least this many items, all of them new: the feed overflowed.
OVERFLOW_MIN_ITEMS = 5
# Next pages read after an overflow: pages 2 and 3, up to 30 items of a feed that lists 10.
NEXT_PAGES_MAX = 2

_OVERFLOWS = text(
    """
    SELECT src.slug,
           count(*) FILTER (WHERE prev.gap <= make_interval(secs => :normal_gap)) AS fetches,
           count(*) FILTER (WHERE prev.gap > make_interval(secs => :normal_gap)) AS after_gap,
           max(f.items_seen) AS items_listed
    FROM raw.feed_fetches f
    JOIN core.sources src ON src.id = f.source_id
    CROSS JOIN LATERAL (
        SELECT f.started_at - max(e.started_at) AS gap
        FROM raw.feed_fetches e
        WHERE e.source_id = f.source_id AND e.status IN ('ok', 'not_modified')
          AND e.started_at < f.started_at
    ) prev
    WHERE f.started_at >= now() - interval '24 hours' AND f.status = 'ok'
      AND f.items_seen >= :min_items AND f.items_new = f.items_seen
      AND prev.gap IS NOT NULL  -- not the source's first fetch
    GROUP BY src.slug ORDER BY src.slug
    """
)


def feed_overflows(session: Session, scheduler_interval_minutes: int) -> list[dict[str, Any]]:
    """Per source, the fetches of the last 24 hours in which every item was new (at least
    ``OVERFLOW_MIN_ITEMS``), counting the next pages read after it: ``fetches`` one run after the
    source's previous successful fetch (at most 1.5 scheduler intervals before), ``after_gap``
    the others. A feed whose next page caught up does not show here."""
    return [
        dict(r._mapping)
        for r in session.execute(
            _OVERFLOWS,
            {"normal_gap": scheduler_interval_minutes * 90, "min_items": OVERFLOW_MIN_ITEMS},
        )
    ]


def busy_short_feeds(session: Session, scheduler_interval_minutes: int) -> list[str]:
    """Sources whose feed overflowed one run after another in the last 24 hours, its next
    pages read or none there (Zëri lists 10 items without a page 2): those a second read at
    the end of a run (``INGEST_SECOND_READ``) helps."""
    return [r["slug"] for r in feed_overflows(session, scheduler_interval_minutes) if r["fetches"]]


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
    re_enabled: bool = False
    consecutive_failures: int = 0  # the source's failures in a row after this fetch
    reprobe: bool = False  # an auto-disabled source fetched again to see if it recovered
    pages: int = 1  # feed pages read: more than 1 after an overflow (NEXT_PAGES_MAX)
    items_from_next_pages: int = 0  # of items_new: found on those next pages
    # internal, left out of the run's stats
    fetch_id: int | None = None
    overflowed: bool = False  # every item new although the source was fetched before

    @property
    def failed(self) -> bool:
        return self.status not in SUCCESS_STATUSES


@dataclass(slots=True)
class IngestStats:
    sources: list[SourceIngestStats] = field(default_factory=list)
    outage: bool = False  # most sources failed: failures were not counted
    failing_after: int = 1  # failures in a row from which a source counts as failing

    @property
    def failing(self) -> list[str]:
        """Collected sources that failed again, ``failing_after`` fetches in a row. An
        auto-disabled source probed again is not among them: it was reported when it was
        disabled, and it is not collected."""
        return [
            s.slug
            for s in self.sources
            if s.failed and not s.reprobe and s.consecutive_failures >= self.failing_after
        ]

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
            "sources_failing": self.failing,
            "auto_disabled": [s.slug for s in self.sources if s.auto_disabled],
            "re_enabled": [s.slug for s in self.sources if s.re_enabled],
            "outage": self.outage,
            "items_from_next_pages": sum(s.items_from_next_pages for s in self.sources),
            "per_source": [
                {k: v for k, v in asdict(s).items() if k not in _INTERNAL_STATS}
                for s in self.sources
            ],
        }


_INTERNAL_STATS = ("fetch_id", "overflowed")


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    id: int
    slug: str
    feed_url: str
    etag: str | None
    last_modified: str | None
    is_active: bool  # False: an auto-disabled source fetched again to see if it recovered


# Articles already stored take the photo their unchanged feed entry now carries (ADR-030).
_BACKFILL_IMAGES = text(
    """
    UPDATE core.articles a SET image_url = fi.payload->>'image'
    FROM raw.feed_items fi
    WHERE fi.source_id = :source_id AND fi.item_key = ANY(:keys) AND fi.article_id = a.id
      AND a.source_id = fi.source_id AND a.image_url IS NULL
      AND fi.payload->>'image' LIKE 'https://%'
    """
)


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
    count_failure: bool = True,
) -> SourceIngestStats:
    """Persist one fetch outcome and its items. Runs inside the caller's transaction.

    ``count_failure=False`` (an outage on this side) records a failed fetch without counting it
    towards auto-disabling the source.
    """
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
    fetched_before = source.last_success_at is not None
    source.last_fetch_at = now
    if stats.status in SUCCESS_STATUSES:
        source.consecutive_failures = 0
        source.last_success_at = now
        if result.status == "ok":
            source.etag = result.etag
            source.last_modified = result.last_modified
        source.verification_status = "verified"  # proven by a successful fetch
        if not source.is_active and (source.disabled_reason or "").startswith(AUTO_DISABLED):
            source.is_active = True
            source.disabled_reason = None
            stats.re_enabled = True
            log.info("auto-disabled source recovered", extra={"source": source.slug})
    elif count_failure:
        count_source_failure(source, stats, failure_threshold)

    if parsed is not None:
        prepared = _prepare_items(parsed.entries)
        stats.items_seen = len(prepared)
        stats.items_new, stats.items_changed = _store_items(
            session, source.id, fetch.id, prepared, now
        )
    fetch.items_seen = stats.items_seen
    fetch.items_new = stats.items_new
    fetch.items_changed = stats.items_changed
    stats.consecutive_failures = source.consecutive_failures
    stats.fetch_id = fetch.id
    stats.overflowed = (
        fetched_before
        and stats.items_seen >= OVERFLOW_MIN_ITEMS
        and stats.items_new == stats.items_seen
    )
    return stats


def _store_items(
    session: Session,
    source_id: int,
    fetch_id: int,
    prepared: dict[str, dict[str, Any]],
    now: datetime,
) -> tuple[int, int]:
    """Upsert one page of prepared items; returns how many were new and how many changed."""
    if not prepared:
        return 0, 0
    existing: dict[str, str] = dict(
        session.execute(
            select(FeedItem.item_key, FeedItem.content_hash).where(
                tuple_(FeedItem.source_id, FeedItem.item_key).in_(
                    [(source_id, k) for k in prepared]
                )
            )
        ).all()
    )
    new = changed_count = 0
    rows = []
    for key, item in prepared.items():
        if key not in existing:
            new += 1
        elif existing[key] != item["content_hash"]:
            changed_count += 1
        rows.append(
            {
                **item,
                "source_id": source_id,
                "first_fetch_id": fetch_id,
                "first_seen_at": now,
                "last_seen_at": now,
            }
        )
    stmt = insert(FeedItem).values(rows)
    changed = FeedItem.content_hash != stmt.excluded.content_hash
    # an item stored before photos were kept takes the new payload once, for its photo
    gained_image = and_(
        FeedItem.payload["image"].astext.is_(None),
        stmt.excluded.payload["image"].astext.is_not(None),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[FeedItem.source_id, FeedItem.item_key],
        set_={
            "last_seen_at": stmt.excluded.last_seen_at,
            "payload": case(
                (or_(changed, gained_image), stmt.excluded.payload),
                else_=FeedItem.payload,
            ),
            "content_hash": stmt.excluded.content_hash,
            "processed_at": case((changed, None), else_=FeedItem.processed_at),
            "process_status": case((changed, "pending"), else_=FeedItem.process_status),
        },
    )
    session.execute(stmt)
    session.execute(_BACKFILL_IMAGES, {"source_id": source_id, "keys": list(prepared)})
    return new, changed_count


def follow_next_pages(
    session_factory: Callable[[], Session],
    fetcher: FeedFetcher,
    source_id: int,
    feed_url: str,
    stats: SourceIngestStats,
) -> None:
    """After an overflow, read the feed's next pages until they reach items already stored,
    ``NEXT_PAGES_MAX`` at most. Their items count towards the fetch that overflowed, so the
    ``feed_overflow_24h`` check flags only a feed whose next pages did not catch up. A page
    that fails, is no feed, or repeats items already read (a feed that does not page) ends it,
    and does not count against the source."""
    if stats.fetch_id is None:
        return
    with session_factory() as session:
        read = set(
            session.scalars(
                select(FeedItem.item_key).where(
                    FeedItem.source_id == source_id, FeedItem.first_fetch_id == stats.fetch_id
                )
            )
        )
    for page in range(2, 2 + NEXT_PAGES_MAX):
        result = fetcher.fetch(next_page_url(feed_url, page))
        parsed = (
            parse_feed(
                result.body,
                response_headers={"content-type": result.content_type or "application/xml"},
            )
            if result.status == "ok" and result.body is not None
            else None
        )
        fresh = {}
        if parsed is not None and parsed.is_feed:
            fresh = {k: v for k, v in _prepare_items(parsed.entries).items() if k not in read}
        if not fresh:
            log.info(
                "next feed page has nothing more",
                extra={"source": stats.slug, "page": page, "status": result.status},
            )
            return
        with session_factory() as session, session.begin():
            new, changed = _store_items(
                session, source_id, stats.fetch_id, fresh, datetime.now(UTC)
            )
            fetch = session.get(FeedFetch, stats.fetch_id)
            if fetch is not None:
                fetch.items_seen = (fetch.items_seen or 0) + len(fresh)
                fetch.items_new = (fetch.items_new or 0) + new
                fetch.items_changed = (fetch.items_changed or 0) + changed
                fetch.duration_ms = (fetch.duration_ms or 0) + result.duration_ms
        read.update(fresh)
        stats.pages = page
        stats.items_seen += len(fresh)
        stats.items_new += new
        stats.items_changed += changed
        stats.items_from_next_pages += new
        if new < len(fresh):  # reached items stored before: nothing was missed beyond
            return


def count_source_failure(source: Source, stats: SourceIngestStats, threshold: int) -> None:
    """One more failure in a row; auto-disable the source at ``threshold``."""
    source.consecutive_failures += 1
    if source.consecutive_failures >= threshold and source.is_active:
        source.is_active = False
        source.verification_status = "failing"
        source.disabled_reason = (
            f"{AUTO_DISABLED} after {source.consecutive_failures} consecutive failures "
            f"(last: {stats.status}: {stats.error})"
        )
        stats.auto_disabled = True
        log.warning("source auto-disabled", extra={"source": source.slug})


def ingest_all(
    session_factory: Callable[[], Session],
    fetcher: FeedFetcher,
    settings: Settings,
    *,
    run_id: int | None = None,
    only_slugs: list[str] | None = None,
) -> IngestStats:
    reprobe = and_(
        Source.is_active.is_(False),
        Source.disabled_reason.startswith(AUTO_DISABLED),
        or_(
            Source.last_fetch_at.is_(None), Source.last_fetch_at < datetime.now(UTC) - REPROBE_AFTER
        ),
    )
    with session_factory() as session:
        query = select(Source).where(
            or_(Source.is_active.is_(True), reprobe), Source.feed_url.is_not(None)
        )
        if only_slugs:
            query = query.where(Source.slug.in_(only_slugs))
        snapshots = [
            _SourceSnapshot(s.id, s.slug, s.feed_url or "", s.etag, s.last_modified, s.is_active)
            for s in session.scalars(query.order_by(Source.id))
        ]

    stats = IngestStats(failing_after=settings.source_failure_partial_threshold)
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

    fetched = [r for snap, _, r in results if snap.is_active]
    failed = sum(1 for r in fetched if r.status not in SUCCESS_STATUSES)
    stats.outage = len(fetched) >= OUTAGE_MIN_SOURCES and failed >= OUTAGE_FAILED_SHARE * len(
        fetched
    )
    if stats.outage:
        log.error(
            "most sources failed at once — an outage on this side; not counted against sources",
            extra={"failed": failed, "fetched": len(fetched)},
        )
    threshold = settings.source_failure_disable_threshold
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
                    failure_threshold=threshold,
                    count_failure=not stats.outage,
                )
        except Exception as exc:  # isolate: a DB/parse bug on one source must not stop others
            log.exception("storing fetch result failed", extra={"source": snap.slug})
            source_stats = SourceIngestStats(
                slug=snap.slug,
                status="parse_error",
                http_status=result.http_status,
                duration_ms=result.duration_ms,
                error=f"{type(exc).__name__}: {exc}"[:500],
            )
            _record_store_failure(session_factory, snap, started, source_stats, run_id, threshold)
        source_stats.reprobe = not snap.is_active
        if source_stats.overflowed:
            try:
                follow_next_pages(session_factory, fetcher, snap.id, snap.feed_url, source_stats)
            except Exception:  # the first page is stored; a next page must never cost it
                log.exception("reading the next feed page failed", extra={"source": snap.slug})
        stats.sources.append(source_stats)
        log.info(
            "source ingested",
            extra={
                "source": snap.slug,
                "status": source_stats.status,
                "items_seen": source_stats.items_seen,
                "items_new": source_stats.items_new,
                "pages": source_stats.pages,
                "duration_ms": source_stats.duration_ms,
            },
        )
    return stats


def _record_store_failure(
    session_factory: Callable[[], Session],
    snap: _SourceSnapshot,
    started: datetime,
    stats: SourceIngestStats,
    run_id: int | None,
    threshold: int,
) -> None:
    """A fetch whose result could not be stored still counts as a failed fetch, so a feed that
    keeps breaking the store shows up in the fetch log and is eventually auto-disabled."""
    try:
        with session_factory() as session, session.begin():
            source = session.get(Source, snap.id)
            if source is None:
                return
            session.add(
                FeedFetch(
                    run_id=run_id,
                    source_id=source.id,
                    started_at=started,
                    duration_ms=stats.duration_ms,
                    status=stats.status,
                    http_status=stats.http_status,
                    error=stats.error,
                )
            )
            source.last_fetch_at = datetime.now(UTC)
            count_source_failure(source, stats, threshold)
            stats.consecutive_failures = source.consecutive_failures
    except Exception:
        log.exception("recording the failed fetch failed", extra={"source": snap.slug})
