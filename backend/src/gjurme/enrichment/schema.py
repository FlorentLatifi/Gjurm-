"""Enrichment output contract.

Two layers of defence:

1. **JSON-schema structured output** sent to the model (``OUTPUT_JSON_SCHEMA``) — constrains the
   shape and the enum values at generation time. It deliberately uses only widely supported
   keywords (type/properties/required/enum/items/additionalProperties); numeric ranges and list
   limits are stated in descriptions and enforced by…
2. **Pydantic validation** (``EnrichmentOutput``) after a *repair* pass. Soft problems (too many
   list items, duplicate entities, lower-case country codes, a sentiment score contradicting its
   label) are repaired and recorded as quality flags; hard problems (invalid JSON, missing
   fields, values outside the controlled vocabularies) reject the output.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gjurme.ingestion.normalize import clean_text, normalize_key
from gjurme.taxonomy import ENTITY_TYPES, EVENT_TYPES, LANGUAGES, SENTIMENT_LABELS, TOPIC_SLUGS

SCHEMA_VERSION = "2026-09-24.1"

MAX_SECONDARY_TOPICS = 3
MAX_ENTITIES = 12
MAX_COUNTRIES = 6
MAX_SUMMARY_CHARS = 400

TopicSlug = Literal[TOPIC_SLUGS]  # type: ignore[valid-type]
EventType = Literal[EVENT_TYPES]  # type: ignore[valid-type]
EntityType = Literal[ENTITY_TYPES]  # type: ignore[valid-type]
Sentiment = Literal[SENTIMENT_LABELS]  # type: ignore[valid-type]
Language = Literal[LANGUAGES]  # type: ignore[valid-type]

_COUNTRY = re.compile(r"^[A-Z]{2}$")


class EntityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=120)
    type: EntityType


class EnrichmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language
    primary_topic: TopicSlug
    secondary_topics: list[TopicSlug] = Field(default_factory=list, max_length=MAX_SECONDARY_TOPICS)
    sentiment: Sentiment
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    event_type: EventType
    summary_en: str = Field(min_length=10, max_length=MAX_SUMMARY_CHARS)
    entities: list[EntityOut] = Field(default_factory=list, max_length=MAX_ENTITIES)
    countries: list[str] = Field(default_factory=list, max_length=MAX_COUNTRIES)
    confidence: float = Field(ge=0.0, le=1.0)


OUTPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "language",
        "primary_topic",
        "secondary_topics",
        "sentiment",
        "sentiment_score",
        "event_type",
        "summary_en",
        "entities",
        "countries",
        "confidence",
    ],
    "properties": {
        "language": {
            "type": "string",
            "enum": list(LANGUAGES),
            "description": "ISO 639-1 language of the article text.",
        },
        "primary_topic": {"type": "string", "enum": list(TOPIC_SLUGS)},
        "secondary_topics": {
            "type": "array",
            "items": {"type": "string", "enum": list(TOPIC_SLUGS)},
            "description": f"0-{MAX_SECONDARY_TOPICS} additional topics, excluding the primary.",
        },
        "sentiment": {"type": "string", "enum": list(SENTIMENT_LABELS)},
        "sentiment_score": {
            "type": "number",
            "description": "Tone from -1.0 (very negative) to 1.0 (very positive).",
        },
        "event_type": {"type": "string", "enum": list(EVENT_TYPES)},
        "summary_en": {
            "type": "string",
            "description": "One neutral English sentence, at most 35 words.",
        },
        "entities": {
            "type": "array",
            "description": f"At most {MAX_ENTITIES} named entities explicitly mentioned.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "type"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": list(ENTITY_TYPES)},
                },
            },
        },
        "countries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "ISO 3166-1 alpha-2 codes of countries the story is about (Kosovo=XK).",
        },
        "confidence": {
            "type": "number",
            "description": "Self-assessed confidence in this analysis, 0.0-1.0.",
        },
    },
}


class InvalidOutputError(ValueError):
    """The model's output could not be parsed or failed hard validation."""


