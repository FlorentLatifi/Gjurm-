"""Reference data (controlled vocabularies) — synced from code, idempotently."""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from gjurme.db.models import Topic
from gjurme.taxonomy import TOPICS


def sync_topics(session: Session) -> int:
    rows = [
        {
            "id": t.id,
            "slug": t.slug,
            "name_en": t.name_en,
            "name_sq": t.name_sq,
            "description": t.description,
            "sort_order": i,
        }
        for i, t in enumerate(TOPICS)
    ]
    stmt = insert(Topic).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Topic.id],
        set_={
            c: stmt.excluded[c] for c in ("slug", "name_en", "name_sq", "description", "sort_order")
        },
    )
    session.execute(stmt)
    return len(rows)
