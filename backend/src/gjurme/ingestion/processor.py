"""PROCESS stage: ``raw.feed_items`` → ``core.articles``.

Cleans, validates and deduplicates. Every raw item ends in exactly one terminal state —
``accepted``, ``updated``, ``duplicate`` or ``rejected`` (with a reason) — nothing is silently
dropped. Each item is processed inside a SAVEPOINT so one bad item cannot abort the batch.

Deduplication layers (see docs/BLUEPRINT.md §6):
    L1 raw (source, item_key)             — enforced at ingest
    L2 canonical URL hash                 — unique constraint on core.articles.url_hash
    L3 same source + title hash ±48 h     — republished / slug-edited articles
    L4 cross-source near-duplicate titles — pg_trgm similarity, linked via duplicate_of_id
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from gjurme.config import Settings
from gjurme.db.models import Article, FeedItem, Source
from gjurme.ingestion.normalize import (
    InvalidURLError,
    canonical_url,
    clean_excerpt,
    clean_text,
    normalize_key,
    normalize_url,
    resolve_published_at,
    sha256_hex,
)

log = logging.getLogger(__name__)

TITLE_DEDUP_WINDOW = timedelta(hours=48)
# Calibrated on real headline pairs (see docs/DECISIONS.md, ADR-008): *different* events whose
# titles differ only by a place name score 0.74–0.85 trigram similarity, while genuine rewrites
# of the same story by another outlet score 0.43–0.68. Trigram similarity therefore only
# identifies near-verbatim copies, and a candidate is accepted only if the words that differ
# are noise (labels like "VIDEO", short stopwords) — never a content word such as a place.
NEAR_DUP_SIMILARITY = 0.8
NEAR_DUP_MIN_WORDS = 4
NOISE_TOKENS = frozenset(
    {
        "video",
        "foto",
        "fotot",
        "live",
        "lajm",
        "lajmi",
        "update",
        "ekskluzive",
        "ekskluzivisht",
        "breaking",
        "urgjent",
        "bomba",
        "shikoni",
        "lexoni",
        "detajet",
        "zyrtare",
        "zyrtarisht",
    }
)


def is_near_verbatim(a: str, b: str) -> bool:
    """True when two normalized titles differ only by noise tokens."""
    diff = set(a.split()) ^ set(b.split())
    return all(tok in NOISE_TOKENS or (len(tok) <= 2 and tok.isalpha()) for tok in diff)


MIN_TITLE_CHARS = 8
MAX_TITLE_CHARS = 500


@dataclass(slots=True)
class ProcessStats:
    processed: int = 0
    accepted: int = 0
    updated: int = 0
    duplicates: Counter[str] = field(default_factory=Counter)
    rejected: Counter[str] = field(default_factory=Counter)
    date_issues: Counter[str] = field(default_factory=Counter)
    near_duplicates: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "processed": self.processed,
            "accepted": self.accepted,
            "updated": self.updated,
            "duplicates": dict(self.duplicates),
            "duplicates_total": sum(self.duplicates.values()),
            "rejected": dict(self.rejected),
            "rejected_total": sum(self.rejected.values()),
            "date_issues": dict(self.date_issues),
            "near_duplicates_linked": self.near_duplicates,
        }


@dataclass(frozen=True, slots=True)
class Candidate:
    title: str
    title_normalized: str
    title_hash: str
    url: str
    canonical_url: str
    url_hash: str
    excerpt: str | None
    author: str | None
    categories: list[str]
    language: str
    published_at: datetime
    published_estimated: bool
    content_hash: str


class ItemRejectedError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def build_candidate(
    item: FeedItem, source: Source, settings: Settings, date_issues: Counter[str]
) -> Candidate:
    """Pure transformation + validation of one raw item. Raises ``ItemRejectedError``."""
    payload = item.payload or {}
    title = clean_text(payload.get("title"))
    if not title:
        raise ItemRejectedError("missing_title")
    if len(title) < MIN_TITLE_CHARS:
        raise ItemRejectedError("title_too_short")
    if len(title) > MAX_TITLE_CHARS:
        title = title[:MAX_TITLE_CHARS]

    link = payload.get("link") or item.link
    if not link:
        raise ItemRejectedError("missing_url")
    try:
        url = normalize_url(link, base=source.homepage_url)
        canon = canonical_url(url)
    except InvalidURLError as exc:
        raise ItemRejectedError(f"invalid_url: {exc}") from exc

    parsed_dt = None
    if payload.get("published_iso"):
        try:
            parsed_dt = datetime.fromisoformat(payload["published_iso"])
        except ValueError:
            parsed_dt = None
    published_at, estimated, issue = resolve_published_at(parsed_dt, item.first_seen_at)
    if issue:
        date_issues[issue] += 1
    if published_at < item.first_seen_at - timedelta(days=settings.max_item_age_days):
        raise ItemRejectedError("too_old")

    excerpt = clean_excerpt(payload.get("summary"), settings.excerpt_max_chars) or None
    if excerpt and normalize_key(excerpt) == normalize_key(title):
        excerpt = None
    title_norm = normalize_key(title)
    author = clean_text(payload.get("author"))[:200] or None
    categories = [c for c in (clean_text(t)[:80] for t in payload.get("tags") or []) if c][:20]
    return Candidate(
        title=title,
        title_normalized=title_norm,
        title_hash=sha256_hex(title_norm),
        url=url,
        canonical_url=canon,
        url_hash=sha256_hex(canon),
        excerpt=excerpt,
        author=author,
        categories=categories,
        language=source.language,
        published_at=published_at,
        published_estimated=estimated,
        content_hash=sha256_hex(title, excerpt or ""),
    )


def _find_same_source_title_dup(session: Session, source_id: int, cand: Candidate) -> int | None:
    return session.scalar(
        select(Article.id)
        .where(
            Article.source_id == source_id,
            Article.title_hash == cand.title_hash,
            Article.published_at.between(
                cand.published_at - TITLE_DEDUP_WINDOW, cand.published_at + TITLE_DEDUP_WINDOW
            ),
        )
        .order_by(Article.id)
        .limit(1)
    )


def _find_cross_source_near_dup(session: Session, source_id: int, cand: Candidate) -> int | None:
    if len(cand.title_normalized.split()) < NEAR_DUP_MIN_WORDS:
        return None
    session.execute(
        text("SELECT set_config('pg_trgm.similarity_threshold', :t, true)"),
        {"t": str(NEAR_DUP_SIMILARITY)},
    )
    rows = session.execute(
        select(Article.id, Article.duplicate_of_id, Article.title_normalized)
        .where(
            Article.source_id != source_id,
            Article.title_normalized.op("%")(cand.title_normalized),
            Article.published_at.between(
                cand.published_at - TITLE_DEDUP_WINDOW, cand.published_at + TITLE_DEDUP_WINDOW
            ),
        )
        .order_by(
            func.similarity(Article.title_normalized, cand.title_normalized).desc(),
            Article.published_at,
        )
        .limit(5)
    ).all()
    for row in rows:
        if is_near_verbatim(row.title_normalized, cand.title_normalized):
            return int(row.duplicate_of_id or row.id)
    return None


def _local_date(dt: datetime, tz: ZoneInfo) -> Any:
    return dt.astimezone(tz).date()


def process_item(
    session: Session,
    item: FeedItem,
    source: Source,
    settings: Settings,
    stats: ProcessStats,
    tz: ZoneInfo,
) -> None:
    now = datetime.now(UTC)
    try:
        cand = build_candidate(item, source, settings, stats.date_issues)
    except ItemRejectedError as rej:
        item.process_status, item.rejection_reason = "rejected", rej.reason
        item.processed_at = now
        stats.rejected[rej.reason.split(":")[0]] += 1
        return

    # L2 — canonical URL already known?
    existing = session.scalar(select(Article).where(Article.url_hash == cand.url_hash))
    if existing is not None:
        item.article_id = existing.id
        item.processed_at = now
        title_changed = existing.title_normalized != cand.title_normalized
        excerpt_changed = bool(cand.excerpt) and cand.excerpt != existing.excerpt
        if existing.source_id == source.id and (title_changed or excerpt_changed):
            # Publisher corrected the entry. Never downgrade: a missing excerpt in the new
            # version keeps the stored one.
            existing.title, existing.title_normalized = cand.title, cand.title_normalized
            existing.title_hash = cand.title_hash
            existing.excerpt = cand.excerpt or existing.excerpt
            existing.content_hash = sha256_hex(existing.title, existing.excerpt or "")
            if title_changed and existing.enrichment_status != "pending":
                # A corrected headline can change topics/entities → re-enrich.
                existing.enrichment_status, existing.enrichment_attempts = "pending", 0
            item.process_status = "updated"
            stats.updated += 1
        else:
            item.process_status = "duplicate"
            item.rejection_reason = "dup_l2_url"
            stats.duplicates["l2_url"] += 1
        return

    # L3 — same source, same headline, within 48 h (republished / URL slug edited)
    same = _find_same_source_title_dup(session, source.id, cand)
    if same is not None:
        item.article_id, item.processed_at = same, now
        item.process_status, item.rejection_reason = "duplicate", "dup_l3_title"
        stats.duplicates["l3_title"] += 1
        return

    # L4 — cross-source near-duplicate (kept, but linked to the earliest story)
    near = _find_cross_source_near_dup(session, source.id, cand)

    stmt = (
        insert(Article)
        .values(
            source_id=source.id,
            url=cand.url,
            canonical_url=cand.canonical_url,
            url_hash=cand.url_hash,
            guid=item.guid,
            title=cand.title,
            title_normalized=cand.title_normalized,
            title_hash=cand.title_hash,
            excerpt=cand.excerpt,
            author=cand.author,
            feed_categories=cand.categories,
            language=cand.language,
            published_at=cand.published_at,
            published_date=_local_date(cand.published_at, tz),
            published_at_estimated=cand.published_estimated,
            content_hash=cand.content_hash,
            duplicate_of_id=near,
        )
        .on_conflict_do_nothing(index_elements=[Article.url_hash])
        .returning(Article.id)
    )
    article_id = session.scalar(stmt)
    if article_id is None:  # lost a race with a concurrent writer — treat as L2 duplicate
        item.article_id = session.scalar(
            select(Article.id).where(Article.url_hash == cand.url_hash)
        )
        item.process_status, item.rejection_reason = "duplicate", "dup_l2_url"
        item.processed_at = now
        stats.duplicates["l2_url"] += 1
        return
    item.article_id, item.processed_at = article_id, now
    item.process_status, item.rejection_reason = "accepted", None
    stats.accepted += 1
    if near is not None:
        stats.near_duplicates += 1


def process_pending(
    session: Session, settings: Settings, *, batch_size: int = 500, max_items: int = 20_000
) -> ProcessStats:
    """Process pending raw items in batches; commits after each batch."""
    stats = ProcessStats()
    tz = ZoneInfo(settings.timezone)
    sources: dict[int, Source] = {s.id: s for s in session.scalars(select(Source))}
    while stats.processed < max_items:
        items = list(
            session.scalars(
                select(FeedItem)
                .where(FeedItem.processed_at.is_(None))
                .order_by(FeedItem.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        if not items:
            break
        for item in items:
            source = sources[item.source_id]
            try:
                with session.begin_nested():
                    process_item(session, item, source, settings, stats, tz)
            except Exception as exc:
                log.exception("processing item failed", extra={"feed_item_id": item.id})
                item.process_status = "rejected"
                item.rejection_reason = f"processing_error: {type(exc).__name__}"[:200]
                item.processed_at = datetime.now(UTC)
                stats.rejected["processing_error"] += 1
            stats.processed += 1
        session.commit()
    log.info("processing done", extra=stats.as_dict())
    return stats
