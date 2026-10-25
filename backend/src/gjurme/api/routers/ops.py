"""Health, public status, metrics and the authenticated admin API."""

from __future__ import annotations

import ipaddress
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, text, update
from sqlalchemy.orm import Session

from gjurme import __version__
from gjurme.analytics import queries as q
from gjurme.api.deps import DB, AppSettings, local_today
from gjurme.api.schemas import Health, PublicStatus
from gjurme.api.security import client_ip, require_admin
from gjurme.config import Settings
from gjurme.db.models import AlertEvent, Article, PipelineRun, Source
from gjurme.enrichment.budget import spent_today
from gjurme.runtime_settings import (
    ENRICHMENT_PAUSE,
    RUN_REQUEST,
    SCHEDULER_HEARTBEAT,
    get_setting,
    put_setting,
)

log = logging.getLogger(__name__)
health_router = APIRouter(tags=["health"])
admin_router = APIRouter(
    prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


# ------------------------------------------------------------------------------------------
# Health
# ------------------------------------------------------------------------------------------
@health_router.get("/health", response_model=Health, summary="Liveness (process is up)")
def health() -> Any:
    return {"status": "ok", "version": __version__}


@health_router.get(
    "/health/ready",
    response_model=Health,
    responses={503: {"model": Health, "description": "Database unreachable"}},
    summary="Readiness (database reachable)",
)
def ready(request: Request, response: Response) -> Any:
    try:
        with request.app.state.session_factory() as s:
            version = s.execute(text("SELECT version_num FROM ops.alembic_version")).scalar()
        return {"status": "ok", "version": __version__, "database": True, "migrations": version}
    except Exception as exc:
        log.warning("readiness check failed", extra={"error": str(exc)[:200]})
        response.status_code = 503
        return {"status": "down", "version": __version__, "database": False}


@health_router.get(
    "/api/v1/status",
    response_model=PublicStatus,
    summary="Public pipeline freshness and source health",
)
def public_status(request: Request, response: Response, db: DB, settings: AppSettings) -> Any:
    # Every visitor's page asks for it (the status pill), so it is cached briefly, here and in
    # the browser; a pipeline run every 30 minutes makes 30 s of staleness irrelevant.
    response.headers["Cache-Control"] = f"public, max-age={STATUS_TTL_SECONDS}"
    return request.app.state.cache.get_or_set(
        "status", lambda: _public_status(db, settings), ttl=STATUS_TTL_SECONDS
    )


STATUS_TTL_SECONDS = 30


def _public_status(db: Session, settings: Settings) -> dict[str, Any]:
    last = db.execute(
        text("""
        SELECT started_at, status FROM ops.pipeline_runs
        WHERE status <> 'skipped_locked' ORDER BY started_at DESC LIMIT 1""")
    ).first()
    # a run in progress says nothing yet about health: judge by the last one that finished
    last_finished = db.execute(
        text("""
        SELECT status FROM ops.pipeline_runs
        WHERE status NOT IN ('skipped_locked', 'running') ORDER BY started_at DESC LIMIT 1""")
    ).scalar()
    last_success = db.execute(
        text("""
        SELECT max(finished_at) FROM ops.pipeline_runs
        WHERE status IN ('succeeded', 'partial')""")
    ).scalar()
    # Both counts use an index instead of scanning every article: an article ingested in the
    # last day was published within MAX_ITEM_AGE_DAYS of it (older items are rejected), and the
    # backlog is the enrichment queue's partial index.
    new_24h = db.execute(
        text("""
        SELECT count(*) FROM core.articles
        WHERE ingested_at > now() - interval '24 hours'
          AND published_at > now() - make_interval(days => :max_age + 2)"""),
        {"max_age": settings.max_item_age_days},
    ).scalar_one()
    backlog = db.execute(
        text("""
        SELECT count(*) FROM core.articles
        WHERE enrichment_status IN ('pending', 'failed') AND NOT is_hidden
          AND (enrichment_status = 'pending' OR enrichment_attempts < :max_attempts)"""),
        {"max_attempts": settings.enrich_max_attempts},
    ).scalar_one()
    sources = [
        dict(r._mapping)
        for r in db.execute(
            text("""
        SELECT slug, name, is_active, verification_status, last_success_at, consecutive_failures
        FROM core.sources WHERE slug NOT LIKE 'demo-%' ORDER BY name""")
        )
    ]
    demo = bool(
        db.execute(
            text("SELECT EXISTS (SELECT 1 FROM core.sources WHERE slug LIKE 'demo-%')")
        ).scalar()
    )
    heartbeat = (get_setting(db, SCHEDULER_HEARTBEAT) or {}).get("at")
    minutes = ((datetime.now(UTC) - last_success).total_seconds() / 60) if last_success else None
    collecting = demo or any(s["is_active"] for s in sources)
    if minutes is None or minutes > settings.alert_stale_pipeline_minutes or not collecting:
        state = "stale"
    elif (
        (last_finished is not None and last_finished != "succeeded")
        or any(s["is_active"] and s["consecutive_failures"] > 0 for s in sources)
        # auto-disabled after failing in a row: no longer failing, no longer collected either
        or any(not s["is_active"] and s["verification_status"] == "failing" for s in sources)
    ):
        state = "degraded"
    else:
        state = "ok"
    return {
        "status": state,
        "last_run_at": last.started_at if last else None,
        "last_run_status": last.status if last else None,
        "last_success_at": last_success,
        "minutes_since_success": round(minutes, 1) if minutes is not None else None,
        "scheduler_heartbeat_at": heartbeat,
        "articles_last_24h": new_24h,
        "enrichment_backlog": backlog,
        "sources": sources,
        "analysis": q.analysis_mode(db, local_today(settings)),
        "demo_data": demo,
        "version": __version__,
    }


@health_router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    """Prometheus metrics.

    Open only to direct scrapers on the private Docker network. Anything that came through the
    reverse proxy (``X-Forwarded-For`` present) or from a public address needs the admin token —
    defence in depth on top of Caddy not routing /metrics at all.
    """
    ip = client_ip(request, trust_proxy=False)
    try:
        private = not ipaddress.ip_address(ip).is_global
    except ValueError:
        private = ip in ("testclient", "unknown")
    if not private or "x-forwarded-for" in request.headers:
        require_admin(request)
    return Response(generate_latest(request.app.state.registry), media_type=CONTENT_TYPE_LATEST)


# ------------------------------------------------------------------------------------------
# Admin
# ------------------------------------------------------------------------------------------
class Reason(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


def _invalidate(request: Request) -> None:
    request.app.state.cache.clear()


@admin_router.get("/runs", summary="Recent pipeline runs")
def admin_runs(db: DB, limit: Annotated[int, Query(ge=1, le=200)] = 30) -> Any:
    runs = db.scalars(select(PipelineRun).order_by(desc(PipelineRun.started_at)).limit(limit))
    return [
        {
            "id": r.id,
            "trigger": r.trigger,
            "status": r.status,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "duration_ms": r.duration_ms,
            "error": r.error,
            "summary": {
                k: {kk: vv for kk, vv in v.items() if not isinstance(vv, list | dict)}
                for k, v in (r.stats or {}).items()
                if isinstance(v, dict)
            },
        }
        for r in runs
    ]


@admin_router.get("/runs/{run_id}", summary="Full statistics of one run")
def admin_run(db: DB, run_id: Annotated[int, Path(ge=1)]) -> Any:
    run = db.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "unknown run"})
    return {
        "id": run.id,
        "trigger": run.trigger,
        "status": run.status,
        "stages": run.stages,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_ms": run.duration_ms,
        "error": run.error,
        "stats": run.stats,
        "hostname": run.hostname,
    }


