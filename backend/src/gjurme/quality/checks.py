"""Data-quality checks — explicit, persisted, thresholded.

Each check measures one property of the last 24 hours (or of the current state) and returns
``pass`` / ``warn`` / ``fail`` with the observed value and threshold. Results are stored in
``ops.data_quality_results`` for every pipeline run, so quality can be tracked over time and
alerts can reference concrete numbers.

A check warns only about something to act on: an expected limit (a free model's daily quota,
an analysis queued again on purpose, a feed that is all new because nothing fetched it for
hours) is recorded in its details, not raised. A check that warns says what and where in its
``summary`` (the run's log and the alert carry it).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from gjurme.config import get_settings
from gjurme.db.models import DataQualityResult


@dataclass(slots=True)
class CheckResult:
    name: str
    severity: str  # info | warning | critical
    status: str  # pass | warn | fail
    observed: float | None
    threshold: float | None
    details: dict[str, Any] = field(default_factory=dict)
    summary: str = ""  # what to look at, in one line, when the check does not pass


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
    """Articles still without any analysis 6 h after arriving: pending, or failed with attempts
    left (failures that used up their attempts are not waiting for anything).

    An article that has an analysis and is queued for a better one is not backlog: the keyword
    rules' results put back for a model on purpose (``enrich-requeue --provider fake``, the
    workflow's *reanalyse*), or an article whose title changed. Readers see its analysis
    meanwhile, and with a free model's daily quota thousands of them wait for days by design.
    They are counted apart, in ``details.awaiting_better_analysis``."""
    row = s.execute(
        text("""
        SELECT count(*) FILTER (WHERE NOT analysed) AS waiting,
               count(*) FILTER (WHERE analysed) AS requeued
        FROM (SELECT EXISTS (SELECT 1 FROM core.enrichments e
                             WHERE e.article_id = a.id AND e.is_current) AS analysed
              FROM core.articles a
              WHERE (a.enrichment_status = 'pending'
                     OR (a.enrichment_status = 'failed'
                         AND a.enrichment_attempts < :max_attempts))
                AND NOT a.is_hidden AND a.ingested_at < now() - interval '6 hours') q
    """),
        {"max_attempts": get_settings().enrich_max_attempts},
    ).one()
    waiting, requeued = int(row.waiting), int(row.requeued)
    summary = f"{waiting} articles have no analysis 6 h after arriving"
    if requeued:
        summary += f" ({requeued} more keep theirs while queued for a better one: not counted)"
    return CheckResult(
        "enrichment_backlog_6h",
        "warning",
        _grade(waiting, 200, 1000),
        float(waiting),
        200.0,
        {"articles_waiting_over_6h": waiting, "awaiting_better_analysis": requeued},
        summary,
    )


FAILURE_RATE_MIN_CALLS = 20


def check_enrichment_failure_rate(s: Session) -> CheckResult:
    """Model calls that failed (an error, an unusable or a declined answer), of the calls a
    model answered in 24 hours. Left out:

    - a used-up quota (a 429 after the retries): on a free tier it happens every day and the
      fallback model or the rules take over; it is in ``details.rate_limited``;
    - the keyword rules (provider ``fake``): they cannot fail, and counted as successes they
      hid a model that failed every other call.

    Below FAILURE_RATE_MIN_CALLS answered calls the rate is only recorded: three calls before a
    quota ran out make no rate."""
    rows = s.execute(
        text("""
        SELECT model,
               CASE WHEN status = 'failed' THEN split_part(error, ':', 1) ELSE status END
                   AS outcome,
               count(*) AS n
        FROM core.enrichments
        WHERE created_at >= now() - interval '24 hours' AND provider <> 'fake'
          AND status <> 'cached'
        GROUP BY 1, 2
    """)
    ).all()
    failed_by: dict[str, int] = {}
    calls_by: dict[str, int] = {}
    rate_limited = 0
    for r in rows:
        if r.outcome == "rate_limited":
            rate_limited += int(r.n)
            continue
        calls_by[r.model] = calls_by.get(r.model, 0) + int(r.n)
        if r.outcome != "succeeded":
            key = f"{r.model}: {r.outcome}"
            failed_by[key] = failed_by.get(key, 0) + int(r.n)
    failed, total = sum(failed_by.values()), sum(calls_by.values())
    rate = _rate(failed, total)
    by_count = sorted(failed_by.items(), key=lambda kv: -kv[1])
    details: dict[str, Any] = {
        "failed": failed,
        "attempts": total,
        "rate_limited": rate_limited,
        "failed_by": dict(by_count),
        "calls_by_model": calls_by,
    }
    if total < FAILURE_RATE_MIN_CALLS:
        details["reason"] = f"fewer than {FAILURE_RATE_MIN_CALLS} model calls answered"
        return CheckResult("enrichment_failure_rate_24h", "info", "pass", rate, None, details)
    worst = ", ".join(f"{kind} ×{n}" for kind, n in by_count[:3])
    return CheckResult(
        "enrichment_failure_rate_24h",
        "critical",
        _grade(rate, 0.10, 0.30),
        rate,
        0.10,
        details,
        f"{failed} of {total} model calls failed ({worst}); used-up quotas not counted"
        if failed
        else "",
    )


RULE_BASED_WARN, RULE_BASED_FAIL = 0.5, 0.9
RULE_BASED_MIN_ARTICLES = 20


def check_rule_based_share(s: Session) -> CheckResult:
    """How much of the last 24 hours the keyword rules analysed although a model is configured
    (the rules take what no model analysed in time, ENRICH_RULES_AFTER_MINUTES). A high share
    means the models' quotas do not cover the volume, or a model stopped working: nothing else
    reports that, because every article still ends up analysed. Where the rules are the
    configured analysis (LLM_PROVIDER=fake, ADR-018) the share is only recorded."""
    row = s.execute(
        text("""
        SELECT count(*) FILTER (WHERE e.provider = 'fake') AS rules, count(*) AS total
        FROM core.articles a
        JOIN core.enrichments e ON e.article_id = a.id AND e.is_current
        WHERE a.enriched_at >= now() - interval '24 hours' AND a.enrichment_status = 'succeeded'
    """)
    ).one()
    share = _rate(row.rules, row.total)
    details = {"rule_based": row.rules, "analysed": row.total}
    if get_settings().llm_provider == "fake" or row.total < RULE_BASED_MIN_ARTICLES:
        return CheckResult("rule_based_share_24h", "info", "pass", share, None, details)
    return CheckResult(
        "rule_based_share_24h",
        "warning",
        _grade(share, RULE_BASED_WARN, RULE_BASED_FAIL),
        share,
        RULE_BASED_WARN,
        details,
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


def check_story_backlog(s: Session) -> CheckResult:
    """Articles the CLUSTER stage should have grouped into a story by now (an article waiting
    for its analysis is clustered after STORY_ENRICHMENT_WAIT_MINUTES at the latest)."""
    backlog = s.execute(
        text("""
        SELECT count(*) FROM core.articles
        WHERE story_id IS NULL AND NOT is_hidden AND ingested_at < now() - interval '2 hours'
          AND (enrichment_status IN ('succeeded', 'skipped')
               OR ingested_at < now() - interval '2 hours' - make_interval(mins => :wait))
    """),
        {"wait": get_settings().story_enrichment_wait_minutes},
    ).scalar_one()
    return CheckResult(
        "story_backlog_2h",
        "warning",
        _grade(backlog, 50, 500),
        float(backlog),
        50.0,
        {"articles_without_story": backlog},
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
    """Sources this collects nothing from: active but without a successful fetch for 6 hours,
    or auto-disabled after failing in a row (probed again every 6 hours). Both need a decision:
    a new ``feed_url`` in sources.yaml, or ``enabled: false`` there when the outlet blocks
    automated access, which also ends this warning (docs/OPERATIONS.md, "A source is
    failing")."""
    stale = [
        dict(r._mapping)
        for r in s.execute(
            text("""
            SELECT slug, to_char(last_success_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                   AS last_success_at, consecutive_failures FROM core.sources
            WHERE is_active AND (last_success_at IS NULL
                                 OR last_success_at < now() - interval '6 hours')
            ORDER BY slug
        """)
        )
    ]
    active = s.execute(text("SELECT count(*) FROM core.sources WHERE is_active")).scalar_one()
    # Disabled after failing in a row: no longer "stale", but no longer collected either.
    disabled = s.execute(
        text("""
            SELECT slug, disabled_reason,
                   to_char(last_success_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI"Z"')
                       AS last_success_at
            FROM core.sources
            WHERE NOT is_active AND disabled_reason LIKE 'auto-disabled%' ORDER BY slug
        """)
    ).all()
    auto_disabled = [r.slug for r in disabled]
    if not active or len(stale) == active:
        status = "fail"  # nothing is being collected
    else:
        status = "warn" if stale or auto_disabled else "pass"
    parts = [
        f"{r.slug} auto-disabled ({_last_error(r.disabled_reason)}; last success "
        f"{r.last_success_at or 'never'})"
        for r in disabled
    ] + [
        f"{x['slug']} "
        + (f"no success since {x['last_success_at']}" if x["last_success_at"] else "never fetched")
        + f" ({x['consecutive_failures']} failures in a row)"
        for x in stale
    ]
    return CheckResult(
        "source_freshness_6h",
        "critical",
        status,
        float(len(stale)),
        0.0,
        {
            "stale_sources": stale,
            "active_sources": active,
            "auto_disabled": auto_disabled,
            "disabled_reasons": {r.slug: r.disabled_reason for r in disabled},
        },
        "not collected: " + "; ".join(parts) if parts else "",
    )


def _last_error(disabled_reason: str | None) -> str:
    """The last error an auto-disable recorded, short: "http_error: HTTP 403"."""
    reason = disabled_reason or ""
    last = reason.partition("(last: ")[2].rstrip(")") or reason
    return last[:60]


def check_feed_overflow(s: Session) -> CheckResult:
    """Fetches in which every item was new although the source was fetched one run earlier:
    the outlet published more between two runs than its feed lists (feeds that show only their
    latest 10 items), so items were missed. A feed that is all new after a gap (the source was
    auto-disabled or failing, runs were missed) says nothing about the feed: the gap is reported
    elsewhere, and such fetches are only counted, in ``after_gap``.

    "One run earlier" is the source's previous successful fetch (or 304) at most 1.5 scheduler
    intervals before."""
    normal_gap = get_settings().scheduler_interval_minutes * 90  # seconds
    rows = [
        dict(r._mapping)
        for r in s.execute(
            text("""
            SELECT src.slug,
                   count(*) FILTER (WHERE prev.gap <= make_interval(secs => :normal_gap))
                       AS fetches,
                   count(*) FILTER (WHERE prev.gap > make_interval(secs => :normal_gap))
                       AS after_gap,
                   max(f.items_seen) AS items_listed
            FROM raw.feed_fetches f
            JOIN core.sources src ON src.id = f.source_id
            CROSS JOIN LATERAL (
                SELECT f.started_at - max(e.started_at) AS gap
                FROM raw.feed_fetches e
                WHERE e.source_id = f.source_id AND e.status IN ('ok', 'not_modified')
                  AND e.started_at < f.started_at
            ) prev
            WHERE f.started_at >= now() - interval '24 hours' AND f.status = 'ok'
              AND f.items_seen >= 5 AND f.items_new = f.items_seen
              AND prev.gap IS NOT NULL  -- not the source's first fetch
            GROUP BY src.slug ORDER BY src.slug
        """),
            {"normal_gap": normal_gap},
        )
    ]
    overflowing = [r for r in rows if r["fetches"]]
    return CheckResult(
        "feed_overflow_24h",
        "warning",
        "warn" if overflowing else "pass",
        float(len(overflowing)),
        0.0,
        {"sources": overflowing, "after_gap": [r for r in rows if not r["fetches"]]},
        "published more between two runs than the feed lists: "
        + ", ".join(f"{r['slug']} {r['fetches']}× (lists {r['items_listed']})" for r in overflowing)
        if overflowing
        else "",
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
    """How often a model was unsure of its analysis. The keyword rules (provider "fake") are
    unsure by design and say so on the page (ADR-018): counting them would raise this warning on
    every run of the free mode and hide a model that really is struggling."""
    row = s.execute(
        text("""
        SELECT count(*) FILTER (WHERE a.enrichment_confidence < 0.5 AND NOT rules.yes) AS low,
               count(*) FILTER (WHERE NOT rules.yes) AS total,
               count(*) FILTER (WHERE rules.yes) AS rule_based
        FROM core.articles a
        CROSS JOIN LATERAL (
            SELECT coalesce(bool_or(e.provider = 'fake'), false) AS yes
            FROM core.enrichments e WHERE e.article_id = a.id AND e.is_current
        ) rules
        WHERE a.enriched_at >= now() - interval '24 hours' AND a.enrichment_status = 'succeeded'
    """)
    ).one()
    rate = _rate(row.low, row.total)
    return CheckResult(
        "low_confidence_rate_24h",
        "info",
        _grade(rate, 0.30),
        rate,
        0.30,
        {"low_confidence": row.low, "enriched": row.total, "rule_based": row.rule_based},
    )


def check_database_size(s: Session) -> CheckResult:
    """The database against DB_SIZE_LIMIT_MB. Free hosted Postgres stops accepting writes at
    its cap (Neon's free plan: 1 GB), so this warns at 80 % and fails at 95 %, while there is
    time to shorten retention or upgrade. Without a limit it only records the size."""
    limit = get_settings().db_size_limit_mb
    size_mb = round(
        s.execute(text("SELECT pg_database_size(current_database())")).scalar_one() / 1_048_576,
        1,
    )
    if not limit:
        return CheckResult("database_size", "info", "pass", size_mb, None, {"limit_mb": None})
    used = size_mb / limit
    return CheckResult(
        "database_size",
        "critical",
        "fail" if used >= 0.95 else "warn" if used >= 0.8 else "pass",
        size_mb,
        round(limit * 0.8, 1),
        {"limit_mb": limit, "used": round(used, 3)},
    )


CHECKS: tuple[Callable[[Session], CheckResult], ...] = (
    check_rejection_rate,
    check_duplicate_rate,
    check_estimated_dates,
    check_enrichment_backlog,
    check_enrichment_failure_rate,
    check_rule_based_share,
    check_enrichment_consistency,
    check_story_backlog,
    check_malformed_entities,
    check_ungrounded_entities,
    check_source_freshness,
    check_feed_overflow,
    check_volume_anomaly,
    check_foreign_domains,
    check_low_confidence,
    check_database_size,
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
                details=_jsonable(result.details),
            )
        )
    session.flush()
    return results


def _jsonable(details: dict[str, Any]) -> dict[str, Any]:
    """Details go into a JSONB column: a value JSON has no type for (a timestamp a check took
    from SQL) becomes its text instead of failing the whole quality stage."""
    out: dict[str, Any] = json.loads(json.dumps(details, default=str))
    return out


def describe(result: CheckResult) -> str:
    """One line on what a check found, for the run's log and the alert."""
    return result.summary or f"observed {result.observed} (threshold {result.threshold})"


def summarize(results: list[CheckResult]) -> dict[str, Any]:
    return {
        "passed": sum(r.status == "pass" for r in results),
        "warnings": [r.name for r in results if r.status == "warn"],
        "failures": [r.name for r in results if r.status == "fail"],
    }
