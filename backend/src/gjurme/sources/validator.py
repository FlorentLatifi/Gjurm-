"""Source validation & feed autodiscovery (``gjurme sources validate``).

Produces evidence rather than assumptions: for every registered source it fetches the declared
feed and reports format, item count, field coverage, timestamp range, duplicate GUIDs and whether
Albanian characters survive decoding. When the declared feed fails (or is not declared), it scans
the source's discovery pages for ``<link rel="alternate">`` feeds and validates each candidate.

Run it from a network with open egress — the GitHub Actions workflow
``.github/workflows/sources.yml`` does this weekly and publishes the report as an artifact.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from gjurme.ingestion.feed_parser import discover_feeds, parse_feed
from gjurme.ingestion.fetcher import FeedFetcher
from gjurme.ingestion.normalize import clean_text
from gjurme.sources.registry import SourceConfig

FIELDS = ("title", "link", "id", "published_iso", "summary", "author", "tags")
MAX_CANDIDATES = 6


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


@dataclass(slots=True)
class SourceReport:
    slug: str
    name: str
    enabled: bool
    declared_feed: str | None
    declared: FeedReport | None
    discovered: list[FeedReport] = field(default_factory=list)
    recommendation: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.declared and self.declared.ok)


def validate_feed(fetcher: FeedFetcher, url: str) -> FeedReport:
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
    report.ok = True
    report.status = "ok"
    return report


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
    if cfg.feed_url:
        report.declared = validate_feed(fetcher, cfg.feed_url)
    if report.ok:
        report.recommendation = "declared feed OK — mark verified"
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
        "| Source | Declared feed | Status | Items | Newest item | Title/link/date coverage "
        "| ë/ç seen | Recommendation |",
        "|---|---|---|---|---|---|---|---|",
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
        lines.append(
            f"| {r.name} | `{r.declared_feed or '—'}` | "
            f"{(d.status + (f' ({d.http_status})' if d.http_status else '')) if d else 'none'} | "
            f"{d.items if d else 0} | {d.newest if d and d.newest else '—'} | {cov} | "
            f"{'yes' if d and d.albanian_chars_seen else 'no'} | {r.recommendation} |"
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
