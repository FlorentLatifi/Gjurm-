"""Data-quality checks — explicit, persisted, thresholded.

Each check measures one property of the last 24 hours (or of the current state) and returns
``pass`` / ``warn`` / ``fail`` with the observed value and threshold. Results are stored in
``ops.data_quality_results`` for every pipeline run, so quality can be tracked over time and
alerts can reference concrete numbers.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from gjurme.db.models import DataQualityResult


@dataclass(slots=True)
class CheckResult:
    name: str
    severity: str  # info | warning | critical
    status: str  # pass | warn | fail
    observed: float | None
    threshold: float | None
    details: dict[str, Any] = field(default_factory=dict)


def _rate(num: float, den: float) -> float:
    return round(num / den, 4) if den else 0.0


def _grade(value: float, warn: float, fail: float | None = None) -> str:
    if fail is not None and value > fail:
        return "fail"
    return "warn" if value > warn else "pass"


def check_rejection_rate(s: Session) -> CheckResult:
    row = s.execute(
        text("""
        SELECT count(*) FILTER (WHERE process_status = 'rejected') AS rejected,
               count(*) AS total
        FROM raw.feed_items WHERE processed_at >= now() - interval '24 hours'
    """)
    ).one()
    reasons: dict[str, int] = {
        r[0]: int(r[1])
        for r in s.execute(
            text("""
        SELECT split_part(rejection_reason, ':', 1), count(*)
        FROM raw.feed_items
        WHERE processed_at >= now() - interval '24 hours' AND process_status = 'rejected'
        GROUP BY 1 ORDER BY 2 DESC LIMIT 10
    """)
        ).all()
    }
    rate = _rate(row.rejected, row.total)
    return CheckResult(
        "raw_rejection_rate_24h",
        "warning",
        _grade(rate, 0.10, 0.30),
        rate,
        0.10,
        {"rejected": row.rejected, "processed": row.total, "reasons": reasons},
    )


def check_duplicate_rate(s: Session) -> CheckResult:
    row = s.execute(
        text("""
        SELECT count(*) FILTER (WHERE process_status = 'duplicate') AS dups, count(*) AS total
        FROM raw.feed_items WHERE processed_at >= now() - interval '24 hours'
    """)
    ).one()
    rate = _rate(row.dups, row.total)
    # Informational: high duplicate rates are normal (overlapping feeds); ~100% means a feed that
    # only ever re-serves known items.
    return CheckResult(
        "duplicate_rate_24h",
        "info",
        _grade(rate, 0.95),
        rate,
        0.95,
        {"duplicates": row.dups, "processed": row.total},
    )


def check_estimated_dates(s: Session) -> CheckResult:
    row = s.execute(
        text("""
        SELECT count(*) FILTER (WHERE published_at_estimated) AS est, count(*) AS total
        FROM core.articles WHERE ingested_at >= now() - interval '24 hours'
    """)
    ).one()
    rate = _rate(row.est, row.total)
    return CheckResult(
        "estimated_publication_dates_24h",
        "warning",
        _grade(rate, 0.20),
        rate,
        0.20,
        {"estimated": row.est, "articles": row.total},
    )


def check_enrichment_backlog(s: Session) -> CheckResult:
    backlog = s.execute(
        text("""
        SELECT count(*) FROM core.articles
        WHERE enrichment_status IN ('pending', 'failed') AND NOT is_hidden
          AND ingested_at < now() - interval '6 hours'
    """)
    ).scalar_one()
    return CheckResult(
        "enrichment_backlog_6h",
        "warning",
        _grade(backlog, 200, 1000),
        float(backlog),
        200.0,
        {"articles_waiting_over_6h": backlog},
    )


def check_enrichment_failure_rate(s: Session) -> CheckResult:
    row = s.execute(
        text("""
        SELECT count(*) FILTER (WHERE status IN ('failed', 'invalid', 'refused')) AS failed,
               count(*) FILTER (WHERE status <> 'cached') AS total
        FROM core.enrichments WHERE created_at >= now() - interval '24 hours'
    """)
    ).one()
    rate = _rate(row.failed, row.total)
    return CheckResult(
        "enrichment_failure_rate_24h",
        "critical",
        _grade(rate, 0.10, 0.30),
        rate,
        0.10,
        {"failed": row.failed, "attempts": row.total},
    )


def check_enrichment_consistency(s: Session) -> CheckResult:
    bad = s.execute(
        text("""
        SELECT count(*) FROM core.articles
        WHERE enrichment_status = 'succeeded'
          AND (primary_topic_id IS NULL OR sentiment_label IS NULL OR sentiment_score IS NULL
               OR summary_en IS NULL)
    """)
    ).scalar_one()
    return CheckResult(
        "enrichment_consistency",
        "critical",
        "fail" if bad else "pass",
        float(bad),
        0.0,
        {"succeeded_without_fields": bad},
    )


def check_malformed_entities(s: Session) -> CheckResult:
    bad = s.execute(
        text("""
        SELECT count(*) FROM core.entities
        WHERE length(trim(name)) < 2 OR normalized_key = '' OR name ~ '[<>{}]'
    """)
    ).scalar_one()
    return CheckResult(
        "malformed_entities",
        "warning",
        "fail" if bad else "pass",
        float(bad),
        0.0,
        {"malformed": bad},
    )


def check_ungrounded_entities(s: Session) -> CheckResult:
    row = s.execute(
        text("""
        SELECT coalesce(sum(jsonb_array_length(quality_flags -> 'entities_ungrounded')), 0)
                   AS dropped,
               coalesce(sum(jsonb_array_length(output -> 'entities')), 0) AS kept
        FROM core.enrichments
        WHERE created_at >= now() - interval '24 hours' AND status = 'succeeded'
    """)
    ).one()
    total = int(row.dropped) + int(row.kept)
    rate = _rate(int(row.dropped), total)
    return CheckResult(
        "ungrounded_entity_rate_24h",
        "warning",
        _grade(rate, 0.15),
        rate,
        0.15,
        {"dropped": int(row.dropped), "kept": int(row.kept)},
    )


def check_source_freshness(s: Session) -> CheckResult:
    stale = [
        dict(r._mapping)
        for r in s.execute(
            text("""
            SELECT slug, last_success_at, consecutive_failures FROM core.sources
            WHERE is_active AND (last_success_at IS NULL
                                 OR last_success_at < now() - interval '6 hours')
            ORDER BY slug
        """)
        )
    ]
    active = s.execute(text("SELECT count(*) FROM core.sources WHERE is_active")).scalar_one()
    status = "fail" if active and len(stale) == active else ("warn" if stale else "pass")
    return CheckResult(
        "source_freshness_6h",
        "critical",
        status,
        float(len(stale)),
        0.0,
        {"stale_sources": stale, "active_sources": active},
    )


def check_volume_anomaly(s: Session) -> CheckResult:
    rows = (
        s.execute(
            text("""
        WITH days AS (
            SELECT generate_series(now() - interval '15 days', now() - interval '2 days',
                                   interval '1 day') AS start
        )
        SELECT (SELECT count(*) FROM core.articles
                WHERE ingested_at >= d.start AND ingested_at < d.start + interval '1 day') AS n
        FROM days d
    """)
        )
        .scalars()
        .all()
    )
    current = s.execute(
        text("SELECT count(*) FROM core.articles WHERE ingested_at >= now() - interval '24 hours'")
    ).scalar_one()
    baseline = [int(n) for n in rows]
    active_days = [n for n in baseline if n > 0]
    if len(active_days) < 7:
        return CheckResult(
            "article_volume_anomaly",
            "warning",
            "pass",
            float(current),
            None,
            {"reason": "insufficient history", "days_with_data": len(active_days)},
        )
    mean = sum(baseline) / len(baseline)
    std = math.sqrt(sum((n - mean) ** 2 for n in baseline) / len(baseline))
    z = (current - mean) / max(std, 1.0)
    status = "warn" if abs(z) > 3 else "pass"
    if current == 0 and mean >= 10:
        status = "fail"
    return CheckResult(
        "article_volume_anomaly",
        "warning",
        status,
        round(z, 2),
        3.0,
        {"last_24h": current, "baseline_mean": round(mean, 1), "baseline_std": round(std, 1)},
    )


def check_foreign_domains(s: Session) -> CheckResult:
    row = s.execute(
        text(r"""
        SELECT count(*) FILTER (
                   WHERE regexp_replace(substring(a.url from '^https?://([^/:]+)'), '^www\.', '')
                     NOT LIKE '%' || regexp_replace(
                         substring(src.homepage_url from '^https?://([^/:]+)'), '^www\.', '')
               ) AS foreign_links,
               count(*) AS total
        FROM core.articles a JOIN core.sources src ON src.id = a.source_id
        WHERE a.ingested_at >= now() - interval '24 hours'
    """)
    ).one()
    rate = _rate(row.foreign_links, row.total)
    return CheckResult(
        "foreign_domain_links_24h",
        "info",
        _grade(rate, 0.05),
        rate,
        0.05,
        {"foreign": row.foreign_links, "articles": row.total},
    )


def check_low_confidence(s: Session) -> CheckResult:
    row = s.execute(
        text("""
        SELECT count(*) FILTER (WHERE enrichment_confidence < 0.5) AS low, count(*) AS total
        FROM core.articles
        WHERE enriched_at >= now() - interval '24 hours' AND enrichment_status = 'succeeded'
    """)
    ).one()
    rate = _rate(row.low, row.total)
    return CheckResult(
        "low_confidence_rate_24h",
        "info",
        _grade(rate, 0.30),
        rate,
        0.30,
        {"low_confidence": row.low, "enriched": row.total},
    )


CHECKS: tuple[Callable[[Session], CheckResult], ...] = (
    check_rejection_rate,
    check_duplicate_rate,
    check_estimated_dates,
    check_enrichment_backlog,
    check_enrichment_failure_rate,
    check_enrichment_consistency,
    check_malformed_entities,
    check_ungrounded_entities,
    check_source_freshness,
    check_volume_anomaly,
    check_foreign_domains,
    check_low_confidence,
)


def run_checks(session: Session, run_id: int | None) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check in CHECKS:
        try:
            with session.begin_nested():
                result = check(session)
        except Exception as exc:  # a broken check is itself a quality finding
            result = CheckResult(
                check.__name__.removeprefix("check_"),
                "warning",
                "fail",
                None,
                None,
                {"error": f"{type(exc).__name__}: {exc}"[:500]},
            )
        results.append(result)
        session.add(
            DataQualityResult(
                run_id=run_id,
                check_name=result.name,
                severity=result.severity,
                status=result.status,
                observed=result.observed,
                threshold=result.threshold,
                details=result.details,
            )
        )
    session.flush()
    return results


def summarize(results: list[CheckResult]) -> dict[str, Any]:
    return {
        "passed": sum(r.status == "pass" for r in results),
        "warnings": [r.name for r in results if r.status == "warn"],
        "failures": [r.name for r in results if r.status == "fail"],
    }
