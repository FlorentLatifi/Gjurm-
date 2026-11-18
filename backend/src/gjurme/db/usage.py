"""What the database holds and what the pipeline costs it: ``gjurme db-usage``.

Made for the free plans (ADR-027): Neon counts storage (1 GB) and the hours its compute is
awake (100 CU-hours a month; it suspends after 5 minutes without a query). The report reads
only catalog sizes and ``ops.pipeline_runs``, so it is cheap and changes nothing:

* the database's size, and every table's with its indexes (``pg_total_relation_size``), largest
  first, and the ten largest indexes, so retention can aim at what is actually large;
* the average and longest duration of each pipeline stage, from the runs' ``stats``;
* the time the pipeline alone keeps the compute awake: each run from its start to 5 minutes
  after its end, overlapping runs counted once. Neon's own figure minus this one is what
  readers' requests (cache misses) and everything else cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# Neon's free plan: a compute suspends after 5 minutes without a query, and is billed while it
# is awake at its size, 0.25 CU at the least (it can scale up under load).
SUSPEND_AFTER = timedelta(minutes=5)
MIN_CU = 0.25
STAGE_ORDER = ("ingest", "process", "enrich", "cluster", "quality")

_TABLES = text("""
    SELECT n.nspname || '.' || c.relname AS name,
           pg_total_relation_size(c.oid) AS total_bytes,
           pg_table_size(c.oid) AS table_bytes,
           pg_indexes_size(c.oid) AS index_bytes,
           coalesce(st.n_live_tup, greatest(c.reltuples, 0))::bigint AS rows_estimate
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_stat_all_tables st ON st.relid = c.oid
    WHERE c.relkind IN ('r', 'p', 'm')
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND n.nspname NOT LIKE 'pg_toast%'
    ORDER BY total_bytes DESC, name
""")

_INDEXES = text("""
    SELECT i.indexrelid::regclass::text AS name, i.relid::regclass::text AS "table",
           pg_relation_size(i.indexrelid) AS bytes
    FROM pg_stat_user_indexes i
    ORDER BY bytes DESC, name LIMIT :top
""")

_STAGES = text("""
    SELECT s.key AS stage, count(*) AS runs,
           round(avg((s.value ->> 'duration_ms')::numeric)) AS avg_ms,
           max((s.value ->> 'duration_ms')::numeric) AS max_ms
    FROM ops.pipeline_runs r CROSS JOIN LATERAL jsonb_each(r.stats) s
    WHERE r.started_at >= now() - make_interval(days => :days)
      AND r.status NOT IN ('running', 'skipped_locked')
      AND jsonb_typeof(s.value) = 'object' AND s.value ? 'duration_ms'
    GROUP BY s.key
""")

_RUNS = text("""
    SELECT started_at, finished_at, duration_ms FROM ops.pipeline_runs
    WHERE started_at >= now() - make_interval(days => :days)
      AND status NOT IN ('running', 'skipped_locked') AND finished_at IS NOT NULL
    ORDER BY started_at
