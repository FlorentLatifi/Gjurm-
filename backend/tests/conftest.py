"""Shared fixtures.

Integration tests run against a real PostgreSQL database (``TEST_DATABASE_URL``). The schema is
created once per session with the real Alembic migrations — the same code path as production —
and every test starts from empty tables (TRUNCATE), so tests are independent and order-free.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from gjurme.cli import alembic_config
from gjurme.config import Settings
from gjurme.db.reference import sync_topics
from gjurme.ingestion.fetcher import FeedFetcher

FIXTURES = Path(__file__).parent / "fixtures"
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5433/gjurme_test"
)


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / "feeds" / name).read_bytes()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        gjurme_env="test",
        database_url=TEST_DATABASE_URL,
        llm_provider="fake",
        llm_daily_budget_usd=5.0,
        enrich_concurrency=2,
        enrich_max_per_run=500,
        respect_robots_txt=True,
        log_format="text",
    )


# ---------------------------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------------------------
def _db_available(url: str) -> bool:
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 3})
        with engine.connect():
            pass
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    if not _db_available(TEST_DATABASE_URL):
        pytest.skip(f"PostgreSQL not reachable at {TEST_DATABASE_URL}")
    eng = create_engine(TEST_DATABASE_URL)
    with eng.begin() as conn:
        for schema in ("raw", "core", "ops"):
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
    command.upgrade(alembic_config(TEST_DATABASE_URL), "head")
    yield eng
    eng.dispose()


TABLES = (
    "core.article_entities, core.article_topics, core.enrichments, core.entities, "
    "raw.feed_items, raw.feed_fetches, core.articles, core.sources, core.topics, "
    "ops.data_quality_results, ops.alert_events, ops.pipeline_runs, ops.settings"
)


@pytest.fixture
def db(engine: Engine) -> Iterator[sessionmaker[Session]]:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s, s.begin():
        sync_topics(s)
    yield factory


@pytest.fixture
def session(db: sessionmaker[Session]) -> Iterator[Session]:
    with db() as s:
        yield s


# ---------------------------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------------------------
def no_dns_check(_host: str) -> None:
    """Tests use fake hostnames; the SSRF DNS check is tested separately."""


@pytest.fixture
def make_fetcher():  # type: ignore[no-untyped-def]
    clients: list[httpx.Client] = []

    def _make(
        handler,
        *,
        respect_robots: bool = False,
        max_bytes: int = 5_000_000,  # type: ignore[no-untyped-def]
        host_validator=no_dns_check,
    ) -> FeedFetcher:
        client = httpx.Client(transport=httpx.MockTransport(handler), timeout=5)
        clients.append(client)
        return FeedFetcher(
            client=client,
            user_agent="GjurmeTest/1.0",
            max_bytes=max_bytes,
            respect_robots=respect_robots,
            host_validator=host_validator,
        )

    yield _make
    for c in clients:
        c.close()


def feed_server(routes: dict[str, tuple[int, bytes, dict[str, str]]]):  # type: ignore[no-untyped-def]
    """Build a MockTransport handler serving ``url -> (status, body, headers)``."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = str(request.url)
        if key not in routes:
            return httpx.Response(404, content=b"not found")
        status, body, headers = routes[key]
        return httpx.Response(status, content=body, headers=headers)

    return handler
