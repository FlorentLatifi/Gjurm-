"""Alembic environment.

The URL comes from ``DATABASE_URL`` (via ``gjurme.config``) so migrations can never be pointed at
a database by a stale ini file. Migrations run inside a single transaction and take an advisory
lock so that two containers starting at once cannot migrate concurrently.
"""

from __future__ import annotations

from typing import Any

from alembic import context
from sqlalchemy import create_engine, pool, text

from gjurme.config import get_settings
from gjurme.db import Base

MIGRATION_LOCK_KEY = 7_230_001

config = context.config
target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: Any) -> bool:
    if type_ == "schema":
        return name in ("raw", "core", "ops")
    return True


def _url() -> str:
    return config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
        version_table_schema="ops",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS ops"))
        connection.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            version_table_schema="ops",
            compare_type=True,
            transaction_per_migration=False,
        )
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
