"""Source validation & feed autodiscovery (``gjurme sources validate``).

Produces evidence rather than assumptions: for every registered source it fetches the declared
feed and reports format, item count, field coverage, timestamp range, duplicate GUIDs and whether
Albanian characters survive decoding. When the declared feed fails (or is not declared), it scans
the source's discovery pages for ``<link rel="alternate">`` feeds and validates each candidate;
when none of those works either, it tries the paths where publishing systems usually put a feed.
For a working feed it also reports whether the feed has a next page (``?paged=2``): what
ingestion reads when every item of a fetch is new, so that a busy outlet's items are not missed.
A short feed without one (``SHORT_FEED_ITEMS`` items or fewer) gets its alternatives looked for:
the size parameters content systems commonly read (``?limit=50``), and the other feeds the site
links (section and category feeds), each with how many of its items the declared feed lacks.

Run it from a network with open egress — the GitHub Actions workflow
``.github/workflows/sources.yml`` does this weekly and publishes the report as an artifact.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from gjurme.ingestion.feed_parser import discover_feeds, parse_feed
from gjurme.ingestion.fetcher import FeedFetcher, next_page_url, with_query
from gjurme.ingestion.normalize import clean_text, item_key
from gjurme.sources.registry import SourceConfig

FIELDS = ("title", "link", "id", "published_iso", "summary", "author", "tags", "image")
MAX_CANDIDATES = 6
# WordPress, Drupal, Joomla and most news CMSs serve their feed at one of these paths.
WELL_KNOWN_FEED_PATHS = ("/feed/", "/rss", "/rss/", "/rss.xml", "/feed.xml", "/feed/rss")
# A feed listing this few items without a next page loses items at a busy outlet's peak.
SHORT_FEED_ITEMS = 10
# How content systems commonly let a list be longer (Joomla, Drupal views, custom CMSs).
SIZE_PARAMS = ("limit", "count", "items_per_page", "per_page")
LONGER_FEED_SIZE = 50
MAX_ALTERNATIVES = 12


@dataclass(slots=True)
class FeedReport:
    url: str
    ok: bool
    status: str
    http_status: int | None = None
    content_type: str | None = None
    bytes: int | None = None
    duration_ms: int = 0
    error: str | None = None
    feed_title: str | None = None
    feed_language: str | None = None
    items: int = 0
    malformed: bool = False
    malformed_reason: str | None = None
    field_coverage: dict[str, float] = field(default_factory=dict)
    newest: str | None = None
    oldest: str | None = None
    duplicate_ids: int = 0
    avg_summary_chars: float | None = None
    has_full_content: bool = False
    albanian_chars_seen: bool = False
    sample_titles: list[str] = field(default_factory=list)
    next_page: str | None = None  # the declared feed's page 2: "10 more items", "none (...)"
    not_in_declared: int | None = None  # an alternative: its items the declared feed lacks


@dataclass(slots=True)
class SourceReport:
    slug: str
    name: str
    enabled: bool
    declared_feed: str | None
    declared: FeedReport | None
    discovered: list[FeedReport] = field(default_factory=list)
    recommendation: str = ""
    # a short declared feed without a next page: longer variants and the site's other feeds
    alternatives: list[FeedReport] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.declared and self.declared.ok)


def validate_feed(fetcher: FeedFetcher, url: str, keys: set[str] | None = None) -> FeedReport:
    """Fetch and describe one feed; ``keys`` receives the identities of its items."""
    result = fetcher.fetch(url)
    report = FeedReport(
        url=url,
        ok=False,
        status=result.status,
        http_status=result.http_status,
        content_type=result.content_type,
        duration_ms=result.duration_ms,
        error=result.error,
        bytes=len(result.body) if result.body is not None else None,
    )
    if result.status != "ok" or result.body is None:
        return report
    parsed = parse_feed(
        result.body, response_headers={"content-type": result.content_type or "application/xml"}
    )
    report.feed_title, report.feed_language = parsed.title, parsed.language
    report.malformed, report.malformed_reason = parsed.malformed, parsed.malformed_reason
    report.items = len(parsed.entries)
    if not parsed.is_feed or not parsed.entries:
        report.status = "parse_error"
        report.error = parsed.malformed_reason or "no feed entries found"
        return report
    n = len(parsed.entries)
    report.field_coverage = {
        f: round(sum(1 for e in parsed.entries if e.get(f)) / n, 2) for f in FIELDS
    }
    dates = [d for d in (_iso(e) for e in parsed.entries) if d is not None]
    if dates:
        report.newest, report.oldest = max(dates).isoformat(), min(dates).isoformat()
    ids = Counter(e.get("id") for e in parsed.entries if e.get("id"))
    report.duplicate_ids = sum(c - 1 for c in ids.values() if c > 1)
    summaries = [len(clean_text(e.get("summary"))) for e in parsed.entries if e.get("summary")]
    report.avg_summary_chars = round(sum(summaries) / len(summaries), 1) if summaries else None
    report.has_full_content = any(e.get("content_length") for e in parsed.entries)
    text_blob = " ".join(clean_text(e.get("title")) for e in parsed.entries)
    report.albanian_chars_seen = any(ch in text_blob for ch in "ëçËÇ")
    report.sample_titles = [clean_text(e.get("title"))[:140] for e in parsed.entries[:3]]
    if keys is not None:
        keys.update(_key(e) for e in parsed.entries)
    report.ok = True
    report.status = "ok"
    return report


def _key(entry: dict[str, Any]) -> str:
    """An item's identity, as ingestion computes it."""
    return item_key(
        entry.get("id"),
        entry.get("link"),
        clean_text(entry.get("title")),
        entry.get("published_iso"),
    )


