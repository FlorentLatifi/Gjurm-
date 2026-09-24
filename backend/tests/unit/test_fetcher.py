from __future__ import annotations

import socket

import httpx
import pytest

from gjurme.ingestion.fetcher import UnsafeHostError, assert_public_host
from tests.conftest import feed_server, fixture_bytes

FEED = "https://portali.example.com/feed/"


def test_ok_fetch_returns_body_and_validators(make_fetcher) -> None:
    handler = feed_server(
        {
            FEED: (
                200,
                fixture_bytes("wordpress_sq.xml"),
                {"etag": '"v1"', "last-modified": "Wed, 24 Sep 2026"},
            )
        }
    )
    result = make_fetcher(handler).fetch(FEED)
    assert result.status == "ok"
    assert result.etag == '"v1"' and result.last_modified == "Wed, 24 Sep 2026"
    assert result.body and b"Kuvendi" in result.body


def test_conditional_get_sends_validators_and_handles_304(make_fetcher) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(304)

    result = make_fetcher(handler).fetch(FEED, etag='"v1"', last_modified="yesterday")
    assert result.status == "not_modified" and result.ok
    assert seen["if-none-match"] == '"v1"' and seen["if-modified-since"] == "yesterday"
    assert seen["user-agent"] == "GjurmeTest/1.0"


def test_timeout_is_reported_not_raised(make_fetcher) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    result = make_fetcher(handler).fetch(FEED)
    assert result.status == "timeout" and not result.ok


def test_connection_error_is_reported(make_fetcher) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert make_fetcher(handler).fetch(FEED).status == "network_error"


def test_http_error_status(make_fetcher) -> None:
    result = make_fetcher(feed_server({FEED: (503, b"down", {})})).fetch(FEED)
    assert result.status == "http_error" and result.http_status == 503


def test_declared_oversize_rejected(make_fetcher) -> None:
    handler = feed_server({FEED: (200, b"x" * 10, {"content-length": "999999999"})})
    assert make_fetcher(handler, max_bytes=1000).fetch(FEED).status == "too_large"


def test_streamed_oversize_rejected(make_fetcher) -> None:
    handler = feed_server({FEED: (200, b"x" * 5000, {})})
    assert make_fetcher(handler, max_bytes=1000).fetch(FEED).status == "too_large"


def test_redirect_followed(make_fetcher) -> None:
    new = "https://portali.example.com/rss.xml"
    handler = feed_server(
        {FEED: (301, b"", {"location": "/rss.xml"}), new: (200, fixture_bytes("atom.xml"), {})}
    )
    result = make_fetcher(handler).fetch(FEED)
    assert result.status == "ok" and result.final_url == new


def test_redirect_to_private_address_is_blocked(make_fetcher) -> None:
    handler = feed_server({FEED: (302, b"", {"location": "http://169.254.169.254/latest/"})})
    result = make_fetcher(handler).fetch(FEED)
    assert result.status == "invalid_url"
    assert "redirect rejected" in (result.error or "")


def test_redirect_loop_stops(make_fetcher) -> None:
    handler = feed_server({FEED: (302, b"", {"location": FEED})})
    result = make_fetcher(handler).fetch(FEED)
    assert result.status == "http_error" and "too many redirects" in (result.error or "")


def test_invalid_scheme(make_fetcher) -> None:
    assert make_fetcher(feed_server({})).fetch("file:///etc/passwd").status == "invalid_url"


def test_robots_disallow_respected(make_fetcher) -> None:
    handler = feed_server(
        {
            "https://portali.example.com/robots.txt": (
                200,
                b"User-agent: *\nDisallow: /feed/\n",
                {},
            ),
            FEED: (200, fixture_bytes("atom.xml"), {}),
        }
    )
    result = make_fetcher(handler, respect_robots=True).fetch(FEED)
    assert result.status == "robots_disallowed"


def test_robots_404_means_allowed(make_fetcher) -> None:
    handler = feed_server({FEED: (200, fixture_bytes("atom.xml"), {})})
    assert make_fetcher(handler, respect_robots=True).fetch(FEED).status == "ok"


def test_robots_5xx_means_disallow(make_fetcher) -> None:
    handler = feed_server(
        {
            "https://portali.example.com/robots.txt": (503, b"", {}),
            FEED: (200, fixture_bytes("atom.xml"), {}),
        }
    )
    result = make_fetcher(handler, respect_robots=True).fetch(FEED)
    assert result.status == "robots_disallowed" and "RFC 9309" in (result.error or "")


def test_robots_cached_per_origin(make_fetcher) -> None:
    calls: list[str] = []
    inner = feed_server({FEED: (200, fixture_bytes("atom.xml"), {})})

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return inner(request)

    fetcher = make_fetcher(handler, respect_robots=True)
    fetcher.fetch(FEED)
    fetcher.fetch(FEED)
    assert calls.count("/robots.txt") == 1


def test_dns_guard_rejects_private_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host, *_a, **_k):  # type: ignore[no-untyped-def]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeHostError):
        assert_public_host("evil.example.com")


def test_dns_guard_accepts_public_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host, *_a, **_k):  # type: ignore[no-untyped-def]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert_public_host("example.com")


def test_fetcher_uses_dns_guard(make_fetcher) -> None:
    def deny(host: str) -> None:
        raise UnsafeHostError(f"{host} is private")

    result = make_fetcher(feed_server({}), host_validator=deny).fetch(FEED)
    assert result.status == "invalid_url"
