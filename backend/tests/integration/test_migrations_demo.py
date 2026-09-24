from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text

from gjurme.cli import alembic_config
from gjurme.config import Settings
from gjurme.db import Base
from gjurme.demo import DemoRefusedError, generate, seed
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.integration

SCRATCH_DB = "gjurme_migration_test"


@pytest.fixture
def scratch_url(engine) -> str:  # type: ignore[no-untyped-def]
    admin = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH_DB}"))
        conn.execute(text(f"CREATE DATABASE {SCRATCH_DB}"))
    admin.dispose()
    base, _, _ = TEST_DATABASE_URL.rpartition("/")
    return f"{base}/{SCRATCH_DB}"


def test_upgrade_downgrade_upgrade_and_no_drift(scratch_url: str) -> None:
    cfg = alembic_config(scratch_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(scratch_url)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={
                "include_schemas": True,
                "version_table_schema": "ops",
                "include_name": lambda name, type_, _p: (
                    name in ("raw", "core", "ops") if type_ == "schema" else True
                ),
            },
        )
        diff = compare_metadata(ctx, Base.metadata)
    eng.dispose()
    assert diff == [], f"models and migrations drifted: {diff}"


def test_demo_generation_is_deterministic() -> None:
    a, b = generate(days=3, seed=7), generate(days=3, seed=7)
    assert [x.title for x in a] == [x.title for x in b]
    assert all(".invalid/" in x.link for x in a)


def test_demo_refuses_production(session) -> None:  # type: ignore[no-untyped-def]
    prod = Settings(_env_file=None, gjurme_env="production")  # type: ignore[call-arg]
    with pytest.raises(DemoRefusedError):
        seed(session, prod, days=1)


@pytest.mark.skipif(os.environ.get("CI_FAST") == "1", reason="slow")
def test_demo_seed_through_real_pipeline(db, settings) -> None:  # type: ignore[no-untyped-def]
    from gjurme.enrichment.providers import FakeProvider
    from gjurme.enrichment.service import run_enrichment
    from gjurme.ingestion.processor import process_pending

    with db() as s, s.begin():
        n = seed(s, settings, days=5)
    with db() as s:
        processed = process_pending(s, settings)
    assert processed.processed == n
    # Identical headlines are rare (independent template/slot collisions) and legitimately
    # deduplicated; most items must survive as distinct articles.
    assert processed.duplicates.get("l3_title", 0) < 0.05 * n
    assert processed.near_duplicates < 0.25 * n
    assert processed.accepted > 0.9 * n
    stats = run_enrichment(
        db, settings.model_copy(update={"enrich_max_per_run": 10_000}), FakeProvider()
    )
    assert stats.failed == {} and stats.succeeded + stats.cached == processed.accepted