@admin_router.post(
    "/pipeline/run",
    status_code=202,
    summary="Ask the scheduler to start a run now (picked up within ~20 s)",
)
def admin_trigger_run(db: DB) -> Any:
    put_setting(
        db,
        RUN_REQUEST,
        {"pending": True, "requested_at": datetime.now(UTC).isoformat()},
        "admin-api",
    )
    db.commit()
    log.info("admin requested pipeline run")
    return {"requested": True}


@admin_router.get("/costs", summary="LLM usage and cost per day and per model")
def admin_costs(
    db: DB, settings: AppSettings, days: Annotated[int, Query(ge=1, le=366)] = 30
) -> Any:
    daily = [
        dict(r._mapping)
        for r in db.execute(
            text("""
        SELECT created_at::date AS day, model,
               count(*) FILTER (WHERE status <> 'cached') AS calls,
               count(*) FILTER (WHERE status = 'succeeded') AS succeeded,
               count(*) FILTER (WHERE status = 'cached') AS cached,
               count(*) FILTER (WHERE status IN ('failed', 'invalid', 'refused')) AS failed,
               sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens,
               sum(cache_read_tokens) AS cache_read_tokens,
               round(sum(cost_usd)::numeric, 4) AS cost_usd,
               round(avg(latency_ms) FILTER (WHERE status <> 'cached')) AS avg_latency_ms
        FROM core.enrichments WHERE created_at >= current_date - make_interval(days => :days)
        GROUP BY 1, 2 ORDER BY 1 DESC, 2"""),
            {"days": days},
        )
    ]
    spent = spent_today(db)
    paused, reason = (lambda v: (bool(v.get("paused")), v.get("reason")))(
        get_setting(db, ENRICHMENT_PAUSE) or {}
    )
    return {
        "today_usd": float(spent),
        "daily_budget_usd": settings.llm_daily_budget_usd,
        "remaining_today_usd": max(0.0, settings.llm_daily_budget_usd - float(spent)),
        "model": settings.llm_model,
        "enrichment_paused": paused,
        "pause_reason": reason,
        "daily": daily,
    }


@admin_router.post("/enrichment/pause", summary="Kill switch: stop all LLM calls")
def admin_pause(db: DB, body: Reason) -> Any:
    put_setting(
        db,
        ENRICHMENT_PAUSE,
        {"paused": True, "reason": body.reason, "at": datetime.now(UTC).isoformat()},
        "admin-api",
    )
    db.commit()
    log.warning("enrichment paused by admin", extra={"reason": body.reason})
    return {"paused": True}


