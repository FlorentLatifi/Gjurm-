from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from gjurme.cli import app
from gjurme.config import get_settings
from gjurme.db.models import Source
from gjurme.db.session import get_engine, get_sessionmaker
from gjurme.sources.registry import Registry, SourceConfig, load_registry, sync_sources
from gjurme.sources.validator import to_markdown, validate_source
from tests.conftest import TEST_DATABASE_URL, feed_server, fixture_bytes

pytestmark = pytest.mark.integration


def test_bundled_registry_is_valid() -> None:
    reg = load_registry()
    slugs = [s.slug for s in reg.sources]
    assert len(slugs) == len(set(slugs)) >= 5
    for src in reg.sources:
        assert not src.enabled or src.feed_url


@pytest.mark.parametrize(
    "bad",
    [
        {
            "slug": "Bad Slug",
            "name": "x",
            "homepage_url": "https://a.example.com/",
            "language": "sq",
            "country": "XK",
        },
        {
            "slug": "ok",
            "name": "x",
            "homepage_url": "javascript:alert(1)",
            "language": "sq",
            "country": "XK",
        },
        {
            "slug": "ok",
            "name": "x",
            "homepage_url": "https://a.example.com/",
            "language": "sq",
            "country": "XK",
            "enabled": True,
        },  # enabled without feed_url
        {
            "slug": "ok",
            "name": "x",
            "homepage_url": "http://10.0.0.1/",
            "language": "sq",
            "country": "XK",
            "feed_url": "http://10.0.0.1/feed",
        },
    ],
)
def test_registry_rejects_invalid_entries(bad: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="validation error"):
        SourceConfig.model_validate(bad)


def test_registry_rejects_duplicate_slugs() -> None:
    entry = {
        "slug": "aa",
        "name": "A",
        "homepage_url": "https://a.example.com/",
        "feed_url": "https://a.example.com/feed",
        "language": "sq",
        "country": "XK",
    }
    with pytest.raises(ValueError, match="duplicate"):
        Registry.model_validate({"sources": [entry, entry]})


def test_sync_sources_semantics(session) -> None:  # type: ignore[no-untyped-def]
    def reg(enabled: bool, feed: str) -> Registry:
        return Registry.model_validate(
            {
                "sources": [
                    {
                        "slug": "aa",
                        "name": "A",
                        "homepage_url": "https://a.example.com/",
                        "feed_url": feed,
                        "language": "sq",
                        "country": "XK",
                        "enabled": enabled,
                    }
                ]
            }
        )

    assert sync_sources(session, reg(True, "https://a.example.com/feed")) == {
        "created": 1,
        "updated": 0,
    }
    src = session.scalar(select(Source))
    src.etag, src.consecutive_failures = '"x"', 4
    session.flush()
    assert sync_sources(session, reg(True, "https://a.example.com/feed"))["updated"] == 0
    # changing the URL resets runtime state that belonged to the old URL
    sync_sources(session, reg(True, "https://a.example.com/rss"))
    assert src.etag is None and src.consecutive_failures == 0
    # YAML disable wins; YAML re-enable restores only YAML-caused disables
    sync_sources(session, reg(False, "https://a.example.com/rss"))
    assert not src.is_active
    sync_sources(session, reg(True, "https://a.example.com/rss"))
    assert src.is_active
    src.is_active, src.disabled_reason = False, "auto-disabled after 20 failures"
    sync_sources(session, reg(True, "https://a.example.com/rss"))
    assert not src.is_active  # operator/auto disables are not silently undone


def test_validator_reports_and_autodiscovers(make_fetcher) -> None:  # type: ignore[no-untyped-def]
    cfg = SourceConfig(
        slug="pp",
        name="Portali",
        homepage_url="https://portali.example.com/",
        feed_url="https://portali.example.com/wrong",
        enabled=True,
        discovery_urls=("https://portali.example.com/",),
        language="sq",
        country="XK",
    )
    fetcher = make_fetcher(
        feed_server(
            {
                "https://portali.example.com/": (200, fixture_bytes("not_a_feed.html"), {}),
                "https://portali.example.com/feed/": (200, fixture_bytes("wordpress_sq.xml"), {}),
                "https://portali.example.com/atom.xml": (200, fixture_bytes("atom.xml"), {}),
            }
        )
    )
    report = validate_source(fetcher, cfg)
    assert not report.ok and report.declared and report.declared.status == "http_error"
    working = {d.url: d for d in report.discovered if d.ok}
    wp = working["https://portali.example.com/feed/"]
    assert wp.items == 3 and wp.albanian_chars_seen and wp.field_coverage["title"] == 1.0
    assert wp.has_full_content
    assert (
        report.recommendation
        == "replace feed_url with discovered feed https://portali.example.com/feed/"
    )
    md = to_markdown([report])
    assert "| Portali |" in md and "Discovered feeds for Portali" in md


