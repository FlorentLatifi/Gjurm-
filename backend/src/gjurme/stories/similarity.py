"""Pure text-similarity functions for story clustering (no database access).

Two articles belong to the same *story* when they report the same event. ADR-008 measured that
headline trigram similarity cannot tell this apart on Albanian news (paraphrases of one event
score lower than different events that share a place name), so clustering uses:

* **TF-IDF vectors** over headline + feed excerpt + extracted entities. Words are folded
  (ë → e), stopwords and outlet labels removed, and stemmed by truncating to six letters and
  dropping one Albanian case ending, which merges inflections (Prishtinë/Prishtinës/Prishtinën,
  Kuvendi/Kuvendit, Kurti/Kurtin/Kurtit). Rare words
  (names, places) weigh more than words every headline uses.
* **A shared event word**: the two sides must share at least one term that is not part of a
  person's name. A person new to the news has a rare (heavily weighted) name and appears in
  several unrelated stories at once ("X presents the programme", "X asks for a session");
  sharing only that name is not sharing an event.
* **Name guards**: when both sides name specific places, or both name people, most of them must
  be shared. "Aksident në Prizren" and "Aksident në Pejë" share almost every word but are
  different events; they score *higher* than most real paraphrases, so the guard is never
  skipped. Near-verbatim copies are linked by dedup layer L4 (``duplicate_of_id``) instead.

See docs/DECISIONS.md (ADR-020) for the thresholds and how to review them on real data.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from gjurme.ingestion.normalize import normalize_key
from gjurme.ingestion.processor import NOISE_TOKENS

STEM_LENGTH = 6
TITLE_WEIGHT = 2.0
EXCERPT_WEIGHT = 1.0
ENTITY_WEIGHT = 1.0
# Only the start of the excerpt describes the event; later sentences drift into background.
EXCERPT_MAX_WORDS = 40


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# Folded (no diacritics), at least three letters: shorter tokens are dropped anyway.
STOPWORDS = _words("""
    dhe per nga nje qe por kane kishte eshte jane ishte ishin tha thote pas para mbi nen deri
    edhe apo ose kete kesaj ketij kjo keto keta ata ato ajo saj tij tyre sot dje neser nese
    vetem shume tek tani pra cfare kur kush cila cili cilet mund duhet ndaj gjate prej rreth
    sipas lidhje mes midis pershkak drejt kunder perpara prapa brenda jashte sic ashtu keshtu
    atje ketu kemi jemi jeni jam nuk mos ndonje asnje gjithe cdo disa pak tjeter tjere tjera
    vete veten ate atij asaj atyre ketyre bere behet bene beri jep dha vit viti vitit vitin
    dite diten ore oren here heren lajm lajmi lajme sapo kryesore ende akoma ndersa megjithate
    prandaj sepse kurse prane
    the and for with from that this was were are has have had its into about than more
    after over says said will not but new out
""")

# Places too broad to identify an event (countries, regions, blocs), folded; compared as stems.
_BROAD_PLACE_WORDS = _words("""
    kosova kosove kosoves koseves kosoven kosovo shqiperi shqiperia shqiperise shqiperine
    shqiptar shqiptare albania serbi serbia serbise serbine serbie maqedoni maqedonia maqedonise
    macedonia evrope evropa evropes europe europa ballkan ballkani ballkanit balkan balkans
    rajon rajoni rajonit amerike amerika amerikes veri veriu veriut verior veriore
