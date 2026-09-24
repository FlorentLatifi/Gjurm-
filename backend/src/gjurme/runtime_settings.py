"""Runtime switches stored in ``ops.settings`` — changeable via the admin API without redeploys."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from gjurme.db.models import Setting

ENRICHMENT_PAUSE = "enrichment_pause"
RUN_REQUEST = "run_request"


def get_setting(session: Session, key: str) -> dict[str, Any] | None:
    row = session.get(Setting, key)
    return dict(row.value) if row else None


def put_setting(session: Session, key: str, value: dict[str, Any], updated_by: str) -> None:
    stmt = insert(Setting).values(key=key, value=value, updated_by=updated_by)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Setting.key],
        set_={
            "value": stmt.excluded.value,
            "updated_by": stmt.excluded.updated_by,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)


def enrichment_paused(session: Session) -> tuple[bool, str | None]:
    value = get_setting(session, ENRICHMENT_PAUSE) or {}
    return bool(value.get("paused")), value.get("reason")
