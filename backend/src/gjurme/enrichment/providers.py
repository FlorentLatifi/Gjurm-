"""LLM providers behind a small protocol.

``AnthropicProvider`` is the production implementation (official ``anthropic`` SDK, JSON-schema
structured outputs, prompt caching). ``FakeProvider`` is a deterministic, zero-cost heuristic used
by tests, local development and demo data; production refuses it unless explicitly allowed.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from gjurme.enrichment.pricing import Usage
from gjurme.ingestion.normalize import fold


class LLMError(Exception):
    """A failed LLM call.

    ``kind`` classifies the failure for retry/circuit-breaker decisions:
    timeout, rate_limited, overloaded, server_error, connection → retryable;
    refused, bad_request → not retryable for this article;
    auth, not_found → fatal for the whole stage (configuration problem).
    """

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        retryable: bool,
        fatal: bool = False,
        usage: Usage | None = None,
        raw_text: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.retryable = retryable
        self.fatal = fatal
        self.usage = usage or Usage()
        self.raw_text = raw_text
        self.request_id = request_id


@dataclass(frozen=True, slots=True)
class LLMResult:
    text: str
    model: str
    usage: Usage
    latency_ms: int
    request_id: str | None = None
    stop_reason: str | None = None


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult: ...


# =============================================================================================
# Anthropic
# =============================================================================================
def _thinking_kwargs(model: str) -> dict[str, Any]:
    """Keep extraction cheap: no extended thinking.

    * Sonnet 5 / Opus 5 / 4.x accept ``thinking: {type: disabled}``.
    * Opus 5.5 and the Fable/Mythos tier cannot disable thinking (400) — use the lowest effort.
    * Haiku 4.5 does not think unless asked.
    """
    if model.startswith("claude-haiku"):
        return {}
    if model.startswith(("claude-opus-5-5", "claude-fable", "claude-mythos")):
        return {"effort": "low"}
    return {"thinking": {"type": "disabled"}}


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_output_tokens: int,
        timeout_seconds: float,
        max_retries: int,
        base_url: str = "https://api.anthropic.com",
    ) -> None:
        # base_url is passed explicitly so an ambient ANTHROPIC_BASE_URL in the environment can
        # never silently redirect production traffic.
        self._client = anthropic.Anthropic(
            api_key=api_key, base_url=base_url, timeout=timeout_seconds, max_retries=max_retries
        )
        self.model = model
        self._max_tokens = max_output_tokens

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        extra = _thinking_kwargs(self.model)
        if "effort" in extra:
            output_config["effort"] = extra.pop("effort")
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
            **extra,
        }
        started = time.monotonic()
        try:
            response = self._client.messages.create(**request)
        except anthropic.APITimeoutError as exc:
            raise LLMError("timeout", str(exc), retryable=True) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("connection", str(exc), retryable=True) from exc
        except anthropic.AuthenticationError as exc:
            raise LLMError("auth", exc.message, retryable=False, fatal=True) from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError("auth", exc.message, retryable=False, fatal=True) from exc
        except anthropic.NotFoundError as exc:
            raise LLMError("not_found", exc.message, retryable=False, fatal=True) from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("rate_limited", exc.message, retryable=True) from exc
        except anthropic.BadRequestError as exc:
            raise LLMError("bad_request", exc.message, retryable=False) from exc
        except anthropic.APIStatusError as exc:
            kind = "overloaded" if exc.status_code == 529 else "server_error"
            raise LLMError(
                kind, f"HTTP {exc.status_code}: {exc.message}", retryable=exc.status_code >= 500
            ) from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        raw_usage = response.usage
        usage = Usage(
            input_tokens=raw_usage.input_tokens or 0,
            output_tokens=raw_usage.output_tokens or 0,
            cache_read_tokens=getattr(raw_usage, "cache_read_input_tokens", None) or 0,
            cache_write_tokens=getattr(raw_usage, "cache_creation_input_tokens", None) or 0,
        )
        request_id = getattr(response, "_request_id", None)
        text = "".join(block.text for block in response.content if block.type == "text")
        if response.stop_reason == "refusal":
            raise LLMError(
                "refused",
                "model declined to analyse this item",
                retryable=False,
                usage=usage,
                raw_text=text,
                request_id=request_id,
            )
        if response.stop_reason == "max_tokens":
            raise LLMError(
                "truncated",
                "output hit max_tokens",
                retryable=True,
                usage=usage,
                raw_text=text,
                request_id=request_id,
            )
        return LLMResult(
            text=text,
            model=response.model or self.model,
            usage=usage,
            latency_ms=latency_ms,
            request_id=request_id,
            stop_reason=response.stop_reason,
        )


# =============================================================================================
# Fake (deterministic heuristic) — tests, local dev, demo data
# =============================================================================================
_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "kosovo_serbia": ("serbi", "beograd", "vucic", "dialog", "veri", "mitrovic", "zubin potok"),
    "elections": ("zgjedhj", "votim", "kandidat", "kek", "fushat"),
    "eu_integration": ("be-", "bashkimi evropian", "brukse", "vizat", "anetaresim", "nato"),
    "crime_justice": (
        "arrest",
        "polici",
        "gjykat",
        "prokurori",
        "vras",
        "korrupsion",
        "dënim",
        "denim",
        "aktakuz",
        "hetim",
    ),
    "economy": (
        "ekonomi",
        "çmim",
        "cmim",
        "buxhet",
        "tatim",
        "invest",
        "biznes",
        "euro",
        "inflacion",
        "eksport",
    ),
    "sports": ("futboll", "ndeshj", "kampion", "gol", "sport", "olimpi", "trajner"),
    "health": ("shëndet", "shendet", "spital", "mjek", "sëmund", "semund", "vaksin"),
    "education": ("shkoll", "universitet", "student", "arsim", "mësim", "mesim"),
    "accidents_disasters": (
        "aksident",
        "zjarr",
        "vërshim",
        "vershim",
        "tërmet",
        "termet",
        "vdiq",
        "plagos",
    ),
    "environment_energy": ("ndotj", "energji", "rrym", "mjedis", "klim", "kek"),
    "culture_entertainment": (
        "film",
        "muzik",
        "koncert",
        "festival",
        "këngëtar",
        "kengetar",
        "art",
    ),
    "infrastructure_transport": ("rrug", "autostrad", "ndërtim", "ndertim", "trafik", "aeroport"),
    "diaspora": ("diaspor", "mërgat", "mergat", "emigr"),
    "technology_science": ("teknologj", "internet", "shkenc", "aplikacion", "inteligjenc"),
    "security_defense": ("kfor", "ushtri", "fsk", "siguri", "mbrojtj"),
    "international": ("sh.b.a", "shba", "rusi", "ukrain", "gjermani", "ambasador"),
    "politics": (
        "qeveri",
        "kuvend",
        "ministr",
        "kryeministr",
        "president",
        "parti",
        "opozit",
        "deputet",
    ),
}
_NEGATIVE = (
    "vras",
    "vdiq",
    "aksident",
    "arrest",
    "zjarr",
    "krizë",
    "kriz",
    "sulm",
    "plagos",
    "tension",
    "protest",
    "akuz",
    "dënim",
    "korrupsion",
    "humb",
    "rrezik",
)
_POSITIVE = (
    "fitor",
    "fiton",
    "marrëveshj",
    "marreveshj",
    "sukses",
    "rritje",
    "hap",
    "invest",
    "urim",
    "çmim nderi",
    "kampion",
    "rekord",
    "përmirës",
    "permires",
)
_COUNTRY_HINTS = {
    "kosov": "XK",
    "shqipëri": "AL",
    "shqiperi": "AL",
    "serbi": "RS",
    "maqedoni": "MK",
    "mal të zi": "ME",
    "gjermani": "DE",
    "zvicër": "CH",
    "shba": "US",
    "ukrain": "UA",
    "rusi": "RU",
    "tiran": "AL",
    "prishtin": "XK",
    "beograd": "RS",
}
_LOCATION_HINTS = (
    "prishtin",
    "tiran",
    "prizren",
    "mitrovic",
    "pej",
    "gjakov",
    "ferizaj",
    "gjilan",
    "durr",
    "shkod",
    "vlor",
    "beograd",
    "shkup",
    "kosov",
    "shqipëri",
    "serbi",
    "maqedoni",
)
_ORG_HINTS = (
    "kuvendi",
    "qeveria",
    "policia",
    "gjykata",
    "prokuroria",
    "ministria",
    "nato",
    "kfor",
    "be",
    "ok",
    "fc",
    "klubi",
    "partia",
    "lëvizja",
    "levizja",
    "ldk",
    "pdk",
    "aak",
    "vetëvendosje",
    "vetevendosje",
    "banka",
    "universiteti",
    "komuna",
)
_NAME_SEQ = re.compile(r"\b([A-ZÇË][\wçëÇË-]+(?:\s+(?:e|i|të)?\s*[A-ZÇË][\wçëÇË-]+){0,3})")
_SENTENCE_START_STOP = {
    "Në",
    "Ne",
    "Për",
    "Per",
    "Pas",
    "Me",
    "Nga",
    "Si",
    "Kjo",
    "Ky",
    "Ja",
    "Sot",
    "Dje",
    "The",
    "A",
    "An",
    "In",
    "On",
    "At",
}


@dataclass
class FakeProvider:
    """Keyword-heuristic 'LLM'. Deterministic; never calls the network; costs nothing."""

    model: str = "fake"
    name: str = "fake"
    fail_every: int = 0  # testing aid: make every Nth call fail
    _calls: int = field(default=0, init=False)

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        self._calls += 1
        if self.fail_every and self._calls % self.fail_every == 0:
            raise LLMError("server_error", "injected failure", retryable=True)
        headline = _between(user, "<headline>", "</headline>")
        excerpt = _between(user, "<excerpt>", "</excerpt>")
        text = f"{headline}. {excerpt}"
        folded = fold(text)

        scores = {
            slug: sum(folded.count(fold(k)) for k in kws) for slug, kws in _TOPIC_KEYWORDS.items()
        }
        ranked = [s for s, v in sorted(scores.items(), key=lambda kv: -kv[1]) if v > 0]
        primary = ranked[0] if ranked else "other"
        neg = sum(folded.count(fold(k)) for k in _NEGATIVE)
        pos = sum(folded.count(fold(k)) for k in _POSITIVE)
        score = max(-0.9, min(0.9, 0.3 * (pos - neg)))
        label = "negative" if score < -0.15 else "positive" if score > 0.15 else "neutral"

        entities: list[dict[str, str]] = []
        for match in _NAME_SEQ.finditer(text):
            name = match.group(1).strip()
            first = name.split()[0]
            if first in _SENTENCE_START_STOP and len(name.split()) == 1:
                continue
            key = fold(name)
            if any(key.startswith(h) for h in _LOCATION_HINTS):
                etype = "location"
            elif any(key.split()[0] == h or key.startswith(h + " ") for h in _ORG_HINTS) or (
                name.isupper() and len(name) <= 6
            ):
                etype = "organization"
            elif len(name.split()) >= 2:
                etype = "person"
            else:
                continue
            if all(e["name"] != name for e in entities):
                entities.append({"name": name, "type": etype})
        countries = sorted({code for hint, code in _COUNTRY_HINTS.items() if fold(hint) in folded})
        output = {
            "language": "en" if " the " in f" {folded} " else "sq",
            "primary_topic": primary,
            "secondary_topics": ranked[1:3],
            "sentiment": label,
            "sentiment_score": round(score, 3),
            "event_type": "other",
            "summary_en": f"[demo heuristic] {headline}"[:380],
            "entities": entities[:8],
            "countries": countries[:4],
            "confidence": 0.3,
        }
        return LLMResult(
            text=json.dumps(output, ensure_ascii=False),
            model=self.model,
            usage=Usage(),
            latency_ms=1,
            request_id=None,
            stop_reason="end_turn",
        )


def _between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    j = text.find(end, i + len(start))
    if i < 0 or j < 0:
        return ""
    from html import unescape

    return unescape(text[i + len(start) : j]).strip()
