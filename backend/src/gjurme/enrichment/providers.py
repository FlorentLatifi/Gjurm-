"""LLM providers behind a small protocol.

``AnthropicProvider`` is the production implementation (official ``anthropic`` SDK, JSON-schema
structured outputs, prompt caching). ``OpenAICompatibleProvider`` speaks the widely copied
``/chat/completions`` format, which covers free options: a local model served by Ollama or
llama.cpp, and the free tiers of hosted APIs. ``FakeProvider`` is a deterministic, zero-cost
heuristic used by tests, local development and demo data; production refuses it unless explicitly
allowed.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import anthropic
import httpx

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
# OpenAI-compatible chat completions — local models (Ollama, llama.cpp) and free hosted tiers
# =============================================================================================
ResponseFormat = Literal["json_schema", "json_object", "prompt"]

# Reasoning models served locally (Qwen3, DeepSeek-R1 …) may prefix the answer with their notes.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_RETRY_AFTER_CAP_SECONDS = 60.0


def _schema_instruction(schema: dict[str, Any]) -> str:
    return (
        "\n\nRespond with one JSON object and nothing else. It must match this JSON schema:\n"
        + json.dumps(schema, ensure_ascii=False)
    )


class OpenAICompatibleProvider:
    """``POST {base_url}/chat/completions`` with structured output where the server supports it.

    ``response_format`` picks how the JSON shape is enforced, because servers differ:
    ``json_schema`` (constrained decoding: OpenAI, Ollama, llama.cpp, most hosted APIs),
    ``json_object`` (valid JSON only; the schema goes in the prompt) or ``prompt`` (schema in the
    prompt, nothing enforced). Either way the output then goes through the same parse, repair,
    validation and grounding as Claude's.

    Free tiers limit requests per minute: ``requests_per_minute`` spaces calls across the worker
    threads, and 429/5xx/connection errors are retried with backoff (honouring ``Retry-After``).
    Temperature is 0 so that the same article gets the same analysis, which comparisons between
    outlets depend on.
    """

    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        max_output_tokens: int,
        timeout_seconds: float,
        max_retries: int,
        api_key: str | None = None,
        response_format: ResponseFormat = "json_schema",
        requests_per_minute: int = 0,
        transport: httpx.BaseTransport | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )
        self.model = model
        self._max_tokens = max_output_tokens
        self._max_retries = max_retries
        self._format = response_format
        self._interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self._next_slot = 0.0
        self._lock = threading.Lock()
        self._sleep = sleep

    def _wait_for_slot(self) -> None:
        if not self._interval:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
        if slot > now:
            self._sleep(slot - now)

    def _request_body(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "temperature": 0,
        }
        if self._format == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "article_analysis", "schema": schema, "strict": True},
            }
        else:
            system = system + _schema_instruction(schema)
            if self._format == "json_object":
                body["response_format"] = {"type": "json_object"}
        body["messages"] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return body

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        attempt = 0
        while True:
            self._wait_for_slot()
            try:
                response = self._client.post("/chat/completions", json=body)
            except httpx.TimeoutException as exc:
                error = LLMError("timeout", str(exc) or "request timed out", retryable=True)
                retry_after = None
            except httpx.TransportError as exc:
                error = LLMError("connection", str(exc) or type(exc).__name__, retryable=True)
                retry_after = None
            else:
                if response.status_code < 400:
                    return response
                error = _status_error(response)
                retry_after = _retry_after_seconds(response)
            if not error.retryable or attempt >= self._max_retries:
                raise error
            attempt += 1
            self._sleep(retry_after if retry_after is not None else min(2.0**attempt, 30.0))

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        started = time.monotonic()
        response = self._post(self._request_body(system, user, schema))
        latency_ms = int((time.monotonic() - started) * 1000)
        request_id = response.headers.get("x-request-id")
        try:
            data = response.json()
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMError(
                "bad_response",
                f"unexpected response shape: {response.text[:200]}",
                retryable=True,
                request_id=request_id,
            ) from exc
        request_id = request_id or data.get("id")
        usage = _openai_usage(data.get("usage"))
        text = _THINK_BLOCK.sub("", text).strip()
        finish = choice.get("finish_reason")
        if finish == "content_filter":
            raise LLMError(
                "refused",
                "model declined to analyse this item",
                retryable=False,
                usage=usage,
                raw_text=text,
                request_id=request_id,
            )
        if finish == "length":
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
            model=data.get("model") or self.model,
            usage=usage,
            latency_ms=latency_ms,
            request_id=request_id,
            stop_reason=finish,
        )


def _status_error(response: httpx.Response) -> LLMError:
    status = response.status_code
    try:
        detail = response.json().get("error", response.text)
        if isinstance(detail, dict):
            detail = detail.get("message", detail)
    except (ValueError, AttributeError):
        detail = response.text
    message = f"HTTP {status}: {str(detail)[:300]}"
    if status in (401, 403):
        return LLMError("auth", message, retryable=False, fatal=True)
    if status == 404:
        return LLMError("not_found", message, retryable=False, fatal=True)
    if status == 429:
        return LLMError("rate_limited", message, retryable=True)
    if status >= 500:
        return LLMError("server_error", message, retryable=True)
    return LLMError("bad_request", message, retryable=False)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return min(max(float(value), 0.0), _RETRY_AFTER_CAP_SECONDS) if value else None
    except ValueError:
        return None


def _openai_usage(raw: Any) -> Usage:
    if not isinstance(raw, dict):
        return Usage()
    prompt = int(raw.get("prompt_tokens") or 0)
    details = raw.get("prompt_tokens_details")
    cached = int(details.get("cached_tokens") or 0) if isinstance(details, dict) else 0
    return Usage(
        input_tokens=max(prompt - cached, 0),
        output_tokens=int(raw.get("completion_tokens") or 0),
        cache_read_tokens=cached,
    )


# =============================================================================================
# Fake (deterministic heuristic) — tests, local dev, demo data
# =============================================================================================
# Keyword stems (diacritics are folded before matching, so "shëndet" and "shendet" are the same).
# A stem matches at the start of a word ("polici" → "policia", "policisë"); a trailing "$" means
# a whole word ("moti$" must not match "motivim"). Order breaks ties: specific topics first.
_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "kosovo_serbia": (
        "serbi",
        "beograd",
        "vucic",
        "vuciq",
        "dialog",
        "veriu$",
        "verior",
        "mitrovic",
        "zubin potok",
        "zvecan",
        "leposavi",
        "banjsk",
        "radoiciq",
        "radoicic",
        "lista serbe",
        "listes serbe",
        "srpska",
    ),
    "elections": ("zgjedhj", "votim", "votues", "kandidat", "kqz$", "fushat", "zgjedhor"),
    "eu_integration": (
        "be-",
        "bashkimi evropian",
        "bashkimit evropian",
        "brukse",
        "vizat",
        "liberalizim",
        "anetaresim",
        "integrim",
        "komisioni evropian",
        "nato$",
    ),
    "crime_justice": (
        "arrest",
        "polici",
        "gjykat",
        "prokurori",
        "prokuror",
        "vras",
        "vrase",
        "korrupsion",
        "denim",
        "denu",
        "aktakuz",
        "akuz",
        "hetim",
        "vjedh",
        "drog",
        "burg",
        "krim",
        "fajesi",
        "mashtrim",
        "speciale",
        "apel",
    ),
    "security_defense": (
        "kfor",
        "ushtri",
        "ushtar",
        "fsk$",
        "siguri",
        "mbrojtj",
        "terror",
        "arme",
        "pentagon",
    ),
    "accidents_disasters": (
        "aksident",
        "zjarr",
        "vershim",
        "termet",
        "vdiq",
        "vdes",
        "plagos",
        "fatkeqesi",
        "shperthim",
        "humb jeten",
        "humbin jeten",
    ),
    "health": (
        "shendet",
        "spital",
        "mjek",
        "semund",
        "vaksin",
        "pacient",
        "farmac",
        "ilac",
        "kancer",
        "virus",
        "ibuprofen",
        "eutanazi",
    ),
    "education": (
        "shkoll",
        "universitet",
        "student",
        "arsim",
        "mesim",
        "nxenes",
        "mesues",
        "provim",
        "matur",
    ),
    "sports": (
        "futboll",
        "ndeshj",
        "kampion",
        "gol$",
        "golat",
        "sport",
        "olimpi",
        "trajner",
        "lojtar",
        "lojatar",
        "klub",
        "liga$",
        "ligat",
        "superlig",
        "basketboll",
        "tenis",
        "boks",
        "atlet",
        "transferim",
        "liverpool",
        "real madrid",
        "barcelon",
        "bayern",
        "juventus",
    ),
    "culture_entertainment": (
        "film",
        "muzik",
        "koncert",
        "festival",
        "kengetar",
        "kenge",
        "artist",
        "aktor",
        "teatr",
        "karikatur",
        "shfaqj",
        "premier",
        "youtube",
        "celebrit",
        "album",
        "libr",
        "roman$",
    ),
    "environment_energy": (
        "ndotj",
        "energji",
        "rrym",
        "mjedis",
        "klim",
        "kek$",
        "moti$",
        "motit$",
        "temperatur",
        "reshj",
        "shi$",
        "shiu$",
        "bore$",
        "vranes",
        "diell",
        "stuhi",
        "thatesir",
        "vale te nxehte",
    ),
    "infrastructure_transport": (
        "rrug",
        "autostrad",
        "ndertim",
        "trafik",
        "aeroport",
        "hekurud",
        "transport",
    ),
    "diaspora": ("diaspor", "mergat", "emigr", "migrant", "refugjat", "azil", "kurbet", "debuar"),
    "technology_science": (
        "teknologj",
        "internet",
        "shkenc",
        "aplikacion",
        "inteligjenc",
        "softuer",
        "haker",
        "hakim",
        "kibernet",
    ),
    "economy": (
        "ekonomi",
        "cmim",
        "buxhet",
        "tatim",
        "invest",
        "biznes",
        "euro$",
        "inflacion",
        "eksport",
        "import",
        "banka",
        "borxh",
        "tender",
        "pagat",
        "pagave",
        "prona",
        "pronat",
        "kompani",
    ),
    "international": (
        "sh.b.a",
        "shba",
        "rusi",
        "ukrain",
        "gjermani",
        "ambasador",
        "okb",
        "kina$",
        "kinen",
        "kines",
        "iran",
        "izrael",
        "gaza",
        "trump",
        "putin",
        "afgan",
        "taleban",
        "ngushtic",
        "hormuz",
        "evropa$",
    ),
    "politics": (
        "qeveri",
        "kuvend",
        "ministr",
        "kryeministr",
        "president",
        "parti",
        "opozit",
        "deputet",
        "pdk$",
        "ldk$",
        "vetevendosje",
        "aak$",
        "komun",
        "kryetar",
        "protest",
        "legjislatur",
    ),
}


def _stem_pattern(stems: tuple[str, ...]) -> re.Pattern[str]:
    parts = [
        re.escape(fold(st[:-1])) + r"(?![0-9a-z])" if st.endswith("$") else re.escape(fold(st))
        for st in stems
    ]
    return re.compile(r"(?<![0-9a-z])(?:" + "|".join(parts) + ")")


_TOPIC_PATTERNS = {slug: _stem_pattern(stems) for slug, stems in _TOPIC_KEYWORDS.items()}
_NEGATIVE = (
    "vras",
    "vdiq",
    "vdes",
    "vdekj",
    "aksident",
    "arrest",
    "zjarr",
    "kriz",
    "sulm",
    "plagos",
    "tension",
    "protest",
    "akuz",
    "denim",
    "denu",
    "korrupsion",
    "humb",
    "rrezik",
    "terror",
    "vjedh",
    "mashtrim",
    "debuar",
    "paralajmer",
    "eutanazi",
    "konfrontim",
    "presion",
)
_POSITIVE = (
    "fitor",
    "fiton",
    "marreveshj",
    "sukses",
    "rritje",
    "rihap",
    "invest",
    "urim",
    "cmim nderi",
    "kampion",
    "rekord",
    "permires",
    "krenar",
    "nderim",
)
_NEGATIVE_PATTERN = _stem_pattern(_NEGATIVE)
_POSITIVE_PATTERN = _stem_pattern(_POSITIVE)
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
_ROLE_PREFIXES = frozenset(
    {
        "trajneri",
        "ministri",
        "ministrja",
        "deputetja",
        "deputeti",
        "drejtori",
        "drejtoresha",
        "rektori",
        "kandidati",
        "negociatori",
        "ambasadori",
        "mesuesja",
        "themeluesja",
        "zedhenesi",
        "perzgjedhesi",
        "kryeministri",
        "presidentja",
        "presidenti",
        "kryetari",
        "zedhenesja",
    }
)
_ORG_HINTS = (
    "komisioni",
    "agjencia",
    "instituti",
    "kombetarja",
    "spitali",
    "bashkimi",
    "kompania",
    "festivali",
    "kqz",
    "kek",
    "opozita",
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
    "Sipas",
    "Edhe",
    "Por",
    "Kur",
    "Tani",
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

        scores = {slug: len(p.findall(folded)) for slug, p in _TOPIC_PATTERNS.items()}
        ranked = [s for s, v in sorted(scores.items(), key=lambda kv: -kv[1]) if v > 0]
        primary = ranked[0] if ranked else "other"
        neg = len(_NEGATIVE_PATTERN.findall(folded))
        pos = len(_POSITIVE_PATTERN.findall(folded))
        score = max(-0.9, min(0.9, 0.3 * (pos - neg)))
        label = "negative" if score < -0.15 else "positive" if score > 0.15 else "neutral"

        entities: list[dict[str, str]] = []
        for match in _NAME_SEQ.finditer(text):
            name = match.group(1).strip()
            words = name.split()
            # Drop leading roles ("Trajneri Blerta Zeqiri") and sentence-initial function words
            # ("Sipas Agjencisë …" = "according to the agency …").
            while words and (fold(words[0]) in _ROLE_PREFIXES or words[0] in _SENTENCE_START_STOP):
                words = words[1:]
            if not words:
                continue
            name = " ".join(words)
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
            "summary_en": f"[headline, no AI summary] {headline}"[:380],
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
