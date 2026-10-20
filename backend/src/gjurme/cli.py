"""``gjurme`` command-line interface — every pipeline stage and operational task.

Examples::

    gjurme db upgrade                 # migrate + sync reference data + sync sources
    gjurme run                        # full pipeline once
    gjurme ingest --source telegrafi  # one stage, one source
    gjurme enrich --limit 20
    gjurme cluster                    # group articles into stories
    gjurme sources validate --markdown report.md
    gjurme scheduler                  # long-running (production)
    gjurme api                        # HTTP API (production: via uvicorn in Docker)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer
from alembic.config import Config
from sqlalchemy.orm import Session, sessionmaker

from gjurme.config import Settings, get_settings
from gjurme.logging_setup import configure_logging

app = typer.Typer(no_args_is_help=True, add_completion=False, help="GJURMË news intelligence.")
db_app = typer.Typer(no_args_is_help=True, help="Database migrations and reference data.")
sources_app = typer.Typer(no_args_is_help=True, help="Source registry management.")
demo_app = typer.Typer(no_args_is_help=True, help="Synthetic demo data (never in production).")
app.add_typer(db_app, name="db")
app.add_typer(sources_app, name="sources")
app.add_typer(demo_app, name="demo")

log = logging.getLogger("gjurme.cli")


def _settings(validate: bool = True) -> Settings:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    if validate:
        settings.validate_for_env()
    return settings


def alembic_config(database_url: str) -> Config:
    """Alembic config built in code: migrations ship inside the package (``gjurme:migrations``),
    so this works identically from a source checkout and from an installed wheel/image."""
    cfg = Config()
    cfg.set_main_option("script_location", "gjurme:migrations")
    cfg.attributes["database_url"] = database_url
    return cfg


def _echo_json(data: object) -> None:
    typer.echo(json.dumps(data, indent=2, default=str, ensure_ascii=False))


# =============================================================================================
# db
# =============================================================================================
@db_app.command("upgrade")
def db_upgrade(
    skip_sources: Annotated[bool, typer.Option(help="Do not sync sources.yaml")] = False,
) -> None:
    """Apply migrations, then sync topics and sources (idempotent)."""
    settings = _settings()
    from alembic import command

    from gjurme.db.reference import sync_topics
    from gjurme.db.session import session_scope
    from gjurme.sources.registry import load_registry, sync_sources

    config = alembic_config(settings.database_url)
    current = _db_revision(settings.database_url)
    if current is None or _known_revision(config, current):
        command.upgrade(config, "head")
        migrated = "head"
    else:
        # A rollback: the database was migrated by a newer release. Migrations are expand-only
        # (docs/DATA_MODEL.md#migrations), so this release runs on that schema as it is; failing
        # here would stop deploy.sh from rolling back at all.
        migrated = f"skipped: database is at {current}, newer than this release"
        typer.echo(f"warning: {migrated}", err=True)
    with session_scope() as s:
        topics = sync_topics(s)
        result = sync_sources(s, load_registry()) if not skip_sources else {}
    _echo_json({"migrated": migrated, "topics": topics, "sources": result})


def _db_revision(database_url: str) -> str | None:
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(
                conn, opts={"version_table_schema": "ops"}
            ).get_current_revision()
    finally:
        engine.dispose()


def _known_revision(config: Config, revision: str) -> bool:
    from alembic.script import ScriptDirectory

    try:
        return ScriptDirectory.from_config(config).get_revision(revision) is not None
    except Exception:  # alembic raises for a revision its scripts do not contain
        return False


@db_app.command("check")
def db_check() -> None:
    """Exit non-zero if the database is unreachable or migrations are pending."""
    settings = _settings(validate=False)
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    head = ScriptDirectory.from_config(alembic_config(settings.database_url)).get_current_head()
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        current = MigrationContext.configure(
            conn, opts={"version_table_schema": "ops"}
        ).get_current_revision()
    _echo_json({"current": current, "head": head})
    if current != head:
        raise typer.Exit(1)


# =============================================================================================
# sources
# =============================================================================================
@sources_app.command("list")
def sources_list() -> None:
    _settings(validate=False)
    from sqlalchemy import select

    from gjurme.db.models import Source
    from gjurme.db.session import session_scope

    with session_scope() as s:
        rows = [
            {
                "slug": x.slug,
                "active": x.is_active,
                "verification": x.verification_status,
                "failures": x.consecutive_failures,
                "last_success": x.last_success_at,
                "disabled_reason": x.disabled_reason,
                "feed_url": x.feed_url,
            }
            for x in s.scalars(select(Source).order_by(Source.slug))
        ]
    _echo_json(rows)


@sources_app.command("sync")
def sources_sync() -> None:
    """Upsert sources.yaml into the database."""
    _settings()
    from gjurme.db.session import session_scope
    from gjurme.sources.registry import load_registry, sync_sources

    with session_scope() as s:
        _echo_json(sync_sources(s, load_registry()))


def _set_active(slug: str, active: bool, reason: str | None) -> None:
    from sqlalchemy import select

    from gjurme.db.models import Source
    from gjurme.db.session import session_scope

    with session_scope() as s:
        src = s.scalar(select(Source).where(Source.slug == slug))
        if src is None:
            typer.echo(f"unknown source: {slug}", err=True)
            raise typer.Exit(2)
        src.is_active = active
        src.disabled_reason = None if active else (reason or "disabled by operator")
        if active:
            src.consecutive_failures = 0
    typer.echo(f"{slug}: {'enabled' if active else 'disabled'}")


@sources_app.command("enable")
def sources_enable(slug: str) -> None:
    _settings()
    _set_active(slug, True, None)


@sources_app.command("disable")
def sources_disable(slug: str, reason: Annotated[str, typer.Option()] = "operator") -> None:
    _settings()
    _set_active(slug, False, reason)


@sources_app.command("validate")
def sources_validate(
    slug: Annotated[list[str] | None, typer.Option("--slug", help="Limit to these slugs")] = None,
    markdown: Annotated[Path | None, typer.Option(help="Write a Markdown report")] = None,
    json_out: Annotated[Path | None, typer.Option("--json", help="Write a JSON report")] = None,
    strict: Annotated[bool, typer.Option(help="Exit 1 if an enabled source fails")] = False,
) -> None:
    """Fetch every registered feed (no database needed) and report what actually works."""
    settings = get_settings()
    configure_logging(settings.log_level, "text")
    from gjurme.ingestion.fetcher import FeedFetcher, build_http_client
    from gjurme.sources.registry import load_registry
    from gjurme.sources.validator import to_json, to_markdown, validate_source

    registry = load_registry()
    selected = [c for c in registry.sources if not slug or c.slug in slug]
    fetcher = FeedFetcher(
        client=build_http_client(settings.http_timeout_seconds),
        user_agent=settings.http_user_agent,
        max_bytes=settings.http_max_bytes,
        respect_robots=settings.respect_robots_txt,
    )
    reports = [validate_source(fetcher, cfg) for cfg in selected]
    fetcher.client.close()
    md = to_markdown(reports)
    typer.echo(md)
    if markdown:
        markdown.write_text(md, "utf-8")
    if json_out:
        json_out.write_text(
            json.dumps(to_json(reports), indent=2, default=str, ensure_ascii=False), "utf-8"
        )
    failing = [r.slug for r in reports if r.enabled and not r.ok]
    if strict and failing:
        typer.echo(f"failing enabled sources: {failing}", err=True)
        raise typer.Exit(1)


# =============================================================================================
# pipeline stages
# =============================================================================================
def _session_factory() -> sessionmaker[Session]:
    from gjurme.db.session import get_sessionmaker

    return get_sessionmaker()


@contextmanager
def _pipeline_lock(factory: sessionmaker[Session]) -> Iterator[None]:
    """Hold the scheduler's pipeline lock, so a stage run by hand never overlaps a scheduled run
    (two ENRICH stages analyse the same articles; two CLUSTER stages split the same stories)."""
    from gjurme.pipeline.locking import PIPELINE_LOCK_KEY, advisory_lock

    with advisory_lock(factory.kw["bind"], PIPELINE_LOCK_KEY) as acquired:
        if not acquired:
            typer.echo(
                "A pipeline run is in progress (it holds the lock). Try again shortly.", err=True
            )
            raise typer.Exit(1)
        yield


@app.command()
def run(
    stages: Annotated[str, typer.Option(help="Comma-separated stages")] = (
        "ingest,process,enrich,cluster,quality"
    ),
    source: Annotated[list[str] | None, typer.Option("--source")] = None,
) -> None:
    """Run the pipeline once (with the pipeline lock, recorded in ops.pipeline_runs)."""
    settings = _settings()
    from gjurme.pipeline.runner import run_pipeline

    result = run_pipeline(
        settings,
        _session_factory(),
        trigger="cli",
        stages=[x.strip() for x in stages.split(",") if x.strip()],
        only_sources=source,
    )
    _echo_json({"run_id": result.run_id, "status": result.status, "stats": result.stats})
    if result.status == "failed":
        raise typer.Exit(1)


@app.command()
def ingest(source: Annotated[list[str] | None, typer.Option("--source")] = None) -> None:
    """INGEST stage only."""
    settings = _settings()
    from gjurme.pipeline.runner import run_pipeline

    result = run_pipeline(
        settings, _session_factory(), trigger="cli", stages=["ingest"], only_sources=source
    )
    _echo_json(result.stats)


@app.command()
def process() -> None:
    """PROCESS stage only (raw → articles)."""
    settings = _settings()
    from gjurme.ingestion.processor import process_pending

    factory = _session_factory()
    with _pipeline_lock(factory), factory() as s:
        _echo_json(process_pending(s, settings).as_dict())


@app.command()
def enrich(
    limit: Annotated[int | None, typer.Option(help="Override ENRICH_MAX_PER_RUN")] = None,
    article_id: Annotated[list[int] | None, typer.Option("--article-id")] = None,
) -> None:
    """ENRICH stage only (respects budget, kill switch and circuit breaker)."""
    settings = _settings()
    if limit is not None:
        settings = settings.model_copy(update={"enrich_max_per_run": limit})
    from gjurme.enrichment.service import build_provider, run_enrichment

    factory = _session_factory()
    with _pipeline_lock(factory):
        stats = run_enrichment(factory, settings, build_provider(settings), article_ids=article_id)
    _echo_json(stats.as_dict())


@app.command()
def cluster(
    rebuild_days: Annotated[
        int | None,
        typer.Option(help="Re-cluster the last N days from scratch (story ids change)"),
    ] = None,
) -> None:
    """CLUSTER stage only: group articles that report the same event into stories."""
    settings = _settings()
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from gjurme.stories.clustering import cluster_pending, rebuild

    factory = _session_factory()
    with _pipeline_lock(factory), factory() as s:
        if rebuild_days is not None:
            since = datetime.now(ZoneInfo(settings.timezone)).date() - timedelta(days=rebuild_days)
            _echo_json(rebuild(s, settings, since))
        else:
            _echo_json(cluster_pending(s, settings).as_dict())


@app.command("stories-review")
def stories_review(
    hours: Annotated[int, typer.Option(help="Look-back window")] = 48,
    markdown: Annotated[Path | None, typer.Option(help="Also write the report here")] = None,
) -> None:
    """Markdown review of story clustering on the latest headlines (to check the thresholds)."""
    settings = _settings(validate=False)
    from gjurme.stories.review import review_report

    with _session_factory()() as s:
        report = review_report(s, settings, hours=hours)
    typer.echo(report)
    if markdown is not None:
        markdown.write_text(report, "utf-8")


@app.command("enrich-requeue")
def enrich_requeue(
    older_than_version: Annotated[str | None, typer.Option(help="Prompt version cut-off")] = None,
    failed: Annotated[bool, typer.Option(help="Requeue failed/skipped articles")] = False,
    article_id: Annotated[list[int] | None, typer.Option("--article-id")] = None,
    provider: Annotated[
        str | None,
        typer.Option(help="Articles analysed by this provider, e.g. 'fake' (keyword rules)"),
    ] = None,
) -> None:
    """Mark articles for re-enrichment (new prompt/model, post-outage recovery)."""
    _settings()
    from gjurme.db.session import session_scope
    from gjurme.enrichment.service import requeue

    with session_scope() as s:
        n = requeue(
            s,
            older_than_prompt=older_than_version,
            article_ids=article_id,
            include_failed=failed,
            provider=provider,
        )
    typer.echo(f"requeued {n} articles")


@app.command()
def quality() -> None:
    """Run data-quality checks now."""
    _settings()
    from gjurme.db.session import session_scope
    from gjurme.quality.checks import run_checks

    with session_scope() as s:
        results = run_checks(s, None)
    _echo_json(
        [
            {"check": r.name, "status": r.status, "observed": r.observed, "threshold": r.threshold}
            for r in results
        ]
    )


@app.command()
def openapi(
    out: Annotated[Path | None, typer.Option(help="Write to this file instead of stdout.")] = None,
) -> None:
    """Print the API's OpenAPI schema. The frontend generates its API types from it
    (frontend/src/shared/api/openapi.json, then `npm run api:types`)."""
    from gjurme.api.app import create_app

    doc = create_app(_settings(validate=False), sessionmaker()).openapi()
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if out is None:
        typer.echo(text, nl=False)
    else:
        out.write_text(text, encoding="utf-8")


@app.command()
def retention(dry_run: Annotated[bool, typer.Option()] = True) -> None:
    """Apply the retention policy (default: dry run)."""
    settings = _settings()
    from gjurme.db.session import session_scope
    from gjurme.pipeline.retention import apply_retention

    with session_scope() as s:
        _echo_json(apply_retention(s, settings, dry_run=dry_run))


@app.command()
def scheduler(
    once: Annotated[
        bool,
        typer.Option(
            "--once",
            help="One tick, then exit: for hosting without a long-running process, where an "
            "external timer (the free-hosting GitHub workflow) starts it. Exits 1 if the run "
            "failed.",
        ),
    ] = False,
) -> None:
    """Run forever: pipeline every SCHEDULER_INTERVAL_MINUTES, retention daily."""
    settings = _settings()
    from gjurme.pipeline.scheduler import Scheduler

    sched = Scheduler(settings, _session_factory())
    if once:
        sched.tick()
        typer.echo(f"pipeline run: {sched.last_status}")
        quality = sched.last_stats.get("quality") or {}
        in_github = os.environ.get("GITHUB_ACTIONS") == "true"
        for level, key in (("warning", "warnings"), ("error", "failures")):
            for name in quality.get(key) or []:
                typer.echo(f"data quality {level}: {name}")
                if in_github:  # an annotation on the run's summary page
                    typer.echo(f"::{level} title=Data quality::{name} (docs/OPERATIONS.md)")
        if sched.last_status in ("failed", "crashed"):
            raise typer.Exit(1)
        return
    sched.install_signal_handlers()
    sched.run_forever()


@app.command()
def healthcheck(
    component: Annotated[str, typer.Option(help="api | scheduler | db")] = "db",
    max_age_minutes: Annotated[int, typer.Option(help="Scheduler heartbeat max age")] = 5,
) -> None:
    """Container health probe. Exit 0 = healthy, 1 = unhealthy (used by Docker HEALTHCHECK)."""
    settings = get_settings()
    from datetime import UTC, datetime

    from sqlalchemy import create_engine, text

    try:
        engine = create_engine(settings.database_url, connect_args={"connect_timeout": 5})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            if component == "scheduler":
                row = conn.execute(
                    text("SELECT value->>'at' FROM ops.settings WHERE key = 'scheduler_heartbeat'")
                ).scalar()
                if row is None:
                    typer.echo("no heartbeat yet", err=True)
                    raise typer.Exit(1)
                age = (datetime.now(UTC) - datetime.fromisoformat(row)).total_seconds() / 60
                if age > max_age_minutes:
                    typer.echo(f"heartbeat is {age:.1f} min old", err=True)
                    raise typer.Exit(1)
        engine.dispose()
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"unhealthy: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo("ok")


@app.command("alert-test")
def alert_test() -> None:
    """Send a test alert through the configured webhook."""
    settings = _settings()
    from gjurme.alerts.engine import Alert, AlertDispatcher
    from gjurme.db.session import session_scope

    with session_scope() as s:
        events = AlertDispatcher(settings).dispatch(
            s, [Alert("test", "info", "Test alert", "If you can read this, alerting works.")]
        )
    _echo_json([{"delivered": e.delivered, "error": e.delivery_error} for e in events])


@app.command()
def api(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
    reload: Annotated[bool, typer.Option()] = False,
) -> None:
    """Serve the HTTP API (development convenience; production runs uvicorn directly)."""
    _settings()
    import uvicorn

    uvicorn.run(
        "gjurme.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_config=None,
    )


# =============================================================================================
# demo
# =============================================================================================
@demo_app.command("seed")
def demo_seed(
    days: Annotated[int, typer.Option()] = 30,
    enrich_all: Annotated[bool, typer.Option(help="Enrich with the fake provider")] = True,
) -> None:
    """Load a synthetic dataset through the real process, enrich and cluster stages (dev only)."""
    settings = _settings()
    from gjurme import demo
    from gjurme.db.reference import sync_topics
    from gjurme.db.session import session_scope
    from gjurme.enrichment.providers import FakeProvider
    from gjurme.enrichment.service import run_enrichment
    from gjurme.ingestion.processor import process_pending
    from gjurme.stories.clustering import cluster_pending

    try:
        with session_scope() as s:
            sync_topics(s)
            n = demo.seed(s, settings, days=days)
    except demo.DemoRefusedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    with _session_factory()() as s:
        processed = process_pending(s, settings, max_items=1_000_000).as_dict()
    enriched = {}
    if enrich_all:
        fake_settings = settings.model_copy(
            update={"enrich_max_per_run": 1_000_000, "enrich_concurrency": 1}
        )
        enriched = run_enrichment(_session_factory(), fake_settings, FakeProvider()).as_dict()
    with _session_factory()() as s:
        clustered = cluster_pending(s, settings, max_articles=1_000_000).as_dict()
    _echo_json({"raw_items": n, "process": processed, "enrich": enriched, "cluster": clustered})


def main() -> None:  # pragma: no cover
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
