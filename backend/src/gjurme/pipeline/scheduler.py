"""Long-running scheduler process (``gjurme scheduler``).

Why an in-container loop instead of cron / GitHub Actions / Airflow (ADR-005): the pipeline must
run next to the database (no public DB port), a missed tick must not be silently dropped, and
overlap protection is already provided by the PostgreSQL advisory lock. The loop is ~100 lines,
restarts via Docker's ``restart: unless-stopped`` and exits cleanly on SIGTERM (it finishes the
current run first, so deployments never interrupt a half-written batch).
"""

from __future__ import annotations

import logging
import signal
import threading
from datetime import UTC, datetime, timedelta
from types import FrameType

from sqlalchemy.orm import Session, sessionmaker

from gjurme.config import Settings
from gjurme.pipeline.retention import apply_retention
from gjurme.pipeline.runner import run_pipeline
from gjurme.runtime_settings import RUN_REQUEST, get_setting, put_setting

log = logging.getLogger(__name__)

HEARTBEAT_KEY = "scheduler_heartbeat"
RETENTION_KEY = "retention_last_run"
POLL_SECONDS = 20


class Scheduler:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.interval = timedelta(minutes=settings.scheduler_interval_minutes)
        self._stop = threading.Event()
        self.next_run = datetime.now(UTC)  # run immediately on start

    def install_signal_handlers(self) -> None:
        def _handler(signum: int, _frame: FrameType | None) -> None:
            log.info("shutdown requested — finishing current work", extra={"signal": signum})
            self._stop.set()

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)

    def stop(self) -> None:
        self._stop.set()

    def tick(self) -> bool:
        """One scheduler iteration. Returns True if a pipeline run was started."""
        now = datetime.now(UTC)
        with self.session_factory() as s, s.begin():
            put_setting(
                s,
                HEARTBEAT_KEY,
                {"at": now.isoformat(), "next_run": self.next_run.isoformat()},
                "scheduler",
            )
            request = get_setting(s, RUN_REQUEST)
            if request and request.get("pending"):
                put_setting(
                    s,
                    RUN_REQUEST,
                    {**request, "pending": False, "picked_up_at": now.isoformat()},
                    "scheduler",
                )
        manual = bool(request and request.get("pending"))
        started = False
        if manual or now >= self.next_run:
            trigger = "admin" if manual else "schedule"
            try:
                run_pipeline(self.settings, self.session_factory, trigger=trigger)
            except Exception:
                log.exception("pipeline run crashed")
            self.next_run = datetime.now(UTC) + self.interval
            started = True
        self._maybe_retention(now)
        return started

    def _maybe_retention(self, now: datetime) -> None:
        with self.session_factory() as s, s.begin():
            last = (get_setting(s, RETENTION_KEY) or {}).get("at")
            if last and now - datetime.fromisoformat(last) < timedelta(hours=24):
                return
            try:
                result = apply_retention(s, self.settings)
            except Exception:
                log.exception("retention failed")
                return
            put_setting(s, RETENTION_KEY, {"at": now.isoformat(), "result": result}, "scheduler")

    def run_forever(self) -> None:
        log.info(
            "scheduler started",
            extra={"interval_minutes": self.settings.scheduler_interval_minutes},
        )
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                # e.g. database temporarily unreachable: log, back off, keep the process alive
                log.exception("scheduler tick failed")
            self._stop.wait(POLL_SECONDS)
        log.info("scheduler stopped")
