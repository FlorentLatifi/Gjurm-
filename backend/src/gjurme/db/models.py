"""ORM models.

Layering (Postgres schemas):

* ``raw``  — what we received, as received. Append-only, replayable.
* ``core`` — curated analytical model (facts, dimensions, bridges).
* ``ops``  — pipeline runs, data quality, alerts, runtime settings.

Enumerations are ``text`` + ``CHECK`` constraints rather than PostgreSQL ENUM types: adding a
value is a one-line migration and never requires ``ALTER TYPE`` inside a transaction.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gjurme.db.base import Base

TZ = DateTime(timezone=True)


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


FETCH_STATUSES = (
    "ok",
    "not_modified",
    "http_error",
    "timeout",
    "network_error",
    "parse_error",
    "too_large",
    "robots_disallowed",
    "invalid_url",
)
ITEM_PROCESS_STATUSES = ("pending", "accepted", "updated", "duplicate", "rejected")
ENRICHMENT_STATUSES = ("pending", "succeeded", "failed", "skipped")
ENRICHMENT_ATTEMPT_STATUSES = ("succeeded", "cached", "failed", "invalid", "refused")
ENTITY_TYPES = ("person", "organization", "location")
SENTIMENT_LABELS = ("negative", "neutral", "positive")
RUN_STATUSES = ("running", "succeeded", "partial", "failed", "skipped_locked", "abandoned")
DQ_STATUSES = ("pass", "warn", "fail")
SEVERITIES = ("info", "warning", "critical")


# =============================================================================================
# core — dimensions
# =============================================================================================
class Source(Base):
    """Dimension: a news publisher feed. Seeded from ``sources.yaml``."""

    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            _in("verification_status", ("unverified", "verified", "failing")), name="verification"
        ),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(Text)
    homepage_url: Mapped[str] = mapped_column(Text)
    feed_url: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8))
    country: Mapped[str] = mapped_column(String(8))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    verification_status: Mapped[str] = mapped_column(
        String(16), server_default=text("'unverified'")
    )
    disabled_reason: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    last_fetch_at: Mapped[datetime | None] = mapped_column(TZ)
    last_success_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), onupdate=func.now())


class Topic(Base):
    """Dimension: controlled topic taxonomy (seeded, not LLM-invented)."""

    __tablename__ = "topics"
    __table_args__ = ({"schema": "core"},)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    slug: Mapped[str] = mapped_column(String(48), unique=True)
    name_en: Mapped[str] = mapped_column(Text)
    name_sq: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger)


class Entity(Base):
    """Dimension: a person, organization or location mentioned in the news."""

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("type", "normalized_key"),
        CheckConstraint(_in("type", ENTITY_TYPES), name="type"),
        Index(
            "ix_entities_normalized_key_trgm",
            "normalized_key",
            postgresql_using="gin",
            postgresql_ops={"normalized_key": "gin_trgm_ops"},
        ),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    type: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(Text)
    normalized_key: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


# =============================================================================================
# core — fact + bridges
# =============================================================================================
class Article(Base):
    """Fact: one published news article, identified by its canonical URL.

    Grain: one row per canonical URL. Enrichment attributes of the *current* enrichment are
    denormalized here (topic, sentiment, summary) so analytical queries need no extra join;
    the full attempt history lives in ``core.enrichments``.
    """

    __tablename__ = "articles"
    __table_args__ = (
        CheckConstraint(_in("enrichment_status", ENRICHMENT_STATUSES), name="enrichment_status"),
        CheckConstraint(
            f"sentiment_label IS NULL OR {_in('sentiment_label', SENTIMENT_LABELS)}",
            name="sentiment_label",
        ),
        CheckConstraint(
            "sentiment_score IS NULL OR (sentiment_score BETWEEN -1 AND 1)", name="sentiment_score"
        ),
        Index("ix_articles_published_at", text("published_at DESC")),
        Index("ix_articles_published_date", "published_date"),
        Index("ix_articles_source_published", "source_id", text("published_at DESC")),
        Index("ix_articles_source_title_hash", "source_id", "title_hash"),
        Index("ix_articles_primary_topic_date", "primary_topic_id", "published_date"),
        Index(
            "ix_articles_enrichment_queue",
            "enrichment_status",
            text("published_at DESC"),
            postgresql_where=text("enrichment_status IN ('pending', 'failed')"),
        ),
        Index(
            "ix_articles_title_trgm",
            "title_normalized",
            postgresql_using="gin",
            postgresql_ops={"title_normalized": "gin_trgm_ops"},
        ),
        Index("ix_articles_duplicate_of", "duplicate_of_id"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("core.sources.id"))
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)
    guid: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    title_normalized: Mapped[str] = mapped_column(Text)
    title_hash: Mapped[str] = mapped_column(String(64))
    excerpt: Mapped[str | None] = mapped_column(Text)  # internal only; never exposed publicly
    author: Mapped[str | None] = mapped_column(Text)
    feed_categories: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    language: Mapped[str] = mapped_column(String(8))
    published_at: Mapped[datetime] = mapped_column(TZ)
    published_date: Mapped[date] = mapped_column(Date)
    published_at_estimated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    content_hash: Mapped[str] = mapped_column(String(64))
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("core.articles.id", ondelete="SET NULL")
    )
    # --- enrichment state + current enrichment (denormalized) ---
    enrichment_status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"))
    enrichment_attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    enriched_at: Mapped[datetime | None] = mapped_column(TZ)
    primary_topic_id: Mapped[int | None] = mapped_column(ForeignKey("core.topics.id"))
    sentiment_label: Mapped[str | None] = mapped_column(String(16))
    sentiment_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    event_type: Mapped[str | None] = mapped_column(String(32))
    detected_language: Mapped[str | None] = mapped_column(String(8))
    countries: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    summary_en: Mapped[str | None] = mapped_column(Text)
    enrichment_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    # --- moderation / takedown ---
    is_hidden: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    hidden_reason: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), onupdate=func.now())

    source: Mapped[Source] = relationship(lazy="joined")
    primary_topic: Mapped[Topic | None] = relationship(lazy="joined")


class ArticleTopic(Base):
    """Bridge: article × topic (primary + up to 3 secondary)."""

    __tablename__ = "article_topics"
    __table_args__ = (
        Index("ix_article_topics_topic_article", "topic_id", "article_id"),
        {"schema": "core"},
    )

    article_id: Mapped[int] = mapped_column(
        ForeignKey("core.articles.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(ForeignKey("core.topics.id"), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class ArticleEntity(Base):
    """Bridge: article × entity mention."""

    __tablename__ = "article_entities"
    __table_args__ = (
        Index("ix_article_entities_entity_article", "entity_id", "article_id"),
        {"schema": "core"},
    )

    article_id: Mapped[int] = mapped_column(
        ForeignKey("core.articles.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("core.entities.id", ondelete="CASCADE"), primary_key=True
    )


class Enrichment(Base):
    """History: one LLM enrichment attempt (or cache hit) for one article.

    Exactly one row per article may be ``is_current``; analytics use the denormalized copy on
    ``core.articles``. Keeping every attempt gives full lineage: model, prompt version, tokens,
    cost, latency and the raw response of failures.
    """

    __tablename__ = "enrichments"
    __table_args__ = (
        CheckConstraint(_in("status", ENRICHMENT_ATTEMPT_STATUSES), name="status"),
        Index(
            "uq_enrichments_current_per_article",
            "article_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("ix_enrichments_created_at", "created_at"),
        Index(
            "ix_enrichments_cache_lookup",
            "input_hash",
            "prompt_version",
            "model",
            postgresql_where=text("status IN ('succeeded', 'cached')"),
        ),
        Index("ix_enrichments_article", "article_id"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("core.articles.id", ondelete="CASCADE"))
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ops.pipeline_runs.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    attempt: Mapped[int] = mapped_column(SmallInteger)
    input_hash: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default=text("0"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(Text)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    raw_response: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    quality_flags: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_current: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


# =============================================================================================
# raw
# =============================================================================================
class FeedFetch(Base):
    """Raw: one HTTP fetch of one feed. Doubles as the source-health log."""

    __tablename__ = "feed_fetches"
    __table_args__ = (
        CheckConstraint(_in("status", FETCH_STATUSES), name="status"),
        Index("ix_feed_fetches_source_started", "source_id", text("started_at DESC")),
        Index("ix_feed_fetches_run", "run_id"),
        {"schema": "raw"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ops.pipeline_runs.id", ondelete="SET NULL")
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("core.sources.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(TZ)
    duration_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    bytes: Mapped[int | None] = mapped_column(Integer)
    items_seen: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    items_new: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    items_changed: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    malformed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    malformed_reason: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class FeedItem(Base):
    """Raw: one distinct feed entry per source, as parsed from the feed (verbatim subset).

    ``(source_id, item_key)`` is the L1 dedup key: re-fetching the same entry only bumps
    ``last_seen_at``. If an entry's content changes (headline correction), ``content_hash``
    changes and the item is re-queued for processing.
    """

    __tablename__ = "feed_items"
    __table_args__ = (
        UniqueConstraint("source_id", "item_key"),
        CheckConstraint(_in("process_status", ITEM_PROCESS_STATUSES), name="process_status"),
        Index(
            "ix_feed_items_unprocessed",
            "id",
            postgresql_where=text("processed_at IS NULL"),
        ),
        Index("ix_feed_items_first_seen", "first_seen_at"),
        {"schema": "raw"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("core.sources.id", ondelete="CASCADE"))
    item_key: Mapped[str] = mapped_column(String(64))
    guid: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    first_fetch_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw.feed_fetches.id", ondelete="SET NULL")
    )
    first_seen_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    process_status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"))
    processed_at: Mapped[datetime | None] = mapped_column(TZ)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    article_id: Mapped[int | None] = mapped_column(
        ForeignKey("core.articles.id", ondelete="SET NULL")
    )


# =============================================================================================
# ops
# =============================================================================================
class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="status"),
        Index("ix_pipeline_runs_started", text("started_at DESC")),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    trigger: Mapped[str] = mapped_column(String(32))
    stages: Mapped[list[str]] = mapped_column(ARRAY(Text))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)
    hostname: Mapped[str | None] = mapped_column(Text)
    pid: Mapped[int | None] = mapped_column(Integer)


class DataQualityResult(Base):
    __tablename__ = "data_quality_results"
    __table_args__ = (
        CheckConstraint(_in("status", DQ_STATUSES), name="status"),
        CheckConstraint(_in("severity", SEVERITIES), name="severity"),
        Index("ix_dq_results_run", "run_id"),
        Index("ix_dq_results_check_created", "check_name", text("created_at DESC")),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ops.pipeline_runs.id", ondelete="CASCADE")
    )
    check_name: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(8))
    observed: Mapped[float | None] = mapped_column(Numeric(14, 4))
    threshold: Mapped[float | None] = mapped_column(Numeric(14, 4))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        CheckConstraint(_in("severity", SEVERITIES), name="severity"),
        Index("ix_alert_events_key_created", "alert_key", text("created_at DESC")),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    alert_key: Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    delivered: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    suppressed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    delivery_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class Setting(Base):
    """Runtime switches editable without a redeploy (e.g. enrichment kill switch)."""

    __tablename__ = "settings"
    __table_args__ = ({"schema": "ops"},)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[str | None] = mapped_column(Text)
