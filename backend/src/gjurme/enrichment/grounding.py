"""Hallucination guard for extracted entities.

An entity is *grounded* when its name tokens (≥ 3 characters) match tokens of the source text by
a shared prefix — **all** tokens for persons (a name must never be completed from the model's
world knowledge), at least **half** of them for organizations and locations (institution names
are legitimately normalized, e.g. "Kuvendi" → "Kuvendi i Kosovës"). Prefix matching (rather
than equality) is needed because Albanian is inflected: the model is asked to return the
nominative form "Prishtina" while the headline says "Prishtinës"; both share the prefix "prisht".
Short names inflect beyond a 5-letter prefix ("Kina" / "Kinën"), so a shared stem of ≥ 3 letters
also counts when both remainders are Albanian case endings. Matching is diacritic-insensitive.

Entities that fail the check are dropped and counted, never silently kept: this catches names the
model "knows" but that the article never mentions (e.g. adding a prime minister's first name, or
inventing the minister of an unnamed ministry).
"""

from __future__ import annotations

import re

from gjurme.enrichment.schema import EntityOut
from gjurme.ingestion.normalize import fold

_TOKEN = re.compile(r"[0-9a-z]+")
MIN_TOKEN = 3
PREFIX = 5
MIN_STEM = 3
# Albanian case/definiteness endings (diacritics folded: ë→e). Short names change more than a
# 5-letter prefix can absorb: Kin|a ~ Kin|ën, Hag|a ~ Hag|ë, Xhak|a ~ Xhak|ës, Zvic|ra ~ Zvic|ër.
# A shorter shared stem is accepted only when BOTH leftovers are such endings.
_ENDINGS = frozenset(
    {
        "",
        "a",
        "e",
        "i",
        "u",
        "n",
        "s",
        "t",
        "en",
        "es",
        "et",
        "in",
        "it",
        "is",
        "ut",
        "un",
        "us",
        "ra",
        "re",
        "ri",
        "er",
        "ja",
        "je",
        "ve",
        "ne",
        "se",
        "te",
        "ave",
        "eve",
    }
)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(fold(text))


def _inflected_match(name_token: str, text_token: str) -> bool:
    common = 0
    for a, b in zip(name_token, text_token, strict=False):
        if a != b:
            break
        common += 1
    return (
        common >= MIN_STEM and name_token[common:] in _ENDINGS and text_token[common:] in _ENDINGS
    )


def _token_matches(name_token: str, text_tokens: set[str], text_prefixes: set[str]) -> bool:
    if name_token in text_tokens:
        return True
    if len(name_token) >= PREFIX and name_token[:PREFIX] in text_prefixes:
        return True
    return any(_inflected_match(name_token, t) for t in text_tokens)


def ground_entities(
    entities: list[EntityOut], source_text: str
) -> tuple[list[EntityOut], list[EntityOut]]:
    text_tokens = set(_tokens(source_text))
    text_prefixes = {t[:PREFIX] for t in text_tokens if len(t) >= PREFIX}
    kept: list[EntityOut] = []
    dropped: list[EntityOut] = []
    for ent in entities:
        name_tokens = [t for t in _tokens(ent.name) if len(t) >= MIN_TOKEN]
        if not name_tokens:
            # Short acronyms ("BE", "OK", "EU"): require an exact token match.
            short = _tokens(ent.name)
            grounded = bool(short) and all(t in text_tokens for t in short)
        else:
            hits = sum(_token_matches(t, text_tokens, text_prefixes) for t in name_tokens)
            grounded = (
                hits == len(name_tokens) if ent.type == "person" else (hits * 2 >= len(name_tokens))
            )
        (kept if grounded else dropped).append(ent)
    return kept, dropped
