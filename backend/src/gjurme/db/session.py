from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from gjurme.config import get_settings


def build_engine(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 5,
    statement_timeout_ms: int = 15_000,
    application_name: str = "gjurme",
) -> Engine:
    engine = create_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,  # survive DB restarts without surfacing stale-connection errors
        pool_recycle=1800,
        connect_args={"application_name": application_name, "connect_timeout": 10},
    )

    @event.listens_for(engine, "connect")
    def _set_session_defaults(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        # Guard rail: no single query may hold resources indefinitely.
        with dbapi_conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {int(statement_timeout_ms)}")
            cur.execute("SET TIME ZONE 'UTC'")
            # psycopg prepares a statement after 5 executions and PostgreSQL may then switch to
            # a generic plan, which cannot fold the optional filters (`:x IS NULL OR ...`) or
            # use date-range selectivity: analytics queries measured ~2x slower. Re-planning
            # with the real parameters costs ~1 ms (docs/TESTING.md#performance).
            cur.execute("SET plan_cache_mode = force_custom_plan")
        dbapi_conn.commit()

    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    s = get_settings()
    return build_engine(
        s.database_url,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        statement_timeout_ms=s.db_statement_timeout_ms,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any exception."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
