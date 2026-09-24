"""denormalize published_date onto bridge tables

Measured (docs/TESTING.md#performance): with 365k articles / 1.09M entity mentions, every
windowed entity query sequentially scanned the *whole* article_entities table to find the ~90k
mentions of a 30-day window, so latency grew linearly with history. Carrying the (immutable)
published_date on the bridges with a (published_date, entity_id|topic_id) index turns windows
into index range scans.

Backward compatible (expand-only): a BEFORE INSERT trigger fills published_date from the
article, so the previous application release — which does not know the column — keeps working
after this migration, and rollbacks never need a database downgrade. The application sets the
date once at ingestion; should it ever be corrected, an AFTER UPDATE trigger on articles keeps
the bridge copies in sync, so the denormalization cannot drift.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("article_entities", "article_topics")


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION core.bridge_fill_published_date() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.published_date IS NULL THEN
                SELECT a.published_date INTO NEW.published_date
                FROM core.articles a WHERE a.id = NEW.article_id;
            END IF;
            RETURN NEW;
        END $$
    """)
    for table in TABLES:
        op.add_column(table, sa.Column("published_date", sa.Date(), nullable=True), schema="core")
        op.execute(f"""
            UPDATE core.{table} b SET published_date = a.published_date
            FROM core.articles a WHERE a.id = b.article_id
        """)
        op.alter_column(table, "published_date", nullable=False, schema="core")
        op.execute(f"""
            CREATE TRIGGER trg_{table}_published_date BEFORE INSERT ON core.{table}
            FOR EACH ROW EXECUTE FUNCTION core.bridge_fill_published_date()
        """)
    op.execute("""
        CREATE OR REPLACE FUNCTION core.article_propagate_published_date() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE core.article_entities SET published_date = NEW.published_date
            WHERE article_id = NEW.id;
            UPDATE core.article_topics SET published_date = NEW.published_date
            WHERE article_id = NEW.id;
            RETURN NULL;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_articles_propagate_published_date
        AFTER UPDATE OF published_date ON core.articles
        FOR EACH ROW WHEN (OLD.published_date IS DISTINCT FROM NEW.published_date)
        EXECUTE FUNCTION core.article_propagate_published_date()
    """)
    op.create_index(
        "ix_article_entities_date_entity",
        "article_entities",
        ["published_date", "entity_id"],
        schema="core",
        postgresql_include=["article_id"],
    )
    op.create_index(
        "ix_article_topics_date_topic",
        "article_topics",
        ["published_date", "topic_id"],
        schema="core",
        postgresql_include=["article_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_article_topics_date_topic", table_name="article_topics", schema="core")
    op.drop_index("ix_article_entities_date_entity", table_name="article_entities", schema="core")
    op.execute("DROP TRIGGER IF EXISTS trg_articles_propagate_published_date ON core.articles")
    op.execute("DROP FUNCTION IF EXISTS core.article_propagate_published_date()")
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_published_date ON core.{table}")
        op.drop_column(table, "published_date", schema="core")
    op.execute("DROP FUNCTION IF EXISTS core.bridge_fill_published_date()")
