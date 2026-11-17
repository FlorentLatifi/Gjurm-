"""A free tier's daily quota spread over the day (enrichment/quota.py), and how a 429 says which
limit it is about. The database side is in tests/integration/test_enrichment.py."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import httpx
import pytest
from pydantic import ValidationError

from gjurme.config import Settings
from gjurme.enrichment.prompt import SYSTEM_PROMPT
from gjurme.enrichment.providers import LLMError, rate_limit_scope
from gjurme.enrichment.quota import QuotaConfig, next_reset, quota_day, run_share, runs_left
from gjurme.enrichment.schema import OUTPUT_JSON_SCHEMA
from tests.unit.test_openai_compatible import Recorder, make

PT = "America/Los_Angeles"


# --- the share of one run ---------------------------------------------------------------------
def test_the_quota_is_spread_evenly_over_the_runs_left() -> None:
    assert run_share(used=0, daily_limit=250, runs_left=48) == 6  # ⌈250 / 48⌉
    assert run_share(used=200, daily_limit=250, runs_left=10) == 5
    # a run that was skipped leaves its share to the runs after it
    assert run_share(used=0, daily_limit=250, runs_left=24) == 11


def test_a_whole_day_of_runs_stays_within_the_quota() -> None:
    used, sent = 0, []
    for left in range(48, 0, -1):
        share = run_share(used=used, daily_limit=250, runs_left=left)
        assert share is not None or left == 1
        n = min(share or 250 - used, 250 - used)  # the last run sends what is left
        sent.append(n)
        used += n
    assert used == 250
    assert max(sent) - min(sent[:-1]) <= 1  # the evening gets as much as the morning
    assert sent[-12:] != [0] * 12  # the last six hours before the reset still get a model


def test_at_least_one_request_once_the_limit_is_reached() -> None:
    """So that a raised limit shows, and the newest article still gets a model."""
    assert run_share(used=250, daily_limit=250, runs_left=10) == 1
    assert run_share(used=300, daily_limit=250, runs_left=10) == 1


def test_the_last_run_before_the_reset_takes_what_is_left() -> None:
    assert run_share(used=100, daily_limit=250, runs_left=1) is None
    assert run_share(used=100, daily_limit=250, runs_left=1, max_per_run=20) == 20


def test_unknown_limit_means_no_pacing_unless_a_ceiling_is_set() -> None:
    assert run_share(used=0, daily_limit=None, runs_left=40) is None
    assert run_share(used=0, daily_limit=None, runs_left=40, max_per_run=8) == 8
    assert run_share(used=0, daily_limit=250, runs_left=4, max_per_run=8) == 8  # 63 → 8


def test_the_day_follows_the_providers_time_zone() -> None:
    # 07:30 UTC in November is 23:30 the day before in California (PST, UTC−8)
    now = datetime(2026, 11, 15, 7, 30, tzinfo=UTC)
    assert quota_day(now, PT) == date(2026, 11, 14)
    assert quota_day(now, "UTC") == date(2026, 11, 15)
    reset = next_reset(date(2026, 11, 14), PT)
    assert reset == datetime(2026, 11, 15, 8, 0, tzinfo=UTC)
    assert runs_left(now, reset, 30) == 1  # the last run of Gemini's day
    assert (
        runs_left(datetime(2026, 11, 15, 19, 0, tzinfo=UTC), next_reset(date(2026, 11, 15), PT), 30)
        == 26
    )
    # in summer (PDT, UTC−7) the reset is an hour earlier in UTC
    assert next_reset(date(2026, 7, 1), PT) == datetime(2026, 7, 2, 7, 0, tzinfo=UTC)


def test_each_model_has_its_own_quota_settings() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        llm_requests_per_day=250,
        llm_max_requests_per_run=12,
        llm_fallback_requests_per_day=60,
        scheduler_interval_minutes=30,
    )
    assert QuotaConfig.for_model(settings) == QuotaConfig(250, 12, PT, 30)
    assert QuotaConfig.for_model(settings, fallback=True) == QuotaConfig(60, 0, "UTC", 30)


def test_an_unknown_time_zone_is_refused() -> None:
    with pytest.raises(ValidationError, match="unknown time zone"):
        Settings(_env_file=None, llm_quota_timezone="Pacific Time")  # type: ignore[call-arg]


# --- which limit a 429 is about ---------------------------------------------------------------
GEMINI_DAY = json.dumps(
    [
        {
            "error": {
                "code": 429,
                "message": "You exceeded your current quota, please check your plan and billing "
                "details. For more information on this error, head to: "
                "https://ai.google.dev/gemini-api/docs/rate-limits.\n* Quota exceeded for "
                "metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, "
                "limit: 250, model: gemini-2.5-flash-lite\nPlease retry in 41.2s.",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaMetric": "generativelanguage.googleapis.com/"
                                "generate_content_free_tier_requests",
                                "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                            }
                        ],
                    },
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "41s"},
                ],
            }
        }
    ]
)
GEMINI_MINUTE = GEMINI_DAY.replace("PerDay", "PerMinute").replace("limit: 250", "limit: 15")
GROQ_TPM = (
    "Rate limit reached for model `openai/gpt-oss-120b` in organization `org_x` service tier "
    "`on_demand` on tokens per minute (TPM): Limit 8000, Used 6449, Requested 3100. Please try "
    "again in 11.5s. Need more tokens? Upgrade to Dev Tier today."
)
GROQ_TPD = GROQ_TPM.replace("tokens per minute (TPM)", "tokens per day (TPD)").replace(
    "8000", "200000"
)


@pytest.mark.parametrize(
    ("text", "retry_after", "scope"),
    [
        (GEMINI_DAY, None, "day"),
        (GEMINI_MINUTE, None, "minute"),
        (GROQ_TPD, "1800", "day"),
        (GROQ_TPM, "12", "minute"),
        (
            "This request would exceed your organization's rate limit of 50,000 input tokens per "
            "minute.",
            None,
            "minute",
        ),
        ("quota", "3600", "day"),  # a wait this long is no per-minute limit
        ("quota", "30", None),
        ("Too Many Requests", None, None),
    ],
)
def test_a_429_says_which_limit_it_is(text: str, retry_after: str | None, scope: str) -> None:
    assert rate_limit_scope(text, retry_after) == scope


def test_the_whole_answer_is_read_not_the_shortened_message() -> None:
    """Gemini names the daily quota at the end of a long answer, after the 300 characters the
    error message keeps; a daily limit is not retried, a per-minute one is."""
    sleeps: list[float] = []
    endpoint = Recorder(httpx.Response(429, text=GEMINI_DAY))
    with pytest.raises(LLMError) as err:
        make(endpoint, sleeps=sleeps).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert "PerDay" not in str(err.value)
    assert (err.value.kind, err.value.limit_scope) == ("rate_limited", "day")
    assert len(endpoint.requests) == 1 and sleeps == []

    endpoint = Recorder(*(httpx.Response(429, text=GEMINI_MINUTE) for _ in range(3)))
    with pytest.raises(LLMError) as err:
        make(endpoint, sleeps=sleeps).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.limit_scope == "minute" and len(endpoint.requests) == 3