def probe_next_page(fetcher: FeedFetcher, feed_url: str, page_one: set[str]) -> str:
    """Whether the feed serves a next page that ingestion can read after an overflow."""
    result = fetcher.fetch(next_page_url(feed_url, 2))
    if result.status != "ok" or result.body is None:
        code = f" {result.http_status}" if result.http_status else ""
        return f"none ({result.status}{code})"
    parsed = parse_feed(
        result.body, response_headers={"content-type": result.content_type or "application/xml"}
    )
    if not parsed.is_feed or not parsed.entries:
        return "none (not a feed)"
    more = len({_key(e) for e in parsed.entries} - page_one)
    return f"{more} more items" if more else "none (page 1 again)"


def find_alternatives(
    fetcher: FeedFetcher, cfg: SourceConfig, declared: set[str]
) -> list[FeedReport]:
    """Feeds that could give more of a short feed's items: the declared feed with a size
    parameter, and the other feeds the source's discovery pages link. Only working feeds with
    items the declared feed lacks are kept."""
    assert cfg.feed_url is not None
    found: list[FeedReport] = []

    def keep(url: str) -> None:
        keys: set[str] = set()
        candidate = validate_feed(fetcher, url, keys)
        if candidate.ok and keys - declared:
            candidate.not_in_declared = len(keys - declared)
            found.append(candidate)

    for param in SIZE_PARAMS:
        keep(with_query(cfg.feed_url, param, str(LONGER_FEED_SIZE)))
    links: dict[str, None] = {}
    for page in cfg.discovery_urls or (cfg.homepage_url,):
        result = fetcher.fetch_page(page)
        if result.status == "ok" and result.body:
            for cand in discover_feeds(result.body, result.final_url or page):
                links.setdefault(cand["url"], None)
    for url in [u for u in links if u != cfg.feed_url][:MAX_ALTERNATIVES]:
        keep(url)
    return found


