"""The real Anthropic SDK against a local server speaking the Messages API wire format.

No API key or network needed: this verifies what we *send* (model, cached system prompt,
structured-output schema, thinking disabled) and how we *interpret* what comes back (usage and
cost, request id, refusals, truncation, 401/404 → fatal, 529 → retried then retryable failure).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from gjurme.enrichment.pricing import cost_usd
from gjurme.enrichment.prompt import SYSTEM_PROMPT
from gjurme.enrichment.providers import AnthropicProvider, LLMError
from gjurme.enrichment.schema import OUTPUT_JSON_SCHEMA, parse_output

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


class FakeAnthropic(BaseHTTPRequestHandler):
    script: list[tuple[int, dict[str, Any], dict[str, str]]] = []
    requests: list[dict[str, Any]] = []
    headers_seen: list[dict[str, str]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", 0))
        FakeAnthropic.requests.append(json.loads(self.rfile.read(length)))
        FakeAnthropic.headers_seen.append({k.lower(): v for k, v in self.headers.items()})
        status, body, headers = FakeAnthropic.script.pop(0)
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture
def server() -> Iterator[str]:
    FakeAnthropic.script, FakeAnthropic.requests, FakeAnthropic.headers_seen = [], [], []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeAnthropic)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def message(text: str, stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 320,
            "output_tokens": 210,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 1450,
        },
    }


def provider(base_url: str, model: str = "claude-sonnet-5", retries: int = 0) -> AnthropicProvider:
    return AnthropicProvider(
        api_key="sk-test",
        model=model,
        max_output_tokens=1500,
        timeout_seconds=5,
        max_retries=retries,
        base_url=base_url,
    )


def test_request_shape_and_success(server: str) -> None:
    FakeAnthropic.script = [(200, message(json.dumps(OUTPUT)), {"request-id": "req_123"})]
    result = provider(server).complete(SYSTEM_PROMPT, "<article>x</article>", OUTPUT_JSON_SCHEMA)

    sent = FakeAnthropic.requests[0]
    assert sent["model"] == "claude-sonnet-5"
    assert sent["max_tokens"] == 1500
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent["system"][0]["text"] == SYSTEM_PROMPT
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": OUTPUT_JSON_SCHEMA}
    assert sent["thinking"] == {"type": "disabled"}
    assert sent["messages"] == [{"role": "user", "content": "<article>x</article>"}]
    assert FakeAnthropic.headers_seen[0]["x-api-key"] == "sk-test"

    assert result.request_id == "req_123"
    assert result.usage.cache_read_tokens == 1450 and result.usage.output_tokens == 210
    out, _ = parse_output(result.text)
    assert out.entities[0].name == "Qeveria e Kosovës"
    assert float(cost_usd("claude-sonnet-5", result.usage)) == pytest.approx(0.00303, abs=1e-5)


def test_opus_5_5_uses_low_effort_instead_of_disabling_thinking(server: str) -> None:
    FakeAnthropic.script = [(200, message(json.dumps(OUTPUT)), {})]
    provider(server, model="claude-opus-5-5").complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    sent = FakeAnthropic.requests[0]
    assert "thinking" not in sent and sent["output_config"]["effort"] == "low"


def test_refusal_is_not_retryable(server: str) -> None:
    FakeAnthropic.script = [(200, message("", stop_reason="refusal"), {})]
    with pytest.raises(LLMError) as err:
        provider(server).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.kind == "refused" and not err.value.retryable
    assert err.value.usage.input_tokens == 320  # still billed → still tracked


def test_truncated_output(server: str) -> None:
    FakeAnthropic.script = [(200, message('{"language": "sq"', stop_reason="max_tokens"), {})]
    with pytest.raises(LLMError) as err:
        provider(server).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.kind == "truncated" and err.value.raw_text == '{"language": "sq"'


@pytest.mark.parametrize(("status", "kind"), [(401, "auth"), (403, "auth"), (404, "not_found")])
def test_configuration_errors_are_fatal(server: str, status: int, kind: str) -> None:
    FakeAnthropic.script = [
        (status, {"type": "error", "error": {"type": "x", "message": "no"}}, {})
    ]
    with pytest.raises(LLMError) as err:
        provider(server).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.kind == kind and err.value.fatal


def test_bad_request_not_retryable_not_fatal(server: str) -> None:
    FakeAnthropic.script = [
        (400, {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}, {})
    ]
    with pytest.raises(LLMError) as err:
        provider(server).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.kind == "bad_request" and not err.value.retryable and not err.value.fatal


def test_overloaded_is_retried_by_sdk_then_succeeds(server: str) -> None:
    overloaded = (
        529,
        {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
        {"retry-after-ms": "10"},
    )
    FakeAnthropic.script = [overloaded, (200, message(json.dumps(OUTPUT)), {})]
    result = provider(server, retries=2).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert len(FakeAnthropic.requests) == 2 and result.text


def test_overloaded_exhausts_retries(server: str) -> None:
    overloaded = (
        529,
        {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
        {"retry-after-ms": "10"},
    )
    FakeAnthropic.script = [overloaded, overloaded]
    with pytest.raises(LLMError) as err:
        provider(server, retries=1).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.kind == "overloaded" and err.value.retryable


def test_rate_limit(server: str) -> None:
    FakeAnthropic.script = [
        (
            429,
            {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}},
            {"retry-after-ms": "10"},
        )
    ]
    with pytest.raises(LLMError) as err:
        provider(server).complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.kind == "rate_limited" and err.value.retryable


def test_connection_failure() -> None:
    with pytest.raises(LLMError) as err:
        provider("http://127.0.0.1:9").complete(SYSTEM_PROMPT, "u", OUTPUT_JSON_SCHEMA)
    assert err.value.kind in ("connection", "timeout") and err.value.retryable