""")


# Albanian case and definiteness endings, folded (ë → e), longest first. Truncation alone misses
# short words: "Kurtin" / "Kurtit" / "Kurti" keep their endings within six letters.
SUFFIXES = ("it", "in", "is", "es", "en", "ut", "un", "us", "i", "u", "a", "e", "n", "s", "t")
MIN_ROOT = 3


def stem(token: str) -> str:
    """Truncate to six letters, then drop one ending: Kurti/Kurtin/Kurtit → kurt,
    Prizren/Prizrenit → prizr, Rama/Ramës → ram. Truncating first keeps long words apart
    (presidenti → presid, presioni → presio)."""
    if not token.isalpha():
        return token
    token = token[:STEM_LENGTH]
    for suffix in SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= MIN_ROOT:
            return token[: -len(suffix)]
    return token


def tokens(text: str | None, *, max_words: int | None = None) -> list[str]:
    """Folded, stopword-free, stemmed content tokens of ``text``."""
    if not text:
        return []
    words = normalize_key(text).split()
    if max_words is not None:
        words = words[:max_words]
    out: list[str] = []
    for w in words:
        if w.isdigit():
            if len(w) >= 2:
                out.append(w)
            continue
        if len(w) < 3 or w in STOPWORDS or w in NOISE_TOKENS:
            continue
        out.append(stem(w))
    return out


BROAD_PLACES = frozenset(stem(w) for w in _BROAD_PLACE_WORDS)


def name_stems(names: Iterable[str]) -> frozenset[str]:
    """Stems of the words of entity names, for overlap tests ("Osmani" ~ "Vjosa Osmani")."""
    out: set[str] = set()
    for name in names:
        for w in normalize_key(name).split():
            if len(w) >= 4 and w not in STOPWORDS:
                out.add(stem(w))
    return frozenset(out)


@dataclass(frozen=True, slots=True)
class Names:
    """Stems of the people, specific places and organisations an article (or story) names."""

    people: frozenset[str] = frozenset()
    places: frozenset[str] = frozenset()
    orgs: frozenset[str] = frozenset()

    def __or__(self, other: Names) -> Names:
        return Names(self.people | other.people, self.places | other.places, self.orgs | other.orgs)


@dataclass(slots=True)
class Doc:
    """One article as the clustering stage sees it."""

    id: int
    title: str
    excerpt: str | None = None
    people: Iterable[str] = ()
    places: Iterable[str] = ()
    other_entities: Iterable[str] = ()
    terms: dict[str, float] = field(init=False)
    names: Names = field(init=False)

    def __post_init__(self) -> None:
        terms: dict[str, float] = {}
        for t in set(tokens(self.title)):
            terms[t] = terms.get(t, 0.0) + TITLE_WEIGHT
        for t in set(tokens(self.excerpt, max_words=EXCERPT_MAX_WORDS)):
            terms[t] = terms.get(t, 0.0) + EXCERPT_WEIGHT
        entity_names = [*self.people, *self.places, *self.other_entities]
        for key in {"@" + normalize_key(n) for n in entity_names if normalize_key(n)}:
            terms[key] = terms.get(key, 0.0) + ENTITY_WEIGHT
        self.terms = terms
        self.names = Names(
            name_stems(self.people),
            name_stems(self.places) - BROAD_PLACES,
            name_stems(self.other_entities) - BROAD_PLACES,
        )


def idf_table(docs: Iterable[Doc]) -> dict[str, float]:
    """Smoothed inverse document frequency: ln((N + 1) / (df + 1)) + 1."""
    df: Counter[str] = Counter()
    n = 0
    for d in docs:
        n += 1
        df.update(d.terms.keys())
    return {term: math.log((n + 1) / (count + 1)) + 1.0 for term, count in df.items()}


def vector(doc: Doc, idf: Mapping[str, float]) -> dict[str, float]:
    """L2-normalized TF-IDF vector. Unknown terms get the IDF of a term seen once."""
    default = max(idf.values(), default=1.0)
    v = {t: w * idf.get(t, default) for t, w in doc.terms.items()}
    norm = math.sqrt(sum(x * x for x in v.values()))
    return {t: x / norm for t, x in v.items()} if norm else {}


def cosine(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def shares_event_term(
    terms: Iterable[str], other: Mapping[str, float], people: frozenset[str]
) -> bool:
    """True when ``terms`` and ``other`` share a term that is not (part of) a person's name."""
    return any(t in other and t not in people and not t.startswith("@") for t in terms)


def _weak_overlap(a: frozenset[str], b: frozenset[str]) -> bool:
    """Both non-empty and at most half of the smaller set is shared (overlap coefficient)."""
    return bool(a and b) and len(a & b) <= 0.5 * min(len(a), len(b))


def conflict_reason(a: Names, b: Names) -> str | None:
    """Which name guard separates ``a`` and ``b`` ("places", "people", "names") or None."""
    if _weak_overlap(a.places, b.places):
        return "places"
    if _weak_overlap(a.people, b.people):
        return "people"
    a_all = a.people | a.places | a.orgs
    b_all = b.people | b.places | b.orgs
    if len(a_all) >= 2 and len(b_all) >= 2 and _weak_overlap(a_all, b_all):
        return "names"
    return None


def names_conflict(a: Names, b: Names) -> bool:
    """True when both sides name specific places (or people) and mostly different ones.

    Overlap is measured on name-word stems, so "Osmani" matches "Vjosa Osmani", and relative to
    the smaller side, so one outlet naming an extra person does not split a story. "Prizren +
    Prishtinë" vs "Pejë + Prishtinë" (two accidents on two roads) conflicts: half is shared.
    Entity types are noisy (a person typed as a place, "Spitali i Pejës" as an organisation), so
    when both sides name at least two name words of any type, those combined sets must overlap
    as well.
    """
    return conflict_reason(a, b) is not None
