"""merged stories keep their URL

Adds ``core.stories.merged_into_id``. The CLUSTER stage now merges two stories when an article
reports both (ADR-020); the absorbed story keeps its row, without articles, pointing at the
story that took them, so its shared links still open the merged story.

Backward compatible (expand-only): the column is nullable, so the previous application release
keeps working against this schema (it shows a merged story's old link as "not found").

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stories", sa.Column("merged_into_id", sa.BigInteger(), nullable=True), schema="core"
    )
    op.create_foreign_key(
        op.f("fk_stories_merged_into_id_stories"),
        "stories",
        "stories",
        ["merged_into_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_stories_merged_into_id_stories"), "stories", schema="core", type_="foreignkey"
    )
    op.drop_column("stories", "merged_into_id", schema="core")
