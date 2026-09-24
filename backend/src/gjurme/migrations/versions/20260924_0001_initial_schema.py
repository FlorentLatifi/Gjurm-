"""initial schema: raw / core / ops layers

Hand-reviewed autogenerate output. Schemas and the pg_trgm extension (trigram similarity for
near-duplicate detection and fuzzy search) are created explicitly because autogenerate does not
emit them. pg_trgm is a *trusted* extension (PG ≥ 13), so the database owner can create it.

Revision ID: 0001
Revises:
Create Date: 2026-09-24 18:36:17.191170+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for schema in ("raw", "core", "ops"):
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "entities",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_key", sa.Text(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "type IN ('person', 'organization', 'location')", name=op.f("ck_entities_type")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entities")),
        sa.UniqueConstraint("type", "normalized_key", name=op.f("uq_entities_type_normalized_key")),
        schema="core",
    )
    op.create_index(
        "ix_entities_normalized_key_trgm",
        "entities",
        ["normalized_key"],
        unique=False,
        schema="core",
        postgresql_using="gin",
        postgresql_ops={"normalized_key": "gin_trgm_ops"},
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("homepage_url", sa.Text(), nullable=False),
        sa.Column("feed_url", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("country", sa.String(length=8), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "verification_status",
            sa.String(length=16),
            server_default=sa.text("'unverified'"),
            nullable=False,
        ),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("last_modified", sa.Text(), nullable=True),
        sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "verification_status IN ('unverified', 'verified', 'failing')",
            name=op.f("ck_sources_verification"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint("slug", name=op.f("uq_sources_slug")),
        schema="core",
    )
    op.create_table(
        "topics",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("slug", sa.String(length=48), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_sq", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_topics")),
        sa.UniqueConstraint("slug", name=op.f("uq_topics_slug")),
        schema="core",
    )
    op.create_table(
        "alert_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("alert_key", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("delivered", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("suppressed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("delivery_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')", name=op.f("ck_alert_events_severity")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_events")),
        schema="ops",
    )
    op.create_index(
        "ix_alert_events_key_created",
        "alert_events",
        ["alert_key", sa.literal_column("created_at DESC")],
        unique=False,
        schema="ops",
    )
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("stages", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("hostname", sa.Text(), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed', 'skipped_locked', 'abandoned')",
            name=op.f("ck_pipeline_runs_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_runs")),
        schema="ops",
    )
    op.create_index(
        "ix_pipeline_runs_started",
        "pipeline_runs",
        [sa.literal_column("started_at DESC")],
        unique=False,
        schema="ops",
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
        schema="ops",
    )
    op.create_table(
        "articles",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("guid", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_normalized", sa.Text(), nullable=False),
        sa.Column("title_hash", sa.String(length=64), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column(
            "feed_categories",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column(
            "published_at_estimated", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("duplicate_of_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "enrichment_status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "enrichment_attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("primary_topic_id", sa.SmallInteger(), nullable=True),
        sa.Column("sentiment_label", sa.String(length=16), nullable=True),
        sa.Column("sentiment_score", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=True),
        sa.Column("detected_language", sa.String(length=8), nullable=True),
        sa.Column(
            "countries",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("summary_en", sa.Text(), nullable=True),
        sa.Column("enrichment_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("is_hidden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("hidden_reason", sa.Text(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "enrichment_status IN ('pending', 'succeeded', 'failed', 'skipped')",
            name=op.f("ck_articles_enrichment_status"),
        ),
        sa.CheckConstraint(
            "sentiment_label IS NULL OR sentiment_label IN ('negative', 'neutral', 'positive')",
            name=op.f("ck_articles_sentiment_label"),
        ),
        sa.CheckConstraint(
            "sentiment_score IS NULL OR (sentiment_score BETWEEN -1 AND 1)",
            name=op.f("ck_articles_sentiment_score"),
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_id"],
            ["core.articles.id"],
            name=op.f("fk_articles_duplicate_of_id_articles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["primary_topic_id"],
            ["core.topics.id"],
            name=op.f("fk_articles_primary_topic_id_topics"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["core.sources.id"], name=op.f("fk_articles_source_id_sources")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_articles")),
        sa.UniqueConstraint("url_hash", name=op.f("uq_articles_url_hash")),
        schema="core",
    )
    op.create_index(
        "ix_articles_duplicate_of", "articles", ["duplicate_of_id"], unique=False, schema="core"
    )
    op.create_index(
        "ix_articles_enrichment_queue",
        "articles",
        ["enrichment_status", sa.literal_column("published_at DESC")],
        unique=False,
        schema="core",
        postgresql_where=sa.text("enrichment_status IN ('pending', 'failed')"),
    )
    op.create_index(
        "ix_articles_primary_topic_date",
        "articles",
        ["primary_topic_id", "published_date"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_articles_published_at",
        "articles",
        [sa.literal_column("published_at DESC")],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_articles_published_date", "articles", ["published_date"], unique=False, schema="core"
    )
    op.create_index(
        "ix_articles_source_published",
        "articles",
        ["source_id", sa.literal_column("published_at DESC")],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_articles_source_title_hash",
        "articles",
        ["source_id", "title_hash"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_articles_title_trgm",
        "articles",
        ["title_normalized"],
        unique=False,
        schema="core",
        postgresql_using="gin",
        postgresql_ops={"title_normalized": "gin_trgm_ops"},
    )
    op.create_table(
        "data_quality_results",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("check_name", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("observed", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("threshold", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name=op.f("ck_data_quality_results_severity"),
        ),
        sa.CheckConstraint(
            "status IN ('pass', 'warn', 'fail')", name=op.f("ck_data_quality_results_status")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ops.pipeline_runs.id"],
            name=op.f("fk_data_quality_results_run_id_pipeline_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_quality_results")),
        schema="ops",
    )
    op.create_index(
        "ix_dq_results_check_created",
        "data_quality_results",
        ["check_name", sa.literal_column("created_at DESC")],
        unique=False,
        schema="ops",
    )
    op.create_index(
        "ix_dq_results_run", "data_quality_results", ["run_id"], unique=False, schema="ops"
    )
    op.create_table(
        "feed_fetches",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("http_status", sa.SmallInteger(), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("items_seen", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("items_new", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("items_changed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("malformed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("malformed_reason", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('ok', 'not_modified', 'http_error', 'timeout', 'network_error', 'parse_error', 'too_large', 'robots_disallowed', 'invalid_url')",
            name=op.f("ck_feed_fetches_status"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ops.pipeline_runs.id"],
            name=op.f("fk_feed_fetches_run_id_pipeline_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["core.sources.id"],
            name=op.f("fk_feed_fetches_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feed_fetches")),
        schema="raw",
    )
    op.create_index("ix_feed_fetches_run", "feed_fetches", ["run_id"], unique=False, schema="raw")
    op.create_index(
        "ix_feed_fetches_source_started",
        "feed_fetches",
        ["source_id", sa.literal_column("started_at DESC")],
        unique=False,
        schema="raw",
    )
    op.create_table(
        "article_entities",
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["core.articles.id"],
            name=op.f("fk_article_entities_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["core.entities.id"],
            name=op.f("fk_article_entities_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("article_id", "entity_id", name=op.f("pk_article_entities")),
        schema="core",
    )
    op.create_index(
        "ix_article_entities_entity_article",
        "article_entities",
        ["entity_id", "article_id"],
        unique=False,
        schema="core",
    )
    op.create_table(
        "article_topics",
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_id", sa.SmallInteger(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["core.articles.id"],
            name=op.f("fk_article_topics_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"], ["core.topics.id"], name=op.f("fk_article_topics_topic_id_topics")
        ),
        sa.PrimaryKeyConstraint("article_id", "topic_id", name=op.f("pk_article_topics")),
        schema="core",
    )
    op.create_index(
        "ix_article_topics_topic_article",
        "article_topics",
        ["topic_id", "article_id"],
        unique=False,
        schema="core",
    )
    op.create_table(
        "enrichments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt", sa.SmallInteger(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cost_usd",
            sa.Numeric(precision=12, scale=6),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'cached', 'failed', 'invalid', 'refused')",
            name=op.f("ck_enrichments_status"),
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["core.articles.id"],
            name=op.f("fk_enrichments_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ops.pipeline_runs.id"],
            name=op.f("fk_enrichments_run_id_pipeline_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_enrichments")),
        schema="core",
    )
    op.create_index(
        "ix_enrichments_article", "enrichments", ["article_id"], unique=False, schema="core"
    )
    op.create_index(
        "ix_enrichments_cache_lookup",
        "enrichments",
        ["input_hash", "prompt_version", "model"],
        unique=False,
        schema="core",
        postgresql_where=sa.text("status IN ('succeeded', 'cached')"),
    )
    op.create_index(
        "ix_enrichments_created_at", "enrichments", ["created_at"], unique=False, schema="core"
    )
    op.create_index(
        "uq_enrichments_current_per_article",
        "enrichments",
        ["article_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "feed_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("item_key", sa.String(length=64), nullable=False),
        sa.Column("guid", sa.Text(), nullable=True),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("first_fetch_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "process_status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("article_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "process_status IN ('pending', 'accepted', 'updated', 'duplicate', 'rejected')",
            name=op.f("ck_feed_items_process_status"),
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["core.articles.id"],
            name=op.f("fk_feed_items_article_id_articles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["first_fetch_id"],
            ["raw.feed_fetches.id"],
            name=op.f("fk_feed_items_first_fetch_id_feed_fetches"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["core.sources.id"],
            name=op.f("fk_feed_items_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feed_items")),
        sa.UniqueConstraint("source_id", "item_key", name=op.f("uq_feed_items_source_id_item_key")),
        schema="raw",
    )
    op.create_index(
        "ix_feed_items_first_seen", "feed_items", ["first_seen_at"], unique=False, schema="raw"
    )
    op.create_index(
        "ix_feed_items_unprocessed",
        "feed_items",
        ["id"],
        unique=False,
        schema="raw",
        postgresql_where=sa.text("processed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_feed_items_unprocessed",
        table_name="feed_items",
        schema="raw",
        postgresql_where=sa.text("processed_at IS NULL"),
    )
    op.drop_index("ix_feed_items_first_seen", table_name="feed_items", schema="raw")
    op.drop_table("feed_items", schema="raw")
    op.drop_index(
        "uq_enrichments_current_per_article",
        table_name="enrichments",
        schema="core",
        postgresql_where=sa.text("is_current"),
    )
    op.drop_index("ix_enrichments_created_at", table_name="enrichments", schema="core")
    op.drop_index(
        "ix_enrichments_cache_lookup",
        table_name="enrichments",
        schema="core",
        postgresql_where=sa.text("status IN ('succeeded', 'cached')"),
    )
    op.drop_index("ix_enrichments_article", table_name="enrichments", schema="core")
    op.drop_table("enrichments", schema="core")
    op.drop_index("ix_article_topics_topic_article", table_name="article_topics", schema="core")
    op.drop_table("article_topics", schema="core")
    op.drop_index(
        "ix_article_entities_entity_article", table_name="article_entities", schema="core"
    )
    op.drop_table("article_entities", schema="core")
    op.drop_index("ix_feed_fetches_source_started", table_name="feed_fetches", schema="raw")
    op.drop_index("ix_feed_fetches_run", table_name="feed_fetches", schema="raw")
    op.drop_table("feed_fetches", schema="raw")
    op.drop_index("ix_dq_results_run", table_name="data_quality_results", schema="ops")
    op.drop_index("ix_dq_results_check_created", table_name="data_quality_results", schema="ops")
    op.drop_table("data_quality_results", schema="ops")
    op.drop_index(
        "ix_articles_title_trgm",
        table_name="articles",
        schema="core",
        postgresql_using="gin",
        postgresql_ops={"title_normalized": "gin_trgm_ops"},
    )
    op.drop_index("ix_articles_source_title_hash", table_name="articles", schema="core")
    op.drop_index("ix_articles_source_published", table_name="articles", schema="core")
    op.drop_index("ix_articles_published_date", table_name="articles", schema="core")
    op.drop_index("ix_articles_published_at", table_name="articles", schema="core")
    op.drop_index("ix_articles_primary_topic_date", table_name="articles", schema="core")
    op.drop_index(
        "ix_articles_enrichment_queue",
        table_name="articles",
        schema="core",
        postgresql_where=sa.text("enrichment_status IN ('pending', 'failed')"),
    )
    op.drop_index("ix_articles_duplicate_of", table_name="articles", schema="core")
    op.drop_table("articles", schema="core")
    op.drop_table("settings", schema="ops")
    op.drop_index("ix_pipeline_runs_started", table_name="pipeline_runs", schema="ops")
    op.drop_table("pipeline_runs", schema="ops")
    op.drop_index("ix_alert_events_key_created", table_name="alert_events", schema="ops")
    op.drop_table("alert_events", schema="ops")
    op.drop_table("topics", schema="core")
    op.drop_table("sources", schema="core")
    op.drop_index(
        "ix_entities_normalized_key_trgm",
        table_name="entities",
        schema="core",
        postgresql_using="gin",
        postgresql_ops={"normalized_key": "gin_trgm_ops"},
    )
    op.drop_table("entities", schema="core")
    op.execute("DROP SCHEMA IF EXISTS raw CASCADE")
    op.execute("DROP SCHEMA IF EXISTS core CASCADE")
