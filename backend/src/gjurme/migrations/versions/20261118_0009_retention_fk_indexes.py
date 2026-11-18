"""indexes for the foreign keys that retention's deletes follow

Deleting a ``raw.feed_fetches`` row sets ``raw.feed_items.first_fetch_id`` to NULL, and
deleting an ``ops.pipeline_runs`` row sets ``core.enrichments.run_id`` to NULL. Without an
index on those columns PostgreSQL scans the whole referencing table once per deleted row: a
day's retention (about 900 fetches and 48 runs on free hosting) would read the enrichments
and feed items thousands of times over, keeping a scale-to-zero database awake for minutes.

Backward compatible (expand-only): two indexes the previous release does not need.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_feed_items_first_fetch", "feed_items", ["first_fetch_id"], schema="raw")
    op.create_index("ix_enrichments_run", "enrichments", ["run_id"], schema="core")


def downgrade() -> None:
    op.drop_index("ix_enrichments_run", table_name="enrichments", schema="core")
    op.drop_index("ix_feed_items_first_fetch", table_name="feed_items", schema="raw")
