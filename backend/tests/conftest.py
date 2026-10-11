"""Shared fixtures.

Integration tests run against a real PostgreSQL database (``TEST_DATABASE_URL``). The schema is
created once per session with the real Alembic migrations — the same code path as production —
and every test starts from empty tables (TRUNCATE), so tests are independent and order-free.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from datetime import date, timedelta
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


# The feed fixtures carry fixed dates from late September 2026. Tests that run them through
# PROCESS would start rejecting them as too old (MAX_ITEM_AGE_DAYS) a few weeks later.
_FIXTURE_EPOCH = date(2026, 9, 25)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_RFC822_DATE = re.compile(r"(?<=, )(\d{2}) (" + "|".join(_MONTHS) + r") (\d{4})")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?=T)")


def fixture_bytes(name: str, *, fresh: bool = False) -> bytes:
    """Read a feed fixture. ``fresh`` moves its dates forward by whole weeks (weekday names stay
    right) so that the newest item is 1–8 days old today, whatever day the tests run."""
    data = (FIXTURES / "feeds" / name).read_bytes()
    if not fresh:
        return data
    shift = timedelta(days=7 * max(0, (date.today() - _FIXTURE_EPOCH).days // 7))

    def rfc(m: re.Match[str]) -> str:
        d = date(int(m[3]), _MONTHS.index(m[2]) + 1, int(m[1])) + shift
        return f"{d.day:02d} {_MONTHS[d.month - 1]} {d.year}"

    def iso(m: re.Match[str]) -> str:
        return (date(int(m[1]), int(m[2]), int(m[3])) + shift).isoformat()

    text = _ISO_DATE.sub(iso, _RFC822_DATE.sub(rfc, data.decode("utf-8")))
    return text.encode("utf-8")


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
