"""How long a CDN keeps a public answer: until just after the next pipeline run (ADR-034).

On free hosting (ADR-027) every answer the CDN does not hold calls the function, and the
function's queries wake the Neon database, which then stays awake (and billed) for 5 minutes.
The data changes only when the pipeline runs, every ``SCHEDULER_INTERVAL_MINUTES``. So instead of
a fixed lifetime, an answer is kept until the next run should have finished, plus a short
margin, never longer than ``CDN_CACHE_SECONDS``:

* the answers readers ask for often expire together, a couple of minutes after a run, and are
  fetched again while that run has left the database awake: they no longer wake it;
* readers see a run's news a couple of minutes after it, instead of up to a fixed lifetime
  later;
* while a run is in progress, answers expire shortly after its expected end; if a run is late,
  they wait in steps of a few minutes, then of one interval once it is very late, so a stopped
  pipeline does not make every reader's request wake the database.

``stale-while-revalidate`` lets the CDN answer at once from the expired copy while it fetches a
new one; ``stale-if-error`` keeps the site readable from the CDN for a week if the database is
unreachable (a free plan's compute suspended until the next month, say).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from gjurme.config import Settings

log = logging.getLogger(__name__)

# after the expected end of a run: its last writes, and the CDN's clock against ours
MARGIN = timedelta(minutes=2)
# never less: a shorter lifetime saves no freshness worth a function call
FLOOR = timedelta(minutes=1)
# while a run is in progress, or late by less than one interval: look again this often
SHORT_STEP = timedelta(minutes=3)
# when the clock cannot be read (the database answered the request, then failed): as before
FALLBACK_SECONDS = 300
DEFAULT_DURATION = timedelta(minutes=3)


@dataclass(frozen=True, slots=True)
class RunClock:
    """The latest pipeline run's start, whether it is still running, and how long runs take."""

    started_at: datetime
    running: bool
    duration: timedelta


def edge_ttl(now: datetime, clock: RunClock | None, interval: timedelta, cap: int) -> int:
    """Seconds the CDN may keep an answer computed at ``now``."""
    if cap <= 0:
        return 0
    if clock is None:  # no run yet (a new or demo database): nothing will change it soon
        return cap
    # The shortest recent run: expiring too early costs a fetch while the database is awake
    # anyway; expiring too late, after it went back to sleep, costs a wake-up.
    duration = min(max(clock.duration, timedelta(minutes=1)), interval / 2)
    running = clock.running and now - clock.started_at < interval
    if running:
        expires = clock.started_at + duration + MARGIN
    else:
        expires = clock.started_at + interval + duration + MARGIN
    if expires - now < FLOOR:
        # The run is longer than expected, or the next one is late: look again soon while that
        # is likely, then once an interval when the pipeline seems to have stopped.
        late = now - expires
        step = SHORT_STEP if running or late < interval else interval
        expires += step * math.ceil((now + FLOOR - expires) / step)
    return max(1, min(cap, int((expires - now).total_seconds())))


def cdn_cache_control(ttl: int, settings: Settings) -> str:
    swr = settings.scheduler_interval_minutes * 60
    value = f"public, max-age={ttl}, stale-while-revalidate={swr}"
    if settings.cdn_stale_if_error_seconds:
        value += f", stale-if-error={settings.cdn_stale_if_error_seconds}"
    return value


_LATEST_RUNS = text("""
    SELECT started_at, finished_at, status FROM ops.pipeline_runs
    WHERE status <> 'skipped_locked' ORDER BY started_at DESC LIMIT 4
""")


def read_clock(session: Session) -> RunClock | None:
    rows = session.execute(_LATEST_RUNS).all()
    if not rows:
        return None
    durations = [
        r.finished_at - r.started_at
        for r in rows
        if r.status != "running" and r.finished_at is not None
    ]
    return RunClock(
        started_at=rows[0].started_at,
        running=rows[0].status == "running",
        duration=min(durations) if durations else DEFAULT_DURATION,
    )


class EdgeClock:
    """The run clock, read at most every ``memo_seconds`` per API process. It is read only when
    the function computes a cacheable answer, i.e. when the database is already awake."""

    def __init__(self, session_factory: Callable[[], Session], memo_seconds: float = 30.0) -> None:
        self._factory = session_factory
        self._memo = memo_seconds
        self._lock = threading.Lock()
        self._read_at = -math.inf
        self._clock: RunClock | None = None

    def ttl(self, settings: Settings, now: datetime | None = None) -> int:
        cap = settings.cdn_cache_seconds
        try:
            with self._lock:
                if time.monotonic() - self._read_at > self._memo:
                    with self._factory() as s:
                        self._clock = read_clock(s)
                    self._read_at = time.monotonic()
                clock = self._clock
        except Exception as exc:
            log.warning("pipeline clock unavailable", extra={"error": str(exc)[:200]})
            return min(cap, FALLBACK_SECONDS)
        interval = timedelta(minutes=settings.scheduler_interval_minutes)
        return edge_ttl(now or datetime.now(UTC), clock, interval, cap)
