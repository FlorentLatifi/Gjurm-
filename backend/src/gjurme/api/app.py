"""FastAPI application factory.

Run in production with::

    uvicorn gjurme.api.app:create_app --factory --host 0.0.0.0 --port 8000 --proxy-headers
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry
from sqlalchemy.orm import Session, sessionmaker

from gjurme import __version__
from gjurme.api.metrics import ApiMetrics, PipelineCollector
from gjurme.api.routers.ops import admin_router, health_router
from gjurme.api.routers.public import router as public_router
from gjurme.api.routers.share import share_router
from gjurme.api.security import (
    API_CSP,
    DOCS_CSP,
    SECURITY_HEADERS,
    Overloaded,
    RateLimiter,
    TTLCache,
    bucket_for,
    client_ip,
    rate_key,
)
from gjurme.config import Settings, get_settings
from gjurme.logging_setup import configure_logging, request_id_var

log = logging.getLogger("gjurme.api")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

DESCRIPTION = """
**GJURMË** — AI-powered intelligence on Albanian & Balkan news.

Public, read-only endpoints expose *metadata and derived analysis only* (headline, source, time,
AI-assigned topics, entities, tone and a one-sentence English summary) and always link to the
original article. Admin endpoints require a Bearer token.

Dates are local calendar days in Europe/Tirane. Rate limits apply per client IP.
"""


def _error(
    status: int, code: str, message: str, details: Any = None, headers: dict[str, str] | None = None
) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body, headers=headers)


def create_app(
    settings: Settings | None = None, session_factory: sessionmaker[Session] | None = None
) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_for_env()
    configure_logging(settings.log_level, settings.log_format)
    if session_factory is None:
        from gjurme.db.session import get_sessionmaker

        session_factory = get_sessionmaker()

    docs = settings.expose_docs
    app = FastAPI(
        title="GJURMË API",
        version=__version__,
        description=DESCRIPTION,
        docs_url="/api/docs" if docs else None,
        redoc_url="/api/redoc" if docs else None,
        openapi_url="/api/openapi.json" if docs else None,
        contact={"name": "GJURMË", "url": settings.contact_url},
        license_info={"name": "MIT (code). Article content belongs to its publishers."},
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.cache = TTLCache(
        settings.api_cache_ttl_seconds, max_computations=settings.api_max_concurrent_computations
    )
    app.state.limiter = RateLimiter()
    registry = CollectorRegistry()
    registry.register(PipelineCollector(session_factory, settings.llm_daily_budget_usd))
    app.state.registry = registry
    app.state.metrics = ApiMetrics(registry)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )

    async def _call(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Unexpected errors become a 500 here, inside ``observe``, so they get the request id
        in the log, the security and cache headers, and a count in the request metrics."""
        try:
            return await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"path": request.url.path})
            return _error(
                500, "internal_error", "Unexpected error. The request id identifies it in the logs."
            )

    async def _with_etag(request: Request, response: Response) -> Response:
        """A weak ETag on a cacheable API answer, and 304 Not Modified when the browser already
        holds this exact body: once max-age has passed, a returning reader revalidates instead
        of downloading the same JSON again."""
        iterator = getattr(response, "body_iterator", None)
        if iterator is None:
            body = bytes(response.body)
        else:
            body = b"".join([bytes(chunk) async for chunk in iterator])
        tag = hashlib.blake2b(body, digest_size=12).hexdigest()
        headers = dict(response.headers)
        headers["ETag"] = f'W/"{tag}"'
        # weak comparison (RFC 9110 13.1.2): the W/ prefix does not matter
        seen = {
            t.strip().removeprefix("W/").strip('"')
            for t in request.headers.get("if-none-match", "").split(",")
        }
        if tag in seen or "*" in seen:
            for name in ("content-length", "content-type"):
                headers.pop(name, None)
            return Response(status_code=304, headers=headers)
        return Response(content=body, status_code=response.status_code, headers=headers)

    @app.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        started = time.perf_counter()
        path = request.url.path
        ip = client_ip(request, settings.trust_proxy_headers)
        try:
            if path.startswith("/api/") and request.method != "OPTIONS":
                bucket = bucket_for(path)
                limit = {
                    "search": settings.rate_limit_search_per_minute,
                    "admin": settings.rate_limit_search_per_minute,
                }.get(bucket, settings.rate_limit_per_minute)
                allowed, retry = app.state.limiter.hit(rate_key(ip), bucket, limit)
                if not allowed:
                    app.state.metrics.rate_limited.labels(bucket).inc()
                    response: Response = _error(
                        429,
                        "rate_limited",
                        "Too many requests — slow down.",
                        headers={"Retry-After": str(max(1, round(retry)))},
                    )
                else:
                    response = await _call(request, call_next)
            else:
                response = await _call(request, call_next)
        finally:
            request_id_var.reset(token)
        elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        app.state.metrics.requests.labels(request.method, template, response.status_code).inc()
        app.state.metrics.latency.labels(template).observe(elapsed)

        response.headers["X-Request-ID"] = rid
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        is_docs = path.startswith(("/api/docs", "/api/redoc"))
        response.headers.setdefault("Content-Security-Policy", DOCS_CSP if is_docs else API_CSP)
        if (
            request.method == "GET"
            and response.status_code == 200
            and path.startswith("/api/v1/")
            and not path.startswith("/api/v1/admin")
            and path != "/api/v1/status"
        ):
            response.headers.setdefault(
                "Cache-Control", "public, max-age=60, stale-while-revalidate=120"
            )
        else:
            response.headers.setdefault("Cache-Control", "no-store")
        if (
            request.method == "GET"
            and response.status_code == 200
            and path.startswith("/api/v1/")
            and not path.startswith("/api/v1/admin")
        ):
            response = await _with_etag(request, response)
        if response.status_code >= 500 or elapsed > 2.0:
            log.warning(
                "slow or failed request",
                extra={
                    "method": request.method,
                    "path": path,
                    "status": response.status_code,
                    "duration_ms": round(elapsed * 1000),
                    "request_id": rid,
                },
            )
        log.debug(
            "request",
            extra={
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration_ms": round(elapsed * 1000),
                # privacy: never log raw client IPs
                "client": hashlib.sha256(ip.encode()).hexdigest()[:12],
            },
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return _error(
                exc.status_code,
                exc.detail["code"],
                exc.detail.get("message", ""),
                headers=dict(exc.headers) if exc.headers else None,
            )
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            503: "unavailable",
        }.get(exc.status_code, "error")
        headers = dict(exc.headers) if exc.headers else None
        return _error(exc.status_code, code, str(exc.detail), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg")} for e in exc.errors()
        ]
        return _error(422, "validation_error", "Invalid request parameters", details)

    @app.exception_handler(Overloaded)
    async def overloaded(_request: Request, _exc: Overloaded) -> JSONResponse:
        app.state.metrics.rate_limited.labels("overloaded").inc()
        return _error(
            503,
            "overloaded",
            "Busy computing other responses — retry shortly.",
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:  # last resort
        log.exception("unhandled error", extra={"path": request.url.path})
        return _error(
            500, "internal_error", "Unexpected error. The request id identifies it in the logs."
        )

    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def starlette_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        headers = dict(exc.headers) if exc.headers else None
        return await http_error(request, HTTPException(exc.status_code, exc.detail, headers))

    app.include_router(health_router)
    app.include_router(public_router)
    app.include_router(admin_router)
    app.include_router(share_router)
    return app
