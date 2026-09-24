"""Cross-process mutual exclusion via PostgreSQL session-level advisory locks.

Why advisory locks: whichever process triggers a run (scheduler, CLI, a second scheduler
replica started by mistake, a cron double-fire), only one can hold the lock. The lock lives on a
dedicated connection, so if the process dies the connection closes and PostgreSQL releases the
lock automatically — no stale lock files, no manual cleanup.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, text

PIPELINE_LOCK_KEY = 7_230_100
BACKFILL_LOCK_KEY = 7_230_101


@contextmanager
def advisory_lock(engine: Engine, key: int) -> Iterator[bool]:
    """Yield ``True`` if the lock was acquired, ``False`` if another holder has it."""
    conn = engine.connect()
    try:
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar())
        conn.commit()
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                conn.commit()
    finally:
        conn.close()


def lock_is_held(engine: Engine, key: int) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
                    "AND objid = :k AND granted)"
                ),
                {"k": key},
            ).scalar()
        )
