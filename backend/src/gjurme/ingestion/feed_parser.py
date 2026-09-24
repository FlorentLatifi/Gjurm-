"""Feed parsing (RSS 0.9x/1.0/2.0, Atom) and HTML feed autodiscovery.

``feedparser`` is deliberately lenient: malformed XML (``bozo``) often still yields entries.
We keep such entries but record that the feed was malformed, so data quality can be tracked
per source instead of dropping everything on the first broken byte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import struct_time
from typing import Any
from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup

from gjurme.ingestion.normalize import parse_feed_datetime

FEED_MIME_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/feed+json",
    "application/rdf+xml",
    "application/xml",
    "text/xml",
)
_MAX_TAGS = 20
_MAX_FIELD = 20_000


@dataclass(slots=True)
class ParsedFeed:
    entries: list[dict[str, Any]] = field(default_factory=list)
    malformed: bool = False
    malformed_reason: str | None = None
    title: str | None = None
    language: str | None = None
    is_feed: bool = True


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_FIELD:
        return value[:_MAX_FIELD]
    return value


def entry_to_payload(entry: Any) -> dict[str, Any]:
    """Project a feedparser entry onto a stable, JSON-serializable dict (the raw layer record)."""
    published = parse_feed_datetime(dict(entry))
    tags = [t.get("term") for t in entry.get("tags", []) or [] if t.get("term")][:_MAX_TAGS]
    content = entry.get("content") or []
    content_value = content[0].get("value") if content and isinstance(content[0], dict) else None
    payload: dict[str, Any] = {
        "title": entry.get("title"),
        "link": entry.get("link"),
        "id": entry.get("id") or entry.get("guid"),
        "summary": entry.get("summary") or entry.get("description"),
        # Full content (content:encoded) is NOT stored: we only keep what we need and are
        # comfortable holding. Its length is kept as a data-quality signal.
        "content_length": len(content_value) if isinstance(content_value, str) else None,
        "published": entry.get("published") or entry.get("updated"),
        "published_iso": published.isoformat() if published else None,
        "author": entry.get("author"),
        "tags": tags,
        "language": entry.get("language"),
    }
    return {k: _clip(v) for k, v in payload.items()}


def parse_feed(body: bytes, *, response_headers: dict[str, str] | None = None) -> ParsedFeed:
    parsed = feedparser.parse(body, response_headers=response_headers or {})
    feed_meta = parsed.get("feed", {}) or {}
    entries = [entry_to_payload(e) for e in parsed.get("entries", [])]
    bozo = bool(parsed.get("bozo"))
    reason = None
    if bozo:
        exc = parsed.get("bozo_exception")
        reason = f"{type(exc).__name__}: {exc}"[:500] if exc else "malformed feed"
    version = parsed.get("version") or ""
    is_feed = bool(version) or bool(entries)
    return ParsedFeed(
        entries=entries,
        malformed=bozo,
        malformed_reason=reason,
        title=feed_meta.get("title"),
        language=feed_meta.get("language"),
        is_feed=is_feed,
    )


def discover_feeds(html: bytes | str, base_url: str) -> list[dict[str, str]]:
    """Find ``<link rel="alternate" type="application/rss+xml">`` feeds and RSS-looking anchors."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, dict[str, str]] = {}
    for link in soup.find_all("link"):
        rel = " ".join(_attr_list(link, "rel")).lower()
        mime = _attr(link, "type").lower()
        href = _attr(link, "href")
        if href and "alternate" in rel and mime in FEED_MIME_TYPES:
            url = urljoin(base_url, href)
            found.setdefault(url, {"url": url, "title": _attr(link, "title"), "via": "link"})
    for anchor in soup.find_all("a"):
        href = _attr(anchor, "href")
        lowered = href.lower()
        if any(marker in lowered for marker in ("/rss", "/feed", ".xml", "/api/")) and (
            "rss" in lowered or "feed" in lowered or "api/" in lowered
        ):
            url = urljoin(base_url, href)
            text = anchor.get_text(" ", strip=True)[:120]
            found.setdefault(url, {"url": url, "title": text, "via": "anchor"})
    return list(found.values())


def _attr(tag: Any, name: str) -> str:
    value = tag.get(name)
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value) if value else ""


def _attr_list(tag: Any, name: str) -> list[str]:
    value = tag.get(name)
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)] if value else []


def struct_to_datetime(value: struct_time | None) -> datetime | None:
    return datetime(*value[:6], tzinfo=UTC) if value else None
