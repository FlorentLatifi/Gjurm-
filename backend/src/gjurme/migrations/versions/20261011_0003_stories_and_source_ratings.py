"""stories (cross-outlet event clusters) and editorial source ratings

Adds ``core.stories`` and ``core.articles.story_id`` for the CLUSTER stage, and the editorial
rating columns of ``core.sources`` (bias, factuality, ownership, owner, ratings_note) that
coverage bars and blindspots are computed from.

Backward compatible (expand-only): every new column is nullable or has a default, so the
previous application release keeps working against this schema. Existing articles start
unclustered (``story_id IS NULL``) and the next pipeline run clusters them.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIAS = "bias IN ('left', 'lean_left', 'center', 'lean_right', 'right', 'unrated')"
FACTUALITY = "factuality IN ('very_high', 'high', 'mixed', 'low', 'very_low', 'unrated')"
OWNERSHIP = (
    "ownership IN ('private', 'media_group', 'public', 'state', 'public_international', "
    "'nonprofit', 'unknown')"
)


def upgrade() -> None:
    # --- source ratings -------------------------------------------------------------------
    op.add_column(
        "sources",
        sa.Column(
            "bias", sa.String(length=16), server_default=sa.text("'unrated'"), nullable=False
        ),
        schema="core",
    )
    op.add_column(
        "sources",
        sa.Column(
            "factuality", sa.String(length=16), server_default=sa.text("'unrated'"), nullable=False
        ),
        schema="core",
    )
    op.add_column(
        "sources",
        sa.Column(
            "ownership", sa.String(length=24), server_default=sa.text("'unknown'"), nullable=False
        ),
        schema="core",
    )
    op.add_column("sources", sa.Column("owner", sa.Text(), nullable=True), schema="core")
    op.add_column("sources", sa.Column("ratings_note", sa.Text(), nullable=True), schema="core")
    op.create_check_constraint(op.f("ck_sources_bias"), "sources", BIAS, schema="core")
    op.create_check_constraint(op.f("ck_sources_factuality"), "sources", FACTUALITY, schema="core")
    op.create_check_constraint(op.f("ck_sources_ownership"), "sources", OWNERSHIP, schema="core")

    # --- stories --------------------------------------------------------------------------
    op.create_table(
        "stories",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("representative_article_id", sa.BigInteger(), nullable=True),
        sa.Column("first_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column("primary_topic_id", sa.SmallInteger(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["primary_topic_id"],
            ["core.topics.id"],
            name=op.f("fk_stories_primary_topic_id_topics"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stories")),
        schema="core",
    )
    op.create_index("ix_stories_published_date", "stories", ["published_date"], schema="core")
    op.create_index(
        "ix_stories_last_published_at",
        "stories",
        [sa.literal_column("last_published_at DESC")],
        schema="core",
    )
    op.add_column("articles", sa.Column("story_id", sa.BigInteger(), nullable=True), schema="core")
    op.create_foreign_key(
        op.f("fk_articles_story_id_stories"),
        "articles",
        "stories",
        ["story_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_stories_representative_article_id_articles"),
        "stories",
        "articles",
        ["representative_article_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
        ondelete="SET NULL",
    )
    op.create_index("ix_articles_story", "articles", ["story_id"], schema="core")
    op.create_index(
        "ix_articles_story_queue",
        "articles",
        ["published_at"],
        schema="core",
        postgresql_where=sa.text("story_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_articles_story_queue", table_name="articles", schema="core")
    op.drop_index("ix_articles_story", table_name="articles", schema="core")
    op.drop_constraint(
        op.f("fk_stories_representative_article_id_articles"),
        "stories",
        schema="core",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_articles_story_id_stories"), "articles", schema="core", type_="foreignkey"
    )
    op.drop_column("articles", "story_id", schema="core")
    op.drop_index("ix_stories_last_published_at", table_name="stories", schema="core")
    op.drop_index("ix_stories_published_date", table_name="stories", schema="core")
    op.drop_table("stories", schema="core")
    for name in ("ownership", "factuality", "bias"):
        op.drop_constraint(op.f(f"ck_sources_{name}"), "sources", schema="core", type_="check")
    for column in ("ratings_note", "owner", "ownership", "factuality", "bias"):
        op.drop_column("sources", column, schema="core")
