"""OpenAI-compatible provider against a mocked ``/chat/completions`` endpoint.

No server, key or network: ``httpx.MockTransport`` answers the requests, so these tests check what
we *send* (model, temperature 0, structured-output format, auth only when a key is set) and how
we *interpret* the answer (usage, reasoning notes, truncation, refusals, 401/404 → fatal,
429/5xx → retried with backoff, request pacing for free tiers).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest

from gjurme.config import ConfigError, Settings
from gjurme.enrichment.pricing import (
    PRICES_PER_MTOK,
    Usage,
    cost_usd,
    price_for,
    register_price,
)
from gjurme.enrichment.prompt import SYSTEM_PROMPT
from gjurme.enrichment.providers import LLMError, OpenAICompatibleProvider
from gjurme.enrichment.schema import OUTPUT_JSON_SCHEMA, parse_output
from gjurme.enrichment.service import ConfigurationError, build_provider

OUTPUT = {
    "language": "sq",
    "primary_topic": "politics",
    "secondary_topics": [],
    "sentiment": "neutral",
    "sentiment_score": 0.0,
    "event_type": "statement",
    "summary_en": "The government announced a new budget proposal.",
    "entities": [{"name": "Qeveria e Kosovës", "type": "organization"}],
    "countries": ["XK"],
    "confidence": 0.8,
}


def completion(content: str, finish_reason: str = "stop", **extra: Any) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "gemma3:4b",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 1800, "completion_tokens": 240, "total_tokens": 2040},
        **extra,
    }


class Recorder:
    """A scripted endpoint: returns the queued responses in order and records the requests."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def body(self, i: int = 0) -> dict[str, Any]:
        return json.loads(self.requests[i].content)


def ok(content: str, finish_reason: str = "stop", **extra: Any) -> httpx.Response:
    return httpx.Response(200, json=completion(content, finish_reason, **extra))


def make(
    endpoint: Recorder,
    *,
    sleeps: list[float] | None = None,
    **kwargs: Any,
) -> OpenAICompatibleProvider:
    record: Callable[[float], None] = sleeps.append if sleeps is not None else lambda _s: None
    options: dict[str, Any] = {
        "base_url": "http://ollama:11434/v1/",
        "model": "gemma3:4b",
        "max_output_tokens": 1500,
        "timeout_seconds": 5,
        "max_retries": 2,
        **kwargs,
    }
    return OpenAICompatibleProvider(
        transport=httpx.MockTransport(endpoint), sleep=record, **options
    )


def test_request_shape_and_success() -> None:
    endpoint = Recorder(ok(json.dumps(OUTPUT)))
    result = make(endpoint).complete(SYSTEM_PROMPT, "<article>x</article>", OUTPUT_JSON_SCHEMA)

    request = endpoint.requests[0]
    assert str(request.url) == "http://ollama:11434/v1/chat/completions"
    assert "authorization" not in request.headers  # a local model needs no key
    sent = endpoint.body()
    assert sent["model"] == "gemma3:4b"
    assert sent["max_tokens"] == 1500
    assert sent["temperature"] == 0
    assert sent["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "article_analysis", "schema": OUTPUT_JSON_SCHEMA, "strict": True},
    }
    assert sent["messages"] == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "<article>x</article>"},
    ]

    assert result.request_id == "chatcmpl-test"
    assert result.stop_reason == "stop"
    assert result.usage.input_tokens == 1800 and result.usage.output_tokens == 240
    out, _ = parse_output(result.text)
    assert out.entities[0].name == "Qeveria e Kosovës"


def test_api_key_is_sent_as_bearer_token() -> None:
    endpoint = Recorder(ok(json.dumps(OUTPUT)))
    make(endpoint, api_key="free-tier-key").complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert endpoint.requests[0].headers["authorization"] == "Bearer free-tier-key"


@pytest.mark.parametrize(
    ("response_format", "expected"), [("json_object", {"type": "json_object"}), ("prompt", None)]
)
def test_schema_goes_in_the_prompt_without_json_schema_support(
    response_format: str, expected: dict[str, str] | None
) -> None:
    endpoint = Recorder(ok(json.dumps(OUTPUT)))
    make(endpoint, response_format=response_format).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    sent = endpoint.body()
    assert sent.get("response_format") == expected
    system = sent["messages"][0]["content"]
    assert system.startswith(SYSTEM_PROMPT)
    assert json.dumps(OUTPUT_JSON_SCHEMA, ensure_ascii=False) in system


def test_reasoning_notes_are_stripped() -> None:
    text = "<think>The headline is about the budget…</think>\n" + json.dumps(OUTPUT)
    result = make(Recorder(ok(text))).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert parse_output(result.text)[0].primary_topic == "politics"


def test_cached_prompt_tokens_are_counted_as_cache_reads() -> None:
    body = completion(json.dumps(OUTPUT))
    body["usage"]["prompt_tokens_details"] = {"cached_tokens": 1500}
    endpoint = Recorder(httpx.Response(200, json=body))
    result = make(endpoint).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert result.usage.input_tokens == 300 and result.usage.cache_read_tokens == 1500