def _iso(entry: dict[str, Any]) -> datetime | None:
    value = entry.get("published_iso")
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def validate_source(fetcher: FeedFetcher, cfg: SourceConfig) -> SourceReport:
    report = SourceReport(
        slug=cfg.slug, name=cfg.name, enabled=cfg.enabled, declared_feed=cfg.feed_url, declared=None
    )
    page_one: set[str] = set()
    if cfg.feed_url:
        report.declared = validate_feed(fetcher, cfg.feed_url, page_one)
    if report.ok and report.declared and cfg.feed_url:
        report.declared.next_page = probe_next_page(fetcher, cfg.feed_url, page_one)
        report.recommendation = "declared feed OK — mark verified"
        if report.declared.items <= SHORT_FEED_ITEMS and report.declared.next_page.startswith(
            "none"
        ):
            report.alternatives = find_alternatives(fetcher, cfg, page_one)
        return report
    candidates: dict[str, dict[str, str]] = {}
    for page in cfg.discovery_urls or (cfg.homepage_url,):
        page_result = fetcher.fetch_page(page)
        if page_result.status == "ok" and page_result.body:
            for cand in discover_feeds(page_result.body, page_result.final_url or page):
                candidates.setdefault(cand["url"], cand)
    for url in list(candidates)[:MAX_CANDIDATES]:
        if url == cfg.feed_url:
            continue
        report.discovered.append(validate_feed(fetcher, url))
    working = [d for d in report.discovered if d.ok]
    if not working:
        tried = {cfg.feed_url, *(d.url for d in report.discovered)}
        for path in WELL_KNOWN_FEED_PATHS:
            url = urljoin(cfg.homepage_url, path)
            if url not in tried:
                tried.add(url)
                result = validate_feed(fetcher, url)
                if result.ok:  # the misses are expected: only a hit is worth reporting
                    report.discovered.append(result)
                    break
        working = [d for d in report.discovered if d.ok]
    if working:
        best = max(working, key=lambda d: d.items)
        report.recommendation = f"replace feed_url with discovered feed {best.url}"
    else:
        report.recommendation = "no working feed found — keep disabled / investigate manually"
    return report


def to_markdown(reports: list[SourceReport], generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now(UTC)
    lines = [
        f"# Source validation report — {generated_at:%Y-%m-%d %H:%M} UTC",
        "",
        "| Source | Declared feed | Status | Items | Page 2 | Newest item "
        "| Title/link/date coverage | Photos | ë/ç seen | Recommendation |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        d = r.declared
        cov = (
            (
                f"{d.field_coverage.get('title', 0):.0%}/{d.field_coverage.get('link', 0):.0%}/"
                f"{d.field_coverage.get('published_iso', 0):.0%}"
            )
            if d and d.ok
            else "—"
        )
        photos = f"{d.field_coverage.get('image', 0):.0%}" if d and d.ok else "—"
        lines.append(
            f"| {r.name} | `{r.declared_feed or '—'}` | "
            f"{(d.status + (f' ({d.http_status})' if d.http_status else '')) if d else 'none'} | "
            f"{d.items if d else 0} | {d.next_page if d and d.next_page else '—'} | "
            f"{d.newest if d and d.newest else '—'} | {cov} | "
            f"{photos} | "
            f"{'yes' if d and d.albanian_chars_seen else 'no'} | {r.recommendation} |"
        )
    for r in reports:
        if r.alternatives:
            lines += [
                "",
                f"## Other feeds of {r.name} (its feed lists "
                f"{r.declared.items if r.declared else 0} items and has no page 2)",
                "",
            ]
            for d in r.alternatives:
                lines.append(
                    f"- `{d.url}` — {d.items} items, {d.not_in_declared} not in the declared "
                    f"feed, newest {d.newest or '—'}"
                )
    for r in reports:
        if r.discovered:
            lines += ["", f"## Discovered feeds for {r.name}", ""]
            for d in r.discovered:
                lines.append(
                    f"- `{d.url}` — {d.status}, {d.items} items"
                    + (f", error: {d.error}" if d.error else "")
                )
    return "\n".join(lines) + "\n"


def to_json(reports: list[SourceReport]) -> list[dict[str, Any]]:
    return [{**asdict(r), "ok": r.ok} for r in reports]
