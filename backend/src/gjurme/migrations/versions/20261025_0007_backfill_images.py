"""photos for articles stored before 0006

The feed entries of the last days are still in ``raw.feed_items`` (kept 7 days on the free
path). Where an outlet put its photo in the entry's description (Telegrafi, among others), the
article stored before migration 0006 takes it now; entries whose photo was only in the full
content, which is never stored, get theirs when the entry is seen again (ADR-030).

Data only: nothing to undo.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        UPDATE core.articles a
        SET image_url = regexp_replace(replace(x.m[1], '&amp;', '&'), '^http://', 'https://')
        FROM (
            SELECT DISTINCT ON (fi.article_id) fi.article_id,
                   regexp_match(fi.payload->>'summary',
                                '<img[^>]*[[:space:]]src="(https?://[^"[:space:]<>]+)"', 'i') AS m
            FROM raw.feed_items fi
            WHERE fi.article_id IS NOT NULL AND fi.payload->>'summary' ILIKE '%<img%'
            ORDER BY fi.article_id, fi.last_seen_at DESC
        ) x
        WHERE x.article_id = a.id AND a.image_url IS NULL AND x.m IS NOT NULL
          AND length(x.m[1]) <= 1000
        """
    )


def downgrade() -> None:
    pass
