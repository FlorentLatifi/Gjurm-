"""The API's response cache: TTL, single-flight and a bound on concurrent computations."""

from __future__ import annotations

import threading
import time

import pytest

from gjurme.api.security import Overloaded, TTLCache


def test_hits_until_the_ttl_expires() -> None:
    cache = TTLCache(0.05)
    calls: list[int] = []
    assert cache.get_or_set("k", lambda: calls.append(1) or "v") == "v"
    assert cache.get_or_set("k", lambda: calls.append(1) or "w") == "v"
    time.sleep(0.06)
    assert cache.get_or_set("k", lambda: calls.append(1) or "w") == "w"
    assert len(calls) == 2


def test_concurrent_misses_on_one_key_compute_once() -> None:
    cache = TTLCache(60)
    calls: list[int] = []
    results: list[str] = []

    def slow() -> str:
        calls.append(1)
        time.sleep(0.1)
        return "v"

    threads = [
        threading.Thread(target=lambda: results.append(cache.get_or_set("k", slow)))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1 and results == ["v"] * 8


def test_without_a_ttl_identical_requests_still_share_one_computation() -> None:
    cache = TTLCache(0)
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def slow() -> str:
        calls.append(1)
        started.set()
        release.wait(1)
        return "v"

    leader = threading.Thread(target=cache.get_or_set, args=("k", slow))
    leader.start()
    started.wait(1)
    follower: list[str] = []
    t = threading.Thread(target=lambda: follower.append(cache.get_or_set("k", slow)))
    t.start()
    release.set()
    leader.join()
    t.join()
    assert follower == ["v"] and len(calls) == 1
    assert cache.get_or_set("k", lambda: "fresh") == "fresh"  # nothing was stored


def test_errors_reach_every_waiting_request_and_are_not_cached() -> None:
    cache = TTLCache(60)
    started = threading.Event()

    def failing() -> str:
        started.set()
        time.sleep(0.05)
        raise ValueError("db down")

    errors: list[BaseException] = []

    def call() -> None:
        try:
            cache.get_or_set("k", failing)
        except ValueError as exc:
            errors.append(exc)

    first = threading.Thread(target=call)
    first.start()
    started.wait(1)
    second = threading.Thread(target=call)
    second.start()
    first.join()
    second.join()
    assert len(errors) == 2
    assert cache.get_or_set("k", lambda: "ok") == "ok"


def test_too_many_computations_at_once_overload() -> None:
    cache = TTLCache(60, max_computations=1, wait_seconds=0.05)
    hold = threading.Event()
    started = threading.Event()

    def slow() -> str:
        started.set()
        hold.wait(1)
        return "v"

    t = threading.Thread(target=cache.get_or_set, args=("a", slow))
    t.start()
    started.wait(1)
    with pytest.raises(Overloaded):  # a different key: no free slot within wait_seconds
        cache.get_or_set("b", lambda: "w")
    hold.set()
    t.join()
    assert cache.get_or_set("b", lambda: "w") == "w"  # free again
