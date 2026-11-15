"""a free model's daily quota, spread over the day

Adds ``ops.llm_quota``: per model, the requests answered since the provider's daily reset, a
429 for the day that has not cleared, and the daily limit learned from such 429s. The ENRICH
stage reads it to give each run its share of what is left (enrichment/quota.py).

Backward compatible (expand-only): a new table that the previous release does not read.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_quota",
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("quota_day", sa.Date(), nullable=False),
        sa.Column("requests", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("limited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("limited_requests", sa.Integer(), nullable=True),
        sa.Column("learned_limit", sa.Integer(), nullable=True),
        sa.Column("configured_limit", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("model", name=op.f("pk_llm_quota")),
        schema="ops",
    )


def downgrade() -> None:
    op.drop_table("llm_quota", schema="ops")
