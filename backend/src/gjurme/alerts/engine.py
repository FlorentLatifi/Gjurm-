"""Alerting: rules evaluated after each pipeline run, delivered to one webhook.

Deliberately small: one notification channel (Slack, Discord, ntfy.sh or generic JSON webhook),
a handful of rules that each mean "a human should look", and per-key de-duplication so a
persistent problem produces one message per ``ALERT_DEDUP_HOURS`` rather than one per run.
Every alert — delivered or suppressed — is recorded in ``ops.alert_events``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from gjurme.config import Settings
from gjurme.db.models import AlertEvent

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Alert:
    key: str
    severity: str  # info | warning | critical
    title: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def evaluate_run(run_status: str, stats: dict[str, Any]) -> list[Alert]:
    """Turn a finished run's stats into alerts. Pure function — easy to unit test."""
    alerts: list[Alert] = []
    today = datetime.now(UTC).date().isoformat()
    if run_status == "failed":
        alerts.append(
            Alert(
                "pipeline_failed",
                "critical",
                "Pipeline run failed",
                f"Run failed: {stats.get('error', 'unknown error')}",
                {"errors": stats.get("stage_errors", {})},
            )
        )
    ingest = stats.get("ingest") or {}
    if ingest.get("sources_total", 0) > 0 and ingest.get("sources_ok", 0) == 0:
        alerts.append(
            Alert(
                "all_sources_down",
                "critical",
                "All news sources failed",
                f"0 of {ingest['sources_total']} sources could be fetched.",
                {
                    "per_source": [
                        {"slug": s["slug"], "status": s["status"], "error": s["error"]}
                        for s in ingest.get("per_source", [])
                    ]
                },
            )
        )
    for slug in ingest.get("auto_disabled", []):
        alerts.append(
            Alert(
                f"source_auto_disabled:{slug}",
                "warning",
                f"Source auto-disabled: {slug}",
                f"'{slug}' was disabled after repeated failures. Check the feed and "
                f"re-enable with `gjurme sources enable {slug}`.",
            )
        )
    enrich = stats.get("enrich") or {}
    if enrich.get("budget_exhausted"):
        alerts.append(
            Alert(
                f"llm_budget_exhausted:{today}",
                "warning",
                "Daily LLM budget reached",
                f"Enrichment stopped at ${enrich.get('spent_today_usd', 0):.2f}; "
                "remaining articles stay queued until tomorrow (UTC).",
            )
        )
    if enrich.get("fatal_error"):
        alerts.append(
            Alert(
                "llm_fatal_error",
                "critical",
                "LLM configuration error",
                f"Enrichment stopped: {enrich['fatal_error']}",
            )
        )
    elif enrich.get("circuit_open"):
        alerts.append(
            Alert(
                "llm_circuit_open",
                "critical",
                "Enrichment circuit breaker open",
                "Repeated consecutive LLM failures; enrichment paused for this run.",
                {"failed": enrich.get("failed", {})},
            )
        )
    for check in (stats.get("quality") or {}).get("results", []):
        if check["status"] == "fail" or (
            check["name"] == "article_volume_anomaly" and check["status"] == "warn"
        ):
            alerts.append(
                Alert(
                    f"dq:{check['name']}",
                    "warning",
                    f"Data quality: {check['name']} = {check['status']}",
                    f"Observed {check['observed']} (threshold {check['threshold']}).",
                    check.get("details") or {},
                )
            )
    return alerts


def _format_payload(
    fmt: str, alert: Alert, env: str
) -> tuple[dict[str, Any] | str, dict[str, str]]:
    icon = {"critical": "🔴", "warning": "🟠", "info": "🔵"}.get(alert.severity, "")
    line = f"{icon} [GJURMË {env}] {alert.title}\n{alert.message}"
    if fmt == "slack":
        return {"text": line}, {}
    if fmt == "discord":
        return {"content": line[:1900]}, {}
    if fmt == "ntfy":
        return alert.message, {
            "Title": f"[GJURMË {env}] {alert.title}",
            "Priority": "high" if alert.severity == "critical" else "default",
        }
    return {
        "key": alert.key,
        "severity": alert.severity,
        "title": alert.title,
        "message": alert.message,
        "details": alert.details,
        "env": env,
    }, {}


class AlertDispatcher:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client

    def dispatch(self, session: Session, alerts: list[Alert]) -> list[AlertEvent]:
        events: list[AlertEvent] = []
        window = datetime.now(UTC) - timedelta(hours=self.settings.alert_dedup_hours)
        for alert in alerts:
            recent = session.scalar(
                select(AlertEvent.id)
                .where(
                    AlertEvent.alert_key == alert.key,
                    AlertEvent.created_at >= window,
                    AlertEvent.suppressed.is_(False),
                )
                .limit(1)
            )
            event = AlertEvent(
                alert_key=alert.key,
                severity=alert.severity,
                title=alert.title,
                message=alert.message,
                details=alert.details,
                suppressed=recent is not None,
            )
            if not event.suppressed:
                event.delivered, event.delivery_error = self._send(alert)
            session.add(event)
            events.append(event)
            log.log(
                logging.ERROR if alert.severity == "critical" else logging.WARNING,
                "alert",
                extra={
                    "alert_key": alert.key,
                    "title": alert.title,
                    "suppressed": event.suppressed,
                    "delivered": event.delivered,
                },
            )
        session.flush()
        return events

    def _send(self, alert: Alert) -> tuple[bool, str | None]:
        if self.settings.alert_webhook_url is None:
            return False, "no ALERT_WEBHOOK_URL configured (logged only)"
        url = self.settings.alert_webhook_url.get_secret_value()
        body, headers = _format_payload(
            self.settings.alert_webhook_format, alert, self.settings.gjurme_env.value
        )
        client = self._client or httpx.Client(timeout=10)
        try:
            if isinstance(body, str):
                resp = client.post(url, content=body.encode("utf-8"), headers=headers)
            else:
                resp = client.post(url, json=body, headers=headers)
            if resp.status_code >= 300:
                return False, f"HTTP {resp.status_code}"
            return True, None
        except httpx.HTTPError as exc:
            return False, f"{type(exc).__name__}: {exc}"[:300]
        finally:
            if self._client is None:
                client.close()
