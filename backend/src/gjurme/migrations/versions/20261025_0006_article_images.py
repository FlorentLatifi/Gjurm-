"""stories show the outlet's own photo

Adds ``core.articles.image_url`` (the image the outlet puts in its own feed entry; only its
address is kept, the picture is never copied) and ``core.sources.show_images`` (an outlet that
asks for its photos not to be shown is switched off in ``sources.yaml``) — ADR-030.

Backward compatible (expand-only): both columns are nullable or defaulted, so the previous
application release keeps working against this schema.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("image_url", sa.Text(), nullable=True), schema="core")
    op.add_column(
        "sources",
        sa.Column("show_images", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        schema="core",
    )


def downgrade() -> None:
    op.drop_column("sources", "show_images", schema="core")
    op.drop_column("articles", "image_url", schema="core")
