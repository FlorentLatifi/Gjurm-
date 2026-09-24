"""Polite, defensive HTTP fetching of RSS/Atom feeds.

Guarantees:

* never raises for network/HTTP problems — every outcome is a ``FetchResult`` with a status;
* hard timeout and hard response-size cap (a hostile or broken server cannot exhaust memory);
* conditional GET (``ETag`` / ``Last-Modified``) so unchanged feeds cost one 304;
* ``robots.txt`` honoured for the feed path (RFC 9309 semantics);
* SSRF guard: the initial URL and every redirect target must resolve to public IP addresses
  (feeds cannot redirect the fetcher into the private Docker network).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from gjurme.ingestion.normalize import InvalidURLError, validate_public_http_url

log = logging.getLogger(__name__)

MAX_REDIRECTS = 5
ACCEPT = (
    "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"
)


class UnsafeHostError(InvalidURLError):
    pass


def assert_public_host(host: str) -> None:
    """Resolve ``host`` and reject it if any address is not globally routable."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeHostError(f"cannot resolve {host}: {exc}") from exc
    for info in infos:
        address = info[4][0]
        if not ipaddress.ip_address(address).is_global:
            raise UnsafeHostError(f"{host} resolves to non-public address {address}")


@dataclass(slots=True)
class FetchResult:
    url: str
    status: str
    http_status: int | None = None
    body: bytes | None = None
    etag: str | None = None
    last_modified: str | None = None
    final_url: str | None = None
    duration_ms: int = 0
    error: str | None = None
    content_type: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "not_modified")


@dataclass
class FeedFetcher:
    client: httpx.Client
    user_agent: str
    max_bytes: int = 5_000_000
    respect_robots: bool = True
    host_validator: Callable[[str], None] = assert_public_host
    _robots_cache: dict[str, RobotFileParser | None] = field(default_factory=dict)

    # ---------------------------------------------------------------------------------------
    def fetch(
        self, url: str, etag: str | None = None, last_modified: str | None = None
    ) -> FetchResult:
        started = time.monotonic()
        result = self._fetch(url, etag, last_modified)
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result

    def fetch_page(self, url: str) -> FetchResult:
        """Plain GET used by feed autodiscovery (HTML pages)."""
        return self.fetch(url)

    # ---------------------------------------------------------------------------------------
    def _fetch(self, url: str, etag: str | None, last_modified: str | None) -> FetchResult:
        try:
            self._check_url(url)
        except InvalidURLError as exc:
            return FetchResult(url=url, status="invalid_url", error=str(exc))

        if self.respect_robots:
            verdict = self._robots_allows(url)
            if verdict is not None:
                return FetchResult(url=url, status="robots_disallowed", error=verdict)

        headers = {"User-Agent": self.user_agent, "Accept": ACCEPT}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        current = url
        try:
            for _ in range(MAX_REDIRECTS + 1):
                with self.client.stream("GET", current, headers=headers) as resp:
                    # NB: httpx's ``is_redirect`` is true for *every* 3xx (incl. 304 Not
                    # Modified); only responses with a Location header are redirects.
                    if resp.has_redirect_location:
                        location = resp.headers.get("location")
                        if not location:  # pragma: no cover - guarded by has_redirect_location
                            return FetchResult(
                                url=url,
                                status="http_error",
                                http_status=resp.status_code,
                                error="redirect without Location header",
                            )
                        current = urljoin(current, location)
                        self._check_url(current)
                        continue
                    return self._read_response(url, current, resp)
            return FetchResult(url=url, status="http_error", error="too many redirects")
        except InvalidURLError as exc:
            return FetchResult(url=url, status="invalid_url", error=f"redirect rejected: {exc}")
        except httpx.TimeoutException as exc:
            return FetchResult(url=url, status="timeout", error=type(exc).__name__)
        except httpx.HTTPError as exc:
            return FetchResult(
                url=url, status="network_error", error=f"{type(exc).__name__}: {exc}"
            )

    def _read_response(self, url: str, final_url: str, resp: httpx.Response) -> FetchResult:
        base = {
            "url": url,
            "final_url": final_url,
            "http_status": resp.status_code,
            "etag": resp.headers.get("etag"),
            "last_modified": resp.headers.get("last-modified"),
            "content_type": resp.headers.get("content-type"),
        }
        if resp.status_code == 304:
            return FetchResult(status="not_modified", **base)
        if resp.status_code != 200:
            return FetchResult(status="http_error", error=f"HTTP {resp.status_code}", **base)
        declared = resp.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            return FetchResult(status="too_large", error=f"content-length {declared}", **base)
        chunks: list[bytes] = []
        size = 0
        for chunk in resp.iter_bytes():
            size += len(chunk)
            if size > self.max_bytes:
                return FetchResult(
                    status="too_large", error=f"body exceeds {self.max_bytes} bytes", **base
                )
            chunks.append(chunk)
        return FetchResult(status="ok", body=b"".join(chunks), **base)

    # ---------------------------------------------------------------------------------------
    def _check_url(self, url: str) -> None:
        validate_public_http_url(url)
        host = urlsplit(url).hostname or ""
        self.host_validator(host)

    def _robots_allows(self, url: str) -> str | None:
        """Return ``None`` if allowed, otherwise the reason it is not."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots_cache:
            self._robots_cache[origin] = self._load_robots(origin)
        parser = self._robots_cache[origin]
        if parser is None:
            return "robots.txt unavailable (server error) — treated as disallow per RFC 9309"
        if parser.can_fetch(self.user_agent, url):
            return None
        return "disallowed by robots.txt"

    def _load_robots(self, origin: str) -> RobotFileParser | None:
        parser = RobotFileParser()
        current = f"{origin}/robots.txt"
        try:
            for _ in range(MAX_REDIRECTS + 1):
                resp = self.client.get(current, headers={"User-Agent": self.user_agent})
                if resp.has_redirect_location:
                    current = urljoin(current, resp.headers["location"])
                    self._check_url(current)
                    continue
                break
            else:
                resp = None
        except (httpx.HTTPError, InvalidURLError) as exc:
            # Unreachable robots.txt: allow (RFC 9309 treats only 5xx responses as disallow).
            log.warning("robots.txt fetch failed", extra={"origin": origin, "error": str(exc)})
            parser.parse([])
            return parser
        if resp is None or 400 <= resp.status_code < 500:
            parser.parse([])  # 4xx / redirect loop: no usable robots.txt, no restrictions
            return parser
        if resp.status_code >= 500:
            return None
        body = resp.content[: 512 * 1024].decode("utf-8", errors="replace")
        parser.parse(body.splitlines())
        return parser


def build_http_client(timeout_seconds: float) -> httpx.Client:
    timeout = httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds))
    return httpx.Client(timeout=timeout, follow_redirects=False, http2=False)