def test_truncated_output_is_retryable() -> None:
    endpoint = Recorder(ok('{"language": "sq"', finish_reason="length"))
    with pytest.raises(LLMError) as err:
        make(endpoint).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.kind == "truncated" and err.value.retryable
    assert err.value.raw_text == '{"language": "sq"'
    assert err.value.usage.output_tokens == 240


def test_content_filter_is_a_refusal() -> None:
    endpoint = Recorder(ok("", finish_reason="content_filter"))
    with pytest.raises(LLMError) as err:
        make(endpoint).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.kind == "refused" and not err.value.retryable


@pytest.mark.parametrize(("status", "kind"), [(401, "auth"), (403, "auth"), (404, "not_found")])
def test_configuration_errors_are_fatal_and_not_retried(status: int, kind: str) -> None:
    endpoint = Recorder(httpx.Response(status, json={"error": {"message": "nope"}}))
    with pytest.raises(LLMError) as err:
        make(endpoint).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.kind == kind and err.value.fatal and not err.value.retryable
    assert "nope" in str(err.value)
    assert len(endpoint.requests) == 1


def test_bad_request_is_not_retried() -> None:
    endpoint = Recorder(httpx.Response(400, text="response_format not supported"))
    with pytest.raises(LLMError) as err:
        make(endpoint).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.kind == "bad_request" and not err.value.fatal
    assert "response_format not supported" in str(err.value)
    assert len(endpoint.requests) == 1


def test_rate_limit_waits_for_retry_after_then_succeeds() -> None:
    sleeps: list[float] = []
    endpoint = Recorder(
        httpx.Response(429, headers={"retry-after": "7"}, json={"error": "slow down"}),
        ok(json.dumps(OUTPUT)),
    )
    result = make(endpoint, sleeps=sleeps).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert result.text and sleeps == [7.0] and len(endpoint.requests) == 2


def test_retry_after_is_capped() -> None:
    sleeps: list[float] = []
    endpoint = Recorder(
        httpx.Response(429, headers={"retry-after": "86400"}), ok(json.dumps(OUTPUT))
    )
    make(endpoint, sleeps=sleeps).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert sleeps == [60.0]


def test_server_errors_back_off_then_give_up_as_retryable() -> None:
    sleeps: list[float] = []
    endpoint = Recorder(
        httpx.Response(503, text="loading model"),
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("slow CPU"),
    )
    with pytest.raises(LLMError) as err:
        make(endpoint, sleeps=sleeps).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.kind == "timeout" and err.value.retryable and not err.value.fatal
    assert sleeps == [2.0, 4.0] and len(endpoint.requests) == 3


def test_unexpected_response_shape() -> None:
    endpoint = Recorder(httpx.Response(200, json={"detail": "not a completion"}))
    with pytest.raises(LLMError) as err:
        make(endpoint, max_retries=0).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.kind == "bad_response" and err.value.retryable


def test_requests_are_paced_for_free_tier_limits() -> None:
    sleeps: list[float] = []
    endpoint = Recorder(*(ok(json.dumps(OUTPUT)) for _ in range(3)))
    provider = make(endpoint, sleeps=sleeps, requests_per_minute=30)
    for _ in range(3):
        provider.complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    # First call goes at once; each later one waits for its 2-second slot (the fake sleep does
    # not advance the clock, so the slots accumulate).
    assert len(sleeps) == 2
    assert sleeps[0] == pytest.approx(2.0, abs=0.2) and sleeps[1] == pytest.approx(4.0, abs=0.2)


# ---------------------------------------------------------------------------------------------
# Configuration and pricing
# ---------------------------------------------------------------------------------------------
def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_build_provider_for_a_local_model_prices_it_at_zero() -> None:
    provider = build_provider(
        settings(
            llm_provider="openai_compatible",
            llm_base_url="http://ollama:11434/v1",
            llm_model="test-local-model:1b",
        )
    )
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.name == "openai_compatible" and provider.model == "test-local-model:1b"
    assert price_for("test-local-model:1b") == (Decimal(0), Decimal(0))


def test_build_provider_requires_a_base_url() -> None:
    with pytest.raises(ConfigurationError, match="LLM_BASE_URL"):
        build_provider(settings(llm_provider="openai_compatible", llm_model="m"))


def test_deployed_config_requires_a_base_url() -> None:
    config = settings(
        gjurme_env="production",
        admin_api_token="x" * 40,
        database_url="postgresql+psycopg://gjurme:secret@db/gjurme",
        llm_provider="openai_compatible",
    )
    with pytest.raises(ConfigError, match="LLM_BASE_URL"):
        config.validate_for_env()


def test_paid_endpoint_price_is_used_for_the_budget() -> None:
    register_price("test-hosted-model", 0.5, 1.5)
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost_usd("test-hosted-model", usage) == Decimal("2.000000")


def test_known_model_prices_cannot_be_overridden() -> None:
    before = PRICES_PER_MTOK["claude-sonnet-5"]
    register_price("claude-sonnet-5", 0, 0)
    assert PRICES_PER_MTOK["claude-sonnet-5"] == before