def test_validator_tries_the_usual_feed_paths(make_fetcher) -> None:  # type: ignore[no-untyped-def]
    cfg = SourceConfig(
        slug="tv",
        name="Televizioni",
        homepage_url="https://tv.example.com/",
        feed_url="https://tv.example.com/feed/",
        language="sq",
        country="AL",
    )
    # the homepage links no feed, the declared one is gone, but the CMS serves /rss
    fetcher = make_fetcher(
        feed_server(
            {
                "https://tv.example.com/": (200, b"<html><body>Lajme</body></html>", {}),
                "https://tv.example.com/rss": (200, fixture_bytes("wordpress_sq.xml"), {}),
            }
        )
    )
    report = validate_source(fetcher, cfg)
    assert [d.url for d in report.discovered] == ["https://tv.example.com/rss"]
    assert (
        report.recommendation == "replace feed_url with discovered feed https://tv.example.com/rss"
    )


def test_validator_ok_source(make_fetcher) -> None:  # type: ignore[no-untyped-def]
    cfg = SourceConfig(
        slug="rr",
        name="Regional",
        homepage_url="https://regional.example.org/",
        feed_url="https://regional.example.org/feed",
        language="en",
        country="REG",
    )
    fetcher = make_fetcher(
        feed_server({"https://regional.example.org/feed": (200, fixture_bytes("atom.xml"), {})})
    )
    report = validate_source(fetcher, cfg)
    assert report.ok and report.declared is not None and report.declared.items == 2
    assert report.discovered == []


# ------------------------------------------------------------------------------------------
# CLI (in-process, against the test database)
# ------------------------------------------------------------------------------------------
@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, db):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("GJURME_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LOG_FORMAT", "text")
    for cached in (get_settings, get_engine, get_sessionmaker):
        cached.cache_clear()
    yield CliRunner()
    for cached in (get_settings, get_engine, get_sessionmaker):
        cached.cache_clear()


def test_cli_db_upgrade_check_and_sources(cli_env: CliRunner) -> None:
    result = cli_env.invoke(app, ["db", "upgrade"])
    assert result.exit_code == 0, result.output
    assert cli_env.invoke(app, ["db", "check"]).exit_code == 0
    listed = cli_env.invoke(app, ["sources", "list"])
    assert "telegrafi" in listed.output
    assert (
        cli_env.invoke(app, ["sources", "disable", "telegrafi", "--reason", "test"]).exit_code == 0
    )
    assert cli_env.invoke(app, ["sources", "enable", "telegrafi"]).exit_code == 0
    assert cli_env.invoke(app, ["sources", "enable", "nope"]).exit_code == 2


