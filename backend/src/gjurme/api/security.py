"""Cross-cutting HTTP protections: rate limiting, response caching, security headers, admin auth.

All in-process and dependency-free on purpose: the API runs as a single container behind Caddy,
so a per-process token bucket and TTL cache are sufficient and have no moving parts. If the API is
ever scaled horizontally, both move to Redis (documented in docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import hmac
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status

from gjurme.config import Settings


# ------------------------------------------------------------------------------------------
# Rate limiting — token bucket per (client, bucket class)
# ------------------------------------------------------------------------------------------
@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(self, max_keys: int = 20_000) -> None:
        self._buckets: OrderedDict[tuple[str, str], _Bucket] = OrderedDict()
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def hit(
        self, client: str, bucket: str, per_minute: int, now: float | None = None
    ) -> tuple[bool, float]:
        """Consume one token. Returns (allowed, seconds_until_next_token)."""
        now = time.monotonic() if now is None else now
        rate = per_minute / 60.0
        key = (client, bucket)
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(tokens=float(per_minute), updated=now)
                self._buckets[key] = b
                if len(self._buckets) > self._max_keys:
                    self._buckets.popitem(last=False)  # evict least recently seen client
            else:
                self._buckets.move_to_end(key)
            b.tokens = min(float(per_minute), b.tokens + (now - b.updated) * rate)
            b.updated = now
            if b.tokens >= 1.0:
                b.tokens -= 1.0
                return True, 0.0
            return False, (1.0 - b.tokens) / rate


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def bucket_for(path: str) -> str:
    if path.startswith("/api/v1/admin"):
        return "admin"
    if path.startswith("/api/v1/articles") or path.startswith("/api/v1/entities"):
        return "search"
    return "default"


# ------------------------------------------------------------------------------------------
# TTL cache for expensive, read-only analytics responses
# ------------------------------------------------------------------------------------------
class Overloaded(Exception):  # noqa: N818 - an HTTP condition (503), not a programming error
    """Too many responses are being computed at once: answer 503 instead of queueing for the
    database pool, which would hold every request (cheap ones too) for the pool timeout."""


@dataclass(slots=True)
class _Flight:
    """One computation in progress; requests for the same key wait for it."""

    done: threading.Event
    value: Any = None
    error: BaseException | None = None


class TTLCache:
    """In-process TTL cache with single-flight and a bound on concurrent computations.

    A cache miss computes the response with database work. Concurrent requests for the same key
    share one computation, and at most ``max_computations`` run at once: past that, a request
    waits ``wait_seconds`` for a slot and then gets ``Overloaded`` (503).
    """

    def __init__(
        self,
        ttl_seconds: float,
        max_items: int = 512,
        *,
        max_computations: int = 6,
        wait_seconds: float = 2.0,
        flight_timeout: float = 30.0,
    ) -> None:
        self.ttl = ttl_seconds
        self.max_items = max_items
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._flights: dict[str, _Flight] = {}
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max_computations)
        self._wait = wait_seconds
        self._flight_timeout = flight_timeout
        self.hits = 0
        self.misses = 0

    def get_or_set(self, key: str, factory: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key) if self.ttl > 0 else None
            if entry and entry[0] > now:
                self._data.move_to_end(key)
                self.hits += 1
                return entry[1]
            self.misses += 1
            flight = self._flights.get(key)
            leader = flight is None
            if flight is None:
                flight = self._flights[key] = _Flight(threading.Event())
        if not leader:
            if not flight.done.wait(self._flight_timeout):
                raise Overloaded
            if flight.error is not None:
                raise flight.error
            return flight.value
        try:
            if not self._slots.acquire(timeout=self._wait):
                raise Overloaded
            try:
                flight.value = factory()
            finally:
                self._slots.release()
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._flights.pop(key, None)
                if flight.error is None and self.ttl > 0:
                    self._data[key] = (time.monotonic() + self.ttl, flight.value)
                    self._data.move_to_end(key)
                    while len(self._data) > self.max_items:
                        self._data.popitem(last=False)
            flight.done.set()
        return flight.value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


# ------------------------------------------------------------------------------------------
# Headers
# ------------------------------------------------------------------------------------------
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
DOCS_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: "
    "https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), interest-cohort=()",
    "Cross-Origin-Resource-Policy": "same-site",
}


# ------------------------------------------------------------------------------------------
# Admin authentication
# ------------------------------------------------------------------------------------------
def require_admin(request: Request) -> str:
    settings: Settings = request.app.state.settings
    expected = settings.admin_api_token.get_secret_value() if settings.admin_api_token else ""
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "admin API disabled (ADMIN_API_TOKEN not configured)",
        )
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or missing admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return "admin"
