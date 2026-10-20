"""Free hosting without a server (ADR-027): the Vercel adapter, vercel.json and the settings it
relies on. vercel.json must route exactly as the Caddyfile does on a server."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from gjurme.api.app import create_app
from gjurme.api.serverless import PATH_PARAM, VercelPaths, original_path, serverless_defaults
from gjurme.config import Settings

ROOT = Path(__file__).resolve().parents[3]
VERCEL = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
CADDYFILE = (ROOT / "frontend" / "Caddyfile").read_text(encoding="utf-8")
FUNCTION = "/api/index"


def test_serverless_defaults_fill_only_what_is_missing() -> None:
    env = {"VERCEL_PROJECT_PRODUCTION_URL": "gjurme.vercel.app", "CDN_CACHE_SECONDS": "60"}
    defaults = serverless_defaults(env)
    assert defaults["PUBLIC_BASE_URL"] == defaults["CORS_ORIGINS"] == "https://gjurme.vercel.app"
    assert "CDN_CACHE_SECONDS" not in defaults  # the environment wins
    assert defaults["GJURME_ENV"] == "production" and defaults["TRUST_PROXY_HEADERS"] == "true"
    # no admin token configured: a random one nobody knows keeps the admin API closed
    assert len(defaults["ADMIN_API_TOKEN"]) >= 32
    assert serverless_defaults({})["ADMIN_API_TOKEN"] != serverless_defaults({})["ADMIN_API_TOKEN"]
    assert "PUBLIC_BASE_URL" not in serverless_defaults({})  # a preview build has no domain yet


def test_serverless_defaults_are_a_valid_production_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://neondb_owner:secret@ep-x.aws.neon.tech/neondb")
    for key, value in serverless_defaults(
        {"VERCEL_PROJECT_PRODUCTION_URL": "g.vercel.app"}
    ).items():
        monkeypatch.setenv(key, value)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.validate_for_env()
    assert settings.is_production and settings.trust_proxy_headers
    assert settings.public_base_url == "https://g.vercel.app"
    assert (settings.db_pool_size, settings.db_max_overflow, settings.cdn_cache_seconds) == (
        1,
        2,
        300,
    )
    # fewer concurrent computations than pooled connections, as everywhere
    assert (
        settings.api_max_concurrent_computations < settings.db_pool_size + settings.db_max_overflow
    )


@pytest.mark.parametrize(
    ("path", "query", "expected"),
    [
        # Vercel hands over the path that was asked for, or the rewrite target: same result
        ("/api/v1/stories", f"days=3&{PATH_PARAM}=api/v1/stories", ("/api/v1/stories", "days=3")),
        ("/api/index", f"days=3&{PATH_PARAM}=api/v1/stories", ("/api/v1/stories", "days=3")),
        ("/api/index", f"{PATH_PARAM}=health", ("/health", "")),
        (
            "/api/index",
            f"{PATH_PARAM}=api/v1/search&q=k%C3%ABrkim",
            ("/api/v1/search", "q=k%C3%ABrkim"),
        ),
        # what Caddy rewrites on a server: a crawler's story link and the sitemap
        ("/api/index", f"{PATH_PARAM}=stories/42", ("/api/share/stories/42", "")),
        ("/stories/42", "", ("/api/share/stories/42", "")),
        ("/api/index", f"{PATH_PARAM}=sitemap.xml", ("/api/share/sitemap.xml", "")),
        ("/sitemap.xml", "", ("/api/share/sitemap.xml", "")),
        # anything else passes through untouched
        ("/api/v1/stories", "q=k%C3%ABrkim", ("/api/v1/stories", "q=k%C3%ABrkim")),
    ],
)
def test_original_path(path: str, query: str, expected: tuple[str, str]) -> None:
    assert original_path(path, query) == expected


def test_vercel_paths_rewrites_the_scope_only_when_needed() -> None:
    seen: list[dict[str, Any]] = []

    async def inner(scope: dict[str, Any], _receive: Any, _send: Any) -> None:
        seen.append(scope)

    app = VercelPaths(inner)
    target = {
        "type": "http",
        "path": "/api/index",
        "raw_path": b"/api/index",
        "query_string": f"{PATH_PARAM}=api/v1/status".encode(),
    }
    asyncio.run(app(target, None, None))
    plain = {"type": "http", "path": "/health", "raw_path": b"/health", "query_string": b""}
    asyncio.run(app(plain, None, None))
    asyncio.run(app({"type": "lifespan"}, None, None))
    assert (seen[0]["path"], seen[0]["raw_path"], seen[0]["query_string"]) == (
        "/api/v1/status",
        b"/api/v1/status",
        b"",
    )
    assert seen[1] is plain and seen[2] == {"type": "lifespan"}


# ------------------------------------------------------------------------------------------
# vercel.json
# ------------------------------------------------------------------------------------------
def _crawler_tokens() -> list[str]:
    match = re.search(r"header_regexp User-Agent \(\?i\)\(([^)]*)\)", CADDYFILE)
    assert match
    return match.group(1).split("|")


def _caddy_header(name: str) -> str:
    match = re.search(rf'\n\t\t\??{re.escape(name)} "([^"]*)"', CADDYFILE)
    assert match, name
    return match.group(1)


def test_link_preview_crawlers_are_the_caddyfiles() -> None:
    preview = VERCEL["rewrites"][0]
    assert preview["source"] == "/stories/:id(\\d+)"
    [condition] = preview["has"]
    assert (condition["type"], condition["key"]) == ("header", "user-agent")
    # Vercel's routing is JavaScript regex, matched whole and without an (?i) flag: each
    # letter is a character class, so any casing of the Caddyfile's names matches.
    pattern = re.compile(condition["value"])
    for token in _crawler_tokens():
        for name in (token, token.upper(), token.title()):
            assert pattern.fullmatch(f"Mozilla/5.0 (compatible; {name}/1.0)"), name
    assert pattern.fullmatch("facebookexternalhit/1.1 (+http://www.facebook.com/externalhit)")
    assert pattern.fullmatch("WhatsApp/2.24.20.80 A")
    for reader in (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1",
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    ):
        assert not pattern.fullmatch(reader)  # readers and search engines get the app


def test_security_headers_are_the_caddyfiles() -> None:
    every_path, html, assets = VERCEL["headers"]
    assert every_path["source"] == "/(.*)"
    for header in every_path["headers"]:
        assert header["value"] == _caddy_header(header["key"]), header["key"]
    # the API sends its own, stricter policy: the app's CSP is for every other path
    assert html["source"] == "/:path((?!api/|health).*)"
    assert html["headers"] == [
        {"key": "Content-Security-Policy", "value": _caddy_header("Content-Security-Policy")}
    ]
    assert assets["source"] == "/assets/(.*)"
    assert "immutable" in assets["headers"][0]["value"]


def test_rewrites_send_api_paths_to_the_function_and_the_rest_to_the_app() -> None:
    rewrites = VERCEL["rewrites"]
    fallback = rewrites[-1]
    # last, so the crawler rule and the API win; a missing /assets/ chunk stays a real 404
    assert fallback == {"source": "/:path((?!api/|assets/).*)", "destination": "/index.html"}
    for rule in rewrites[:-1]:
        assert rule["destination"].startswith(f"{FUNCTION}?{PATH_PARAM}="), rule
    assert list(VERCEL["functions"]) == ["api/index.py"]


@pytest.mark.parametrize(
    ("source", "sample"),
    [
        ("/stories/:id(\\d+)", {"id": "42"}),
        ("/sitemap.xml", {}),
        ("/api/:path*", {"path*": "v1/status"}),
        ("/health/:path*", {"path*": "ready"}),
        ("/health", {}),
    ],
)
def test_every_function_rewrite_reaches_an_api_route(source: str, sample: dict[str, str]) -> None:
    [rule] = [r for r in VERCEL["rewrites"] if r["source"] == source]
    destination = rule["destination"]
    for name, value in sample.items():
        destination = destination.replace(f":{name}", value)
    assert ":" not in destination.split("?", 1)[1], destination
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, gjurme_env="test", database_url="postgresql+psycopg://u:p@localhost/x"
    )
    # No database here: a matched route fails on it (500), an unmatched path is a 404.
    client = TestClient(VercelPaths(create_app(settings, sessionmaker())))
    assert client.get(destination).status_code != 404, destination


# ------------------------------------------------------------------------------------------
# Database settings from hosting dashboards
# ------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    ["postgres://u:p@h/db", "postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"],
)
def test_database_url_from_a_dashboard_uses_psycopg(url: str) -> None:
    settings = Settings(_env_file=None, database_url=url)  # type: ignore[call-arg]
    assert settings.database_url == "postgresql+psycopg://u:p@h/db"


def test_the_unpooled_database_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    # The Neon integration on Vercel sets both; PgBouncer in transaction mode would drop the
    # session settings and the pipeline's advisory lock.
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@ep-x-pooler.neon.tech/db")
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", "postgresql://u:p@ep-x.neon.tech/db")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.database_url == "postgresql+psycopg://u:p@ep-x.neon.tech/db"
