"""a summary of each story, written from all its outlets' reports

Adds to ``core.stories`` the story's own summary (Albanian and English), the model that wrote
it, when, and how many outlets it was written from (``stories/summaries.py``, ADR-035). The
story page and cards showed the summary of one article, which the keyword rules leave empty for
two thirds of them.

Backward compatible (expand-only): nullable columns the previous release does not read.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stories", sa.Column("summary_sq", sa.Text(), nullable=True), schema="core")
    op.add_column("stories", sa.Column("summary_en", sa.Text(), nullable=True), schema="core")
    op.add_column("stories", sa.Column("summary_model", sa.Text(), nullable=True), schema="core")
    op.add_column(
        "stories",
        sa.Column("summary_at", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )
    op.add_column(
        "stories", sa.Column("summary_outlets", sa.Integer(), nullable=True), schema="core"
    )


def downgrade() -> None:
    for column in ("summary_outlets", "summary_at", "summary_model", "summary_en", "summary_sq"):
        op.drop_column("stories", column, schema="core")