_LABEL_SCORE_DEFAULT = {"negative": -0.5, "neutral": 0.0, "positive": 0.5}


def _repair(data: dict[str, Any], flags: dict[str, Any]) -> dict[str, Any]:
    """Fix *soft* violations in place and record what was changed."""
    primary = data.get("primary_topic")
    secondary = data.get("secondary_topics")
    if isinstance(secondary, list):
        seen: list[str] = []
        for slug in secondary:
            if isinstance(slug, str) and slug != primary and slug not in seen:
                seen.append(slug)
        if len(seen) != len(secondary):
            flags["secondary_topics_repaired"] = True
        data["secondary_topics"] = seen[:MAX_SECONDARY_TOPICS]

    entities = data.get("entities")
    if isinstance(entities, list):
        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for ent in entities:
            if not isinstance(ent, dict):
                continue
            name = clean_text(ent.get("name"))[:120]
            etype = ent.get("type")
            key = (str(etype), normalize_key(name))
            if len(name) >= 2 and key[1] and key not in unique:
                unique[key] = {"name": name, "type": etype}
        if len(unique) != len(entities):
            flags["entities_deduplicated"] = len(entities) - len(unique)
        data["entities"] = list(unique.values())[:MAX_ENTITIES]
        if len(unique) > MAX_ENTITIES:
            flags["entities_truncated"] = len(unique) - MAX_ENTITIES

    countries = data.get("countries")
    if isinstance(countries, list):
        cleaned: list[str] = []
        for code in countries:
            if isinstance(code, str):
                up = code.strip().upper()
                if _COUNTRY.match(up) and up not in cleaned:
                    cleaned.append(up)
        if len(cleaned) != len(countries):
            flags["countries_repaired"] = True
        data["countries"] = cleaned[:MAX_COUNTRIES]

    summary = data.get("summary_en")
    if isinstance(summary, str):
        summary = clean_text(summary)
        if len(summary) > MAX_SUMMARY_CHARS:
            summary = summary[: MAX_SUMMARY_CHARS - 1].rsplit(" ", 1)[0] + "…"
            flags["summary_truncated"] = True
        data["summary_en"] = summary

    for field_name in ("sentiment_score", "confidence"):
        value = data.get(field_name)
        if isinstance(value, int | float) and not isinstance(value, bool):
            lo = -1.0 if field_name == "sentiment_score" else 0.0
            clamped = max(lo, min(1.0, float(value)))
            if clamped != value:
                flags[f"{field_name}_clamped"] = True
            data[field_name] = clamped

    label, score = data.get("sentiment"), data.get("sentiment_score")
    if (
        isinstance(score, float)
        and label in _LABEL_SCORE_DEFAULT
        and (
            (label == "positive" and score < 0)
            or (label == "negative" and score > 0)
            or (label == "neutral" and abs(score) > 0.5)
        )
    ):
        # Trust the categorical judgement; a contradicting score is replaced, not averaged.
        data["sentiment_score"] = _LABEL_SCORE_DEFAULT[label]
        flags["sentiment_inconsistent"] = True
    return data


def parse_output(raw_text: str | None) -> tuple[EnrichmentOutput, dict[str, Any]]:
    """Parse, repair and validate model output. Raises ``InvalidOutputError``."""
    if not raw_text or not raw_text.strip():
        raise InvalidOutputError("empty response")
    text = raw_text.strip()
    if text.startswith("```"):  # tolerate fenced JSON from providers without structured output
        text = text.strip("`")
        text = text[text.find("{") :]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidOutputError(f"malformed JSON: {exc.msg} at pos {exc.pos}") from exc
    if not isinstance(data, dict):
        raise InvalidOutputError("top-level JSON value is not an object")
    flags: dict[str, Any] = {}
    data = _repair(data, flags)
    try:
        return EnrichmentOutput.model_validate(data), flags
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()[:5]
        )
        raise InvalidOutputError(f"schema validation failed: {details}") from exc
