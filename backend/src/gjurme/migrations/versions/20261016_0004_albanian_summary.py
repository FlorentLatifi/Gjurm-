"""the AI summary in Albanian

Adds ``core.articles.summary_sq`` next to ``summary_en``: prompt v1.2 asks for the one-sentence
summary in both languages, and the site shows Albanian by default (ADR-026).

Backward compatible (expand-only): the column is nullable, so the previous application release
keeps working against this schema. Articles analysed before v1.2 have no Albanian summary until
``gjurme enrich-requeue --older-than-version v1.2`` analyses them again.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("summary_sq", sa.Text(), nullable=True), schema="core")


def downgrade() -> None:
    op.drop_column("articles", "summary_sq", schema="core")
