"""Cleaning & normalization — pure functions, no I/O.

Text is normalized to Unicode NFC so that Albanian letters (``ë``, ``ç``) have a single
representation regardless of how the publisher encoded them; *keys* used for deduplication are
diacritic-folded (``ë``→``e``) so that "Kosovës" and "Kosoves" compare equal.
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from time import struct_time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

# --------------------------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------------------------
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_SPACES = re.compile(r"[\s   ]+")
_MOJIBAKE = re.compile(r"[ÃÅÄ][\u0080-¿]")
_WP_FOOTER = re.compile(r"\s*(The post .+? appeared first on .+?\.|Postimi .+? u shfaq .+?\.)\s*$")
_TRAILING_MORE = re.compile(r"\s*(\[(?:…|\.\.\.|&hellip;)\]|…|Read more|Lexo më shumë)\s*$", re.I)


def fix_mojibake(value: str) -> str:
    """Repair UTF-8 text that was mis-decoded as Latin-1 (e.g. ``KosovÃ«`` → ``Kosovë``).

    Only applied when the characteristic byte pattern is present *and* the repair round-trips;
    otherwise the input is returned unchanged.
    """
    if not _MOJIBAKE.search(value):
        return value
    try:
        repaired = value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    return repaired if len(_MOJIBAKE.findall(repaired)) < len(_MOJIBAKE.findall(value)) else value


def strip_html(value: str) -> str:
    if "<" not in value and "&" not in value:
        return value
    if "<" in value:
        value = BeautifulSoup(value, "html.parser").get_text(" ")
    return html.unescape(value)


def clean_text(value: Any) -> str:
    """HTML → plain text, NFC-normalized, mojibake-repaired, whitespace-collapsed."""
    if value is None:
        return ""
    text = str(value)
    text = strip_html(text)
    text = html.unescape(text)  # double-escaped entities (&amp;euml;) are common in feeds
    text = fix_mojibake(text)
    text = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH)
    text = _SPACES.sub(" ", text).strip()
    return text


def clean_excerpt(value: Any, max_chars: int) -> str:
    text = clean_text(value)
    text = _WP_FOOTER.sub("", text)
    text = _TRAILING_MORE.sub("", text).strip()
    return truncate(text, max_chars)


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1]
    space = cut.rfind(" ")
    if space > max_chars * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"


def fold(value: str) -> str:
    """Case- and diacritic-insensitive form: ``Shqipëria`` → ``shqiperia``."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalize_key(value: str) -> str:
    """Dedup/search key: folded, punctuation removed, single spaces."""
    return _NON_ALNUM.sub(" ", fold(value)).strip()


def sha256_hex(*parts: str) -> str:
    h = hashlib.sha256()
    for i, part in enumerate(parts):
        if i:
            h.update(b"\x1f")
        h.update(part.encode("utf-8"))
    return h.hexdigest()


# --------------------------------------------------------------------------------------------
# URLs
# --------------------------------------------------------------------------------------------
class InvalidURLError(ValueError):
    pass


_TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "igshid",
        "ocid",
        "ref",
        "ref_src",
        "_ga",
        "_gl",
        "amp",
        "output",
        "share",
        "s_cid",
        "cmpid",
        "yclid",
    }
)


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k.startswith(("utm_", "pk_", "mtm_")) or k in _TRACKING_PARAMS


def validate_public_http_url(url: str) -> str:
    """Accept only absolute http(s) URLs without credentials and not pointing at IP literals in
    private ranges. Used for feed URLs (SSRF guard) and for outbound article links (XSS guard:
    no ``javascript:`` or ``data:`` URLs can reach the UI)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise InvalidURLError(f"unsupported scheme: {parts.scheme!r}")
    if not parts.hostname:
        raise InvalidURLError("missing host")
    if parts.username or parts.password:
        raise InvalidURLError("credentials in URL are not allowed")
    host = parts.hostname
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise InvalidURLError("local hostnames are not allowed") from None
    else:
        if not ip.is_global:
            raise InvalidURLError("non-public IP address")
    return url.strip()


def normalize_url(url: str, base: str | None = None) -> str:
    """Clean an article URL for storage/linking (keeps scheme and host as published)."""
    raw = (url or "").strip()
    if not raw:
        raise InvalidURLError("empty URL")
    if base:
        raw = urljoin(base, raw)
    validate_public_http_url(raw)
    parts = urlsplit(raw)
    try:
        host = (parts.hostname or "").lower().encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidURLError("invalid hostname") from exc
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
    ]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query), ""))


def canonical_url(url: str) -> str:
    """Identity form of a URL used for deduplication (L2).

    https-folded, ``www.`` stripped, tracking params removed, params sorted, trailing slash and
    AMP suffix removed. Never shown to users — only hashed.
    """
    parts = urlsplit(normalize_url(url))
    host = parts.netloc.removeprefix("www.")
    path = parts.path
    if path.endswith("/amp") or path.endswith("/amp/"):
        path = path[: path.rfind("/amp")]
    path = path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit(("https", host, path, query, ""))


def url_hash(url: str) -> str:
    return sha256_hex(canonical_url(url))


# --------------------------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------------------------
MIN_VALID_DATE = datetime(2000, 1, 1, tzinfo=UTC)
FUTURE_TOLERANCE = timedelta(minutes=10)


def _from_struct(value: struct_time) -> datetime:
    # feedparser's *_parsed values are already converted to UTC.
    return datetime(*value[:6], tzinfo=UTC)


def _from_string(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)  # RFC 822 / 2822 (RSS pubDate)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))  # ISO 8601 (Atom)
        except ValueError:
            return None
    if dt.tzinfo is None:
        # A feed that omits the offset: assume UTC and let the plausibility check catch errors.
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_feed_datetime(entry: dict[str, Any]) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if isinstance(value, struct_time):
            try:
                return _from_struct(value)
            except (ValueError, OverflowError):
                continue
    for key in ("published", "updated", "created", "pubDate", "dc_date"):
        value = entry.get(key)
        if isinstance(value, str):
            parsed = _from_string(value)
            if parsed is not None:
                return parsed
    return None


def resolve_published_at(
    parsed: datetime | None, first_seen_at: datetime
) -> tuple[datetime, bool, str | None]:
    """Decide the publication timestamp.

    Returns ``(published_at, estimated, issue)``. Missing, pre-2000 and future timestamps are
    replaced by the time we first saw the item (``estimated=True``) and the issue is reported
    for data-quality tracking instead of silently accepting a bad value.
    """
    if parsed is None:
        return first_seen_at, True, "missing_date"
    if parsed < MIN_VALID_DATE:
        return first_seen_at, True, "implausible_date"
    if parsed > first_seen_at + FUTURE_TOLERANCE:
        # Typical cause: local time (UTC+1/+2) published with a +0000 offset.
        return first_seen_at, True, "future_date"
    return parsed, False, None


# --------------------------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------------------------
def item_key(guid: str | None, link: str | None, title: str, published: str | None) -> str:
    """Stable per-source identifier of a feed entry (L1 dedup key)."""
    if guid and guid.strip():
        return sha256_hex("guid", guid.strip())
    if link:
        try:
            return sha256_hex("url", canonical_url(link))
        except InvalidURLError:
            pass
    return sha256_hex("title", normalize_key(title), published or "")