def test_cli_demo_process_enrich_quality_retention(cli_env: CliRunner) -> None:
    result = cli_env.invoke(app, ["demo", "seed", "--days", "2"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output[result.output.index("\n{") :])
    assert payload["process"]["accepted"] > 0 and payload["enrich"]["failed_total"] == 0
    assert cli_env.invoke(app, ["process"]).exit_code == 0
    assert cli_env.invoke(app, ["enrich", "--limit", "5"]).exit_code == 0
    assert cli_env.invoke(app, ["enrich-requeue", "--failed"]).exit_code == 0
    assert cli_env.invoke(app, ["quality"]).exit_code == 0
    dry = cli_env.invoke(app, ["retention"])
    assert dry.exit_code == 0 and '"dry_run": true' in dry.output


def test_cli_run_with_no_active_sources(cli_env: CliRunner) -> None:
    result = cli_env.invoke(app, ["run", "--stages", "ingest,process,quality"])
    assert result.exit_code == 0, result.output
    assert '"status": "succeeded"' in result.output


@pytest.mark.parametrize(("status", "exit_code"), [("succeeded", 0), ("partial", 0), ("failed", 1)])
def test_cli_scheduler_once_is_one_tick(
    cli_env: CliRunner, monkeypatch: pytest.MonkeyPatch, status: str, exit_code: int
) -> None:
    """Hosting without a long-running process (the free-hosting workflow) runs one tick per
    timer: heartbeat, pipeline, daily retention; a failed run fails the job."""
    from types import SimpleNamespace

    from gjurme.runtime_settings import SCHEDULER_HEARTBEAT, get_setting

    calls: list[str] = []

    def fake_run(_settings: object, _factory: object, trigger: str) -> SimpleNamespace:
        calls.append(trigger)
        quality = {"warnings": ["database_size"], "failures": []}
        return SimpleNamespace(status=status, stats={"quality": quality})

    monkeypatch.setattr("gjurme.pipeline.scheduler.run_pipeline", fake_run)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    result = cli_env.invoke(app, ["scheduler", "--once"])
    assert result.exit_code == exit_code, result.output
    assert f"pipeline run: {status}" in result.output and calls == ["schedule"]
    # a warning shows on the workflow run's page; it does not fail the job
    assert "::warning title=Data quality::database_size" in result.output
    with get_sessionmaker()() as s:
        assert get_setting(s, SCHEDULER_HEARTBEAT) is not None
        assert get_setting(s, "retention_last_run") is not None


def test_cli_validate_writes_reports(
    cli_env: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gjurme.sources import validator

    def fake_validate(_fetcher, cfg):  # type: ignore[no-untyped-def]
        return validator.SourceReport(
            slug=cfg.slug,
            name=cfg.name,
            enabled=cfg.enabled,
            declared_feed=cfg.feed_url,
            declared=None,
            recommendation="offline test",
        )

    monkeypatch.setattr(validator, "validate_source", fake_validate)
    md, js = tmp_path / "r.md", tmp_path / "r.json"
    result = cli_env.invoke(
        app,
        [
            "sources",
            "validate",
            "--slug",
            "koha",
            "--markdown",
            str(md),
            "--json",
            str(js),
            "--strict",
        ],
    )
    assert result.exit_code == 1  # strict: an enabled source has no working feed
    assert "KOHA" in md.read_text() and json.loads(js.read_text())[0]["slug"] == "koha"


def test_cli_refuses_unsafe_production_config(
    cli_env: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GJURME_ENV", "production")
    get_settings.cache_clear()
    result = cli_env.invoke(app, ["run"])
    assert result.exit_code != 0
    assert "ADMIN_API_TOKEN" in str(result.exception)


@pytest.mark.parametrize(
    "command", [["enrich"], ["cluster"], ["cluster", "--rebuild-days", "1"], ["process"]]
)
def test_stage_commands_do_not_overlap_a_pipeline_run(
    cli_env: CliRunner, command: list[str]
) -> None:
    """Run by hand next to the scheduler, two ENRICH stages analysed the same articles."""
    from gjurme.pipeline.locking import PIPELINE_LOCK_KEY, advisory_lock

    with advisory_lock(get_engine(), PIPELINE_LOCK_KEY) as acquired:
        assert acquired
        result = cli_env.invoke(app, command)
    assert result.exit_code == 1
    assert "pipeline run is in progress" in result.output
    assert cli_env.invoke(app, command).exit_code == 0  # free again


def test_db_upgrade_on_a_newer_database_lets_a_rollback_run(cli_env: CliRunner) -> None:
    """deploy.sh rolls back by starting the previous release, whose `db upgrade` runs first;
    against a database a newer release migrated, alembic used to fail and stop the rollback."""
    from sqlalchemy import text

    assert cli_env.invoke(app, ["db", "upgrade"]).exit_code == 0
    with get_engine().begin() as conn:
        head = conn.execute(text("SELECT version_num FROM ops.alembic_version")).scalar_one()
        conn.execute(text("UPDATE ops.alembic_version SET version_num = '9999_from_the_future'"))
    try:
        result = cli_env.invoke(app, ["db", "upgrade"])
        assert result.exit_code == 0, result.output
        assert "skipped: database is at 9999_from_the_future" in result.output
    finally:
        with get_engine().begin() as conn:
            conn.execute(text("UPDATE ops.alembic_version SET version_num = :v"), {"v": head})
