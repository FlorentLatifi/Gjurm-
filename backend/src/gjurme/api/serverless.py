"""The API as a serverless function on Vercel (``api/index.py``; ADR-027).

Two adaptations, both outside ``create_app`` so the app itself stays one and the same:

* **Settings.** ``serverless_defaults`` fills what the dashboard need not repeat: production
  mode, Vercel's own address as the public URL, a small connection pool per function instance
  and CDN caching. Anything set in the environment wins.
* **Paths.** ``vercel.json`` rewrites every API path to the one function and names the path that
  was asked for in ``?__path=``. Whether the function then sees the original path or the rewrite
  target, ``VercelPaths`` hands the app the original, and maps the two paths that Caddy rewrites
  on a server (a crawler's ``/stories/{id}`` and ``/sitemap.xml``) to their API routes.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode

PATH_PARAM = "__path"
# Only link-preview crawlers reach the function with /stories/{id}: vercel.json gives every
# other client the static app there.
_STORY_PREVIEW = re.compile(r"^/stories/([0-9]+)/?$")
_ALIASES = {"/sitemap.xml": "/api/share/sitemap.xml"}


def serverless_defaults(env: Mapping[str, str]) -> dict[str, str]:
    """Environment variables to set because ``env`` lacks them."""
    defaults = {
        "GJURME_ENV": "production",
        "LOG_FORMAT": "json",
        # Vercel replaces X-Forwarded-For with the client's address: it cannot be spoofed.
        "TRUST_PROXY_HEADERS": "true",
        "CDN_CACHE_SECONDS": "300",
        # One instance serves many requests; many instances share the database's connections.
        "DB_POOL_SIZE": "1",
        "DB_MAX_OVERFLOW": "2",
        "API_MAX_CONCURRENT_COMPUTATIONS": "2",
        # Without a token of its own the admin API stays closed: nobody knows this one.
        "ADMIN_API_TOKEN": secrets.token_urlsafe(48),
    }
    host = env.get("VERCEL_PROJECT_PRODUCTION_URL", "").strip()
    if host:  # the production domain: the custom one once added, else <project>.vercel.app
        defaults["PUBLIC_BASE_URL"] = f"https://{host}"
        defaults["CORS_ORIGINS"] = f"https://{host}"
    return {key: value for key, value in defaults.items() if not env.get(key)}


def original_path(path: str, query: str) -> tuple[str, str]:
    """The path (and query, without ``__path``) the app should serve."""
    params = parse_qsl(query, keep_blank_values=True)
    asked = [value for key, value in params if key == PATH_PARAM]
    if asked:
        path = "/" + asked[0].lstrip("/")
        query = urlencode([(key, value) for key, value in params if key != PATH_PARAM])
    if match := _STORY_PREVIEW.match(path):
        path = f"/api/share/stories/{match.group(1)}"
    return _ALIASES.get(path, path), query


class VercelPaths:
    """ASGI middleware: restore the requested path (see the module docstring)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            query = scope.get("query_string", b"").decode("latin-1")
            path, new_query = original_path(scope["path"], query)
            if path != scope["path"] or new_query != query:
                scope = {
                    **scope,
                    "path": path,
                    "raw_path": quote(path).encode("ascii"),
                    "query_string": new_query.encode("latin-1"),
                }
        await self.app(scope, receive, send)
