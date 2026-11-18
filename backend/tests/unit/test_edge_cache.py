"""CDN lifetimes timed to the pipeline (api/edge_cache.py, ADR-034)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gjurme.api.edge_cache import EdgeClock, RunClock, cdn_cache_control, edge_ttl
from gjurme.config import Settings

T0 = datetime(2026, 11, 18, 16, 1, tzinfo=UTC)  # a run starts at :01, as the live clock does
INTERVAL = timedelta(minutes=30)
CAP = 1800


def ttl_at(minutes: float, clock: RunClock | None, cap: int = CAP) -> int:
    return edge_ttl(T0 + timedelta(minutes=minutes), clock, INTERVAL, cap)


def finished(duration: float = 4) -> RunClock:
    return RunClock(T0, running=False, duration=timedelta(minutes=duration))


def test_an_answer_expires_two_minutes_after_the_next_run_should_end() -> None:
    # after a 4-minute run that started at 16:01, the next starts 16:31 and ends 16:35: every
    # answer expires at 16:37, whenever it was computed
    for minute in (5, 10, 20, 30):
        expires = T0 + timedelta(minutes=minute, seconds=ttl_at(minute, finished(), cap=3600))
        assert expires == T0 + timedelta(minutes=36)
    assert ttl_at(5, finished()) == CAP  # never beyond CDN_CACHE_SECONDS


def test_the_shortest_recent_run_sets_the_expected_end() -> None:
    """Expiring early costs one fetch while the database is awake; late, a wake-up."""
    assert ttl_at(5, finished(1)) == (33 - 5) * 60
    assert ttl_at(5, finished(0.1)) == (33 - 5) * 60  # at least a minute
    assert ttl_at(5, finished(25), cap=3600) == (30 + 15 + 2 - 5) * 60  # at most half


def test_during_a_run_answers_expire_soon_after_its_expected_end() -> None:
    running = RunClock(T0, running=True, duration=timedelta(minutes=4))
    assert ttl_at(1, running) == 5 * 60  # ends 16:05, +2: 16:07
    # longer than expected: look again every 3 minutes
    assert 60 <= ttl_at(8, running) <= 4 * 60
    assert 60 <= ttl_at(14, running) <= 4 * 60


def test_a_late_run_is_waited_for_in_short_steps_a_stopped_pipeline_in_intervals() -> None:
    # expected 16:37; at 16:40 the next run has not started: a few minutes at a time
    assert 60 <= ttl_at(39, finished()) <= 4 * 60
    # hours later the pipeline seems stopped: once an interval, not every few minutes
    long = [ttl_at(minute, finished()) for minute in range(120, 180, 7)]
    assert all(60 <= t <= CAP for t in long) and sum(long) / len(long) > 10 * 60


def test_a_run_marked_running_for_longer_than_an_interval_is_dead() -> None:
    stuck = RunClock(T0, running=True, duration=timedelta(minutes=4))
    assert ttl_at(200, stuck) == ttl_at(200, finished())


def test_no_run_yet_and_the_cap() -> None:
    assert ttl_at(0, None) == CAP
    assert ttl_at(5, finished(), cap=300) == 300
    assert ttl_at(5, finished(), cap=0) == 0


def test_header_carries_stale_while_revalidate_and_stale_if_error() -> None:
    settings = Settings(_env_file=None, scheduler_interval_minutes=30)  # type: ignore[call-arg]
    assert cdn_cache_control(600, settings) == (
        "public, max-age=600, stale-while-revalidate=1800, stale-if-error=604800"
    )
    off = settings.model_copy(update={"cdn_stale_if_error_seconds": 0})
    assert cdn_cache_control(600, off) == "public, max-age=600, stale-while-revalidate=1800"


def test_clock_is_read_once_per_memo_and_failures_fall_back() -> None:
    reads: list[int] = []

    class Session:
        def __enter__(self) -> Session:
            reads.append(1)
            raise RuntimeError("database gone")

        def __exit__(self, *exc: object) -> None:
            return None

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, cdn_cache_seconds=CAP, scheduler_interval_minutes=30
    )
    clock = EdgeClock(Session, memo_seconds=60)  # type: ignore[arg-type]
    assert clock.ttl(settings) == 300  # the former fixed lifetime
    assert clock.ttl(settings) == 300 and len(reads) == 2  # a failure is not remembered


@pytest.mark.parametrize("minute", [0, 5, 13, 29])
def test_lifetime_never_exceeds_the_cap_nor_drops_below_a_minute(minute: int) -> None:
    for clock in (finished(), RunClock(T0, running=True, duration=timedelta(minutes=4)), None):
        assert 60 <= ttl_at(minute, clock) <= CAP