@admin_router.post("/enrichment/resume")
def admin_resume(db: DB) -> Any:
    put_setting(
        db, ENRICHMENT_PAUSE, {"paused": False, "at": datetime.now(UTC).isoformat()}, "admin-api"
    )
    db.commit()
    return {"paused": False}


def _source(db: DB, slug: str) -> Source:
    src = db.scalar(select(Source).where(Source.slug == slug))
    if src is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "unknown source"})
    return src


@admin_router.post("/sources/{slug}/disable")
def admin_disable_source(request: Request, db: DB, slug: str, body: Reason) -> Any:
    src = _source(db, slug)
    src.is_active, src.disabled_reason = False, f"admin: {body.reason}"
    db.commit()
    _invalidate(request)
    return {"slug": slug, "is_active": False}


@admin_router.post("/sources/{slug}/enable")
def admin_enable_source(request: Request, db: DB, slug: str) -> Any:
    src = _source(db, slug)
    src.is_active, src.disabled_reason, src.consecutive_failures = True, None, 0
    db.commit()
    _invalidate(request)
    return {"slug": slug, "is_active": True}


@admin_router.post("/articles/{article_id}/hide", summary="Takedown: hide an article everywhere")
def admin_hide(
    request: Request, db: DB, article_id: Annotated[int, Path(ge=1)], body: Reason
) -> Any:
    result = db.execute(
        update(Article)
        .where(Article.id == article_id)
        .values(is_hidden=True, hidden_reason=body.reason)
    )
    if not result.rowcount:  # type: ignore[attr-defined]
        raise HTTPException(404, detail={"code": "not_found", "message": "unknown article"})
    db.commit()
    _invalidate(request)
    log.warning("article hidden", extra={"article_id": article_id, "reason": body.reason})
    return {"id": article_id, "hidden": True}


@admin_router.post("/articles/{article_id}/unhide")
def admin_unhide(request: Request, db: DB, article_id: Annotated[int, Path(ge=1)]) -> Any:
    result = db.execute(
        update(Article).where(Article.id == article_id).values(is_hidden=False, hidden_reason=None)
    )
    if not result.rowcount:  # type: ignore[attr-defined]
        raise HTTPException(404, detail={"code": "not_found", "message": "unknown article"})
    db.commit()
    _invalidate(request)
    return {"id": article_id, "hidden": False}


@admin_router.post("/articles/{article_id}/reenrich", status_code=202)
def admin_reenrich(db: DB, article_id: Annotated[int, Path(ge=1)]) -> Any:
    # Imported here: the enrichment service pulls in the LLM SDKs, half the API's start-up
    # time, for an admin call that is rare (and on serverless hosting, start-up is billed CPU).
    from gjurme.enrichment.service import requeue

    n = requeue(db, article_ids=[article_id])
    db.commit()
    if not n:
        raise HTTPException(404, detail={"code": "not_found", "message": "unknown article"})
    return {"id": article_id, "queued": True}


@admin_router.get("/quality", summary="Latest result of every data-quality check")
def admin_quality(db: DB) -> Any:
    return [
        dict(r._mapping)
        for r in db.execute(
            text("""
        SELECT DISTINCT ON (check_name) check_name, severity, status, observed, threshold,
               details, created_at, run_id
        FROM ops.data_quality_results ORDER BY check_name, created_at DESC""")
        )
    ]


@admin_router.get("/alerts", summary="Recent alerts (delivered and suppressed)")
def admin_alerts(db: DB, limit: Annotated[int, Query(ge=1, le=500)] = 50) -> Any:
    rows = db.scalars(select(AlertEvent).order_by(desc(AlertEvent.created_at)).limit(limit))
    return [
        {
            "id": a.id,
            "key": a.alert_key,
            "severity": a.severity,
            "title": a.title,
            "message": a.message,
            "delivered": a.delivered,
            "suppressed": a.suppressed,
            "delivery_error": a.delivery_error,
            "created_at": a.created_at,
        }
        for a in rows
    ]


@admin_router.get("/failures", summary="Recent enrichment failures and rejected feed items")
def admin_failures(db: DB, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Any:
    enrich = [
        dict(r._mapping)
        for r in db.execute(
            text("""
        SELECT e.article_id, e.status, e.error, e.model, e.prompt_version, e.attempt,
               e.created_at, a.title
        FROM core.enrichments e JOIN core.articles a ON a.id = e.article_id
        WHERE e.status IN ('failed', 'invalid', 'refused')
        ORDER BY e.created_at DESC LIMIT :limit"""),
            {"limit": limit},
        )
    ]
    rejected = [
        dict(r._mapping)
        for r in db.execute(
            text("""
        SELECT f.id, s.slug AS source, f.rejection_reason, f.link, f.processed_at
        FROM raw.feed_items f JOIN core.sources s ON s.id = f.source_id
        WHERE f.process_status = 'rejected'
        ORDER BY f.processed_at DESC NULLS LAST LIMIT :limit"""),
            {"limit": limit},
        )
    ]
    return {"enrichment": enrich, "rejected_items": rejected}