""")


@dataclass(frozen=True, slots=True)
class Span:
    start: datetime
    end: datetime


def awake_seconds(runs: list[Span], tail: timedelta = SUSPEND_AFTER) -> float:
    """Seconds a scale-to-zero compute is awake for these runs: each from its start to ``tail``
    after its end, overlaps counted once (a run that starts while the compute is still awake
    from the one before adds only what goes beyond it)."""
    total = 0.0
    current: Span | None = None
    for run in sorted(runs, key=lambda r: r.start):
        end = run.end + tail
        if current is not None and run.start <= current.end:
            current = Span(current.start, max(current.end, end))
            continue
        if current is not None:
            total += (current.end - current.start).total_seconds()
        current = Span(run.start, end)
    if current is not None:
        total += (current.end - current.start).total_seconds()
    return total


def database_usage(session: Session, days: int = 7) -> dict[str, Any]:
    database_bytes = session.execute(
        text("SELECT pg_database_size(current_database())")
    ).scalar_one()
    tables = [dict(r._mapping) for r in session.execute(_TABLES)]
    indexes = [dict(r._mapping) for r in session.execute(_INDEXES, {"top": 10})]
    by_stage = {r.stage: r for r in session.execute(_STAGES, {"days": days})}
    order = [s for s in STAGE_ORDER if s in by_stage] + sorted(set(by_stage) - set(STAGE_ORDER))
    stages = [
        {
            "stage": name,
            "runs": int(by_stage[name].runs),
            "avg_seconds": round(float(by_stage[name].avg_ms) / 1000, 1),
            "max_seconds": round(float(by_stage[name].max_ms) / 1000, 1),
        }
        for name in order
    ]
    rows = session.execute(_RUNS, {"days": days}).all()
    runs: dict[str, Any] = {"days": days, "count": len(rows)}
    if rows:
        spans = [Span(r.started_at, r.finished_at) for r in rows]
        # The window the runs cover: the last `days` days, or less in a younger database.
        observed = max((rows[-1].finished_at - rows[0].started_at).total_seconds(), 3600.0)
        per_day = 86400 / min(observed, days * 86400)
        awake = awake_seconds(spans) * per_day
        runs |= {
            "per_day": round(len(rows) * per_day, 1),
            "avg_seconds": round(sum(r.duration_ms or 0 for r in rows) / len(rows) / 1000, 1),
            "max_seconds": round(max(r.duration_ms or 0 for r in rows) / 1000, 1),
            "awake_minutes_per_day": round(awake / 60),
            "cu_hours_per_30_days_at_min_size": round(awake / 3600 * 30 * MIN_CU, 1),
        }
    return {
        "database_bytes": int(database_bytes),
        "tables": tables,
        "largest_indexes": indexes,
        "stages": stages,
        "runs": runs,
    }


def _mb(value: int) -> str:
    return f"{value / 1024 / 1024:,.1f} MB"


def format_usage(usage: dict[str, Any], top: int = 25) -> str:
    """The report as plain text, for a terminal or a workflow log."""
    lines = [f"database: {_mb(usage['database_bytes'])}", ""]
    lines.append(f"{'table':<36}{'total':>12}{'data':>12}{'indexes':>12}{'rows':>12}")
    for t in usage["tables"][:top]:
        lines.append(
            f"{t['name']:<36}{_mb(t['total_bytes']):>12}{_mb(t['table_bytes']):>12}"
            f"{_mb(t['index_bytes']):>12}{t['rows_estimate']:>12,}"
        )
    rest = usage["tables"][top:]
    if rest:
        lines.append(f"{len(rest)} smaller tables: {_mb(sum(t['total_bytes'] for t in rest))}")
    if usage["largest_indexes"]:
        lines += ["", "largest indexes:"]
        for i in usage["largest_indexes"]:
            lines.append(f"  {i['name']:<44}{_mb(i['bytes']):>12}")
    runs = usage["runs"]
    lines += ["", f"pipeline runs, last {runs['days']} days: {runs['count']}"]
    if runs["count"]:
        lines.append(
            f"  {runs['per_day']} a day, {runs['avg_seconds']} s on average, "
            f"longest {runs['max_seconds']} s"
        )
        lines.append(
            f"  compute awake for the pipeline (run + 5 min): {runs['awake_minutes_per_day']} "
            f"min a day ≈ {runs['cu_hours_per_30_days_at_min_size']} CU-hours in 30 days at "
            f"{MIN_CU} CU"
        )
    if usage["stages"]:
        lines += ["", f"{'stage':<12}{'runs':>8}{'average':>12}{'longest':>12}"]
        for s in usage["stages"]:
            lines.append(
                f"{s['stage']:<12}{s['runs']:>8}{s['avg_seconds']:>10} s{s['max_seconds']:>10} s"
            )
    return "\n".join(lines) + "\n"
