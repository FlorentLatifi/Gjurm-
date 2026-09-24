"""Pipeline orchestration: ingest → process → enrich → quality → alerts.

One run = one row in ``ops.pipeline_runs``. Stages are independent and each is rerunnable on
its own (``gjurme ingest`` / ``process`` / ``enrich`` / ``quality``) because every stage reads its
work queue from the database rather than from the previous stage's memory.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from gjurme.alerts.engine import AlertDispatcher, evaluate_run
from gjurme.config import Settings
from gjurme.db.models import PipelineRun
from gjurme.enrichment.providers import LLMProvider
from gjurme.enrichment.service import build_provider, run_enrichment
from gjurme.ingestion.fetcher import FeedFetcher, build_http_client
from gjurme.ingestion.ingest import ingest_all
from gjurme.ingestion.processor import process_pending
from gjurme.logging_setup import run_id_var
from gjurme.pipeline.locking import PIPELINE_LOCK_KEY, advisory_lock
from gjurme.quality.checks import run_checks, summarize

log = logging.getLogger(__name__)

ALL_STAGES: tuple[str, ...] = ("ingest", "process", "enrich", "quality")


@dataclass(slots=True)
class RunResult:
    run_id: int | None
    status: str
    stats: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


def _mark_abandoned(session: Session) -> int:
    """Called while holding the pipeline lock: any other 'running' run is necessarily dead."""
    result = session.execute(
        update(PipelineRun)
        .where(PipelineRun.status == "running")
        .values(
            status="abandoned",
            finished_at=datetime.now(UTC),
            error="process died before finishing (detected by next run)",
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def run_pipeline(
    settings: Settings,
    session_factory: sessionmaker[Session],
    *,
    trigger: str = "cli",
    stages: Sequence[str] = ALL_STAGES,
    provider: LLMProvider | None = None,
    fetcher: FeedFetcher | None = None,
    only_sources: list[str] | None = None,
    dispatcher: AlertDispatcher | None = None,
) -> RunResult:
    unknown = set(stages) - set(ALL_STAGES)
    if unknown:
        raise ValueError(f"unknown stages: {sorted(unknown)}")
    engine = session_factory.kw["bind"]
    started = time.monotonic()

    with advisory_lock(engine, PIPELINE_LOCK_KEY) as acquired:
        if not acquired:
            with session_factory() as s, s.begin():
                run = PipelineRun(
                    trigger=trigger,
                    stages=list(stages),
                    status="skipped_locked",
                    finished_at=datetime.now(UTC),
                    duration_ms=0,
                    hostname=socket.gethostname(),
                    pid=os.getpid(),
                    error="another run holds the pipeline lock",
                )
                s.add(run)
            log.warning("pipeline already running — skipped", extra={"trigger": trigger})
            return RunResult(run.id, "skipped_locked")

        with session_factory() as s, s.begin():
            abandoned = _mark_abandoned(s)
            run = PipelineRun(
                trigger=trigger,
                stages=list(stages),
                status="running",
                hostname=socket.gethostname(),
                pid=os.getpid(),
            )
            s.add(run)
            s.flush()
            run_id = run.id
        token = run_id_var.set(run_id)
        stats: dict[str, Any] = {"abandoned_runs_closed": abandoned} if abandoned else {}
        stage_errors: dict[str, str] = {}
        log.info("pipeline run started", extra={"trigger": trigger, "stages": list(stages)})
        try:
            _run_stages(
                settings,
                session_factory,
                run_id,
                stages,
                stats,
                stage_errors,
                provider=provider,
                fetcher=fetcher,
                only_sources=only_sources,
            )
        finally:
            status = _overall_status(stats, stage_errors)
            if stage_errors:
                stats["stage_errors"] = stage_errors
                stats["error"] = "; ".join(f"{k}: {v}" for k, v in stage_errors.items())
            duration_ms = int((time.monotonic() - started) * 1000)
            _alert(settings, session_factory, status, stats, dispatcher)
            with session_factory() as s, s.begin():
                s.execute(
                    update(PipelineRun)
                    .where(PipelineRun.id == run_id)
                    .values(
                        status=status,
                        finished_at=datetime.now(UTC),
                        duration_ms=duration_ms,
                        stats=stats,
                        error=stats.get("error"),
                    )
                )
            log.info("pipeline run finished", extra={"status": status, "duration_ms": duration_ms})
            run_id_var.reset(token)
        return RunResult(run_id, status, stats, duration_ms)


def _run_stages(
    settings: Settings,
    session_factory: sessionmaker[Session],
    run_id: int,
    stages: Sequence[str],
    stats: dict[str, Any],
    stage_errors: dict[str, str],
    *,
    provider: LLMProvider | None,
    fetcher: FeedFetcher | None,
    only_sources: list[str] | None,
) -> None:
    for stage in ALL_STAGES:
        if stage not in stages:
            continue
        if stage_errors and stage in ("process", "enrich"):
            # Upstream stage crashed (e.g. database unavailable): don't pile on.
            stats[stage] = {"skipped": "upstream stage failed"}
            continue
        t0 = time.monotonic()
        try:
            stats[stage] = _run_stage(
                stage,
                settings,
                session_factory,
                run_id,
                provider=provider,
                fetcher=fetcher,
                only_sources=only_sources,
            )
        except Exception as exc:
            log.exception("stage failed", extra={"stage": stage})
            stage_errors[stage] = f"{type(exc).__name__}: {exc}"[:500]
            stats[stage] = {"error": stage_errors[stage]}
        stats[stage]["duration_ms"] = int((time.monotonic() - t0) * 1000)


def _run_stage(
    stage: str,
    settings: Settings,
    session_factory: sessionmaker[Session],
    run_id: int,
    *,
    provider: LLMProvider | None,
    fetcher: FeedFetcher | None,
    only_sources: list[str] | None,
) -> dict[str, Any]:
    if stage == "ingest":
        own_client = fetcher is None
        if fetcher is None:
            fetcher = FeedFetcher(
                client=build_http_client(settings.http_timeout_seconds),
                user_agent=settings.http_user_agent,
                max_bytes=settings.http_max_bytes,
                respect_robots=settings.respect_robots_txt,
            )
        try:
            return ingest_all(
                session_factory, fetcher, settings, run_id=run_id, only_slugs=only_sources
            ).as_dict()
        finally:
            if own_client:
                fetcher.client.close()
    if stage == "process":
        with session_factory() as s:
            return process_pending(s, settings).as_dict()
    if stage == "enrich":
        llm = provider or build_provider(settings)
        return run_enrichment(session_factory, settings, llm, run_id=run_id).as_dict()
    if stage == "quality":
        with session_factory() as s, s.begin():
            results = run_checks(s, run_id)
        return {
            **summarize(results),
            "results": [
                {
                    "name": r.name,
                    "status": r.status,
                    "observed": r.observed,
                    "threshold": r.threshold,
                    "details": r.details,
                }
                for r in results
            ],
        }
    raise ValueError(stage)


def _overall_status(stats: dict[str, Any], stage_errors: dict[str, str]) -> str:
    if stage_errors:
        return "failed"
    ingest = stats.get("ingest") or {}
    enrich = stats.get("enrich") or {}
    if ingest.get("sources_failed") or enrich.get("circuit_open") or enrich.get("fatal_error"):
        return "partial"
    return "succeeded"


def _alert(
    settings: Settings,
    session_factory: Callable[[], Session],
    status: str,
    stats: dict[str, Any],
    dispatcher: AlertDispatcher | None,
) -> None:
    try:
        alerts = evaluate_run(status, stats)
        if not alerts:
            return
        with session_factory() as s, s.begin():
            (dispatcher or AlertDispatcher(settings)).dispatch(s, alerts)
        stats["alerts"] = [a.key for a in alerts]
    except Exception:  # alerting must never mask the run's own outcome
        log.exception("alert evaluation failed")
