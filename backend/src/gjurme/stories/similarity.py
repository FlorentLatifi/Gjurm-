"""Pure text-similarity functions for story clustering (no database access).

Two articles belong to the same *story* when they report the same event. ADR-008 measured that
headline trigram similarity cannot tell this apart on Albanian news (paraphrases of one event
score lower than different events that share a place name), so clustering uses:

* **TF-IDF vectors** over headline + feed excerpt + extracted entities. Words are folded
  (ë → e), stopwords and outlet labels removed, and stemmed by truncating to six letters and
  dropping one Albanian case ending, which merges inflections (Prishtinë/Prishtinës/Prishtinën,
  Kuvendi/Kuvendit, Kurti/Kurtin/Kurtit). Rare words
  (names, places) weigh more than words every headline uses.
* **A shared event word**: the joining article's *headline* must share a term with the story
  that is not part of a person's name. A person new to the news has a rare (heavily weighted)
  name and appears in several unrelated stories at once ("X presents the programme", "X asks
  for a session"); sharing only that name — or a town named in passing in the excerpt — is not
  sharing an event.
* **Guards on the headlines' names and numbers**: when both headlines name specific places, or
  both carry numbers ("12 të vrarë", "14 për qind"), at least half of the smaller side must be
  shared; when both name people, at least one. "Aksident në Prizren" and "Aksident në Pejë"
  share almost every word but are different events; they score *higher* than most real
  paraphrases, so the guards are never skipped. Near-verbatim copies are linked by dedup layer
  L4 (``duplicate_of_id``) instead.

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
    """Stems of the people, specific places and organisations a headline (or story) names, and
    its numbers of two or more digits. ``words`` are all the headline's terms: a name the
    analysis found in one headline counts for another headline that contains it too."""

    people: frozenset[str] = frozenset()
    places: frozenset[str] = frozenset()
    orgs: frozenset[str] = frozenset()
    numbers: frozenset[str] = frozenset()
    words: frozenset[str] = frozenset()

    def __or__(self, other: Names) -> Names:
        return Names(
            self.people | other.people,
            self.places | other.places,
            self.orgs | other.orgs,
            self.numbers | other.numbers,
            self.words | other.words,
        )

    def seen_in(self, other: Names) -> Names:
        """These names plus those of ``other`` that this headline also contains.

        Keyword rules (and models) miss names: one analysis of "Nga Maroviq te Radoiçiq" finds
        only Maroviq, another of "Nga Maroviq te Milan Radoiçiq" only Radoiçiq, and the person
        guard would keep the two headlines apart although both name both men.
        """
        return Names(
            self.people | (other.people & self.words),
            self.places | (other.places & self.words),
            self.orgs | (other.orgs & self.words),
            self.numbers,
            self.words,
        )


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
    # Names in the headline, for the name guards. Excerpts name secondary people and places, and
    # keyword-rule entities pick up boilerplate ("Gazeta Online Reporteri" in every excerpt of
    # one outlet, "Shtetet e Bashkuara" as a person); on live feeds those split real stories.
    names: Names = field(init=False)
    # Every person-name stem (headline + excerpt): never counted as a shared event word.
    people_all: frozenset[str] = field(init=False)
    # Every specific-place stem (headline + excerpt), for the batch's place lexicon.
    places_all: frozenset[str] = field(init=False)
    headline: frozenset[str] = field(init=False)  # the headline's terms
    has_entities: bool = field(init=False)  # False before (or without) an analysis

    def __post_init__(self) -> None:
        terms: dict[str, float] = {}
        headline = set(tokens(self.title))
        for t in headline:
            terms[t] = terms.get(t, 0.0) + TITLE_WEIGHT
        for t in set(tokens(self.excerpt, max_words=EXCERPT_MAX_WORDS)):
            terms[t] = terms.get(t, 0.0) + EXCERPT_WEIGHT
        entity_names = [*self.people, *self.places, *self.other_entities]
        self.has_entities = bool(entity_names)
        for key in {"@" + normalize_key(n) for n in entity_names if normalize_key(n)}:
            terms[key] = terms.get(key, 0.0) + ENTITY_WEIGHT
        self.terms = terms
        self.headline = frozenset(headline)
        self.people_all = name_stems(self.people)
        self.places_all = name_stems(self.places) - BROAD_PLACES
        self.names = Names(
            self.people_all & headline,
            (name_stems(self.places) - BROAD_PLACES) & headline,
            (name_stems(self.other_entities) - BROAD_PLACES) & headline,
            frozenset(t for t in headline if t.isdigit()),
            self.headline,
        )


def place_lexicon(docs: Iterable[Doc]) -> frozenset[str]:
    """Stems typed as a specific place in any of ``docs``."""
    return frozenset().union(*(d.places_all for d in docs))


def apply_place_lexicon(names: Names, lexicon: frozenset[str]) -> Names:
    """Move stems known as places out of people and organisations.

    Keyword-rule entities swallow places into longer names ("Spitali i Tiranës" as an
    organisation, "Nxënësit e Mitrovicës" as a person). A word the analysis typed as a place
    elsewhere in the same days is treated as a place here too.
    """
    moved = (names.people | names.orgs) & lexicon
    if not moved:
        return names
    return Names(
        names.people - moved, names.places | moved, names.orgs - moved, names.numbers, names.words
    )


def headline_places(doc: Doc, known_places: frozenset[str]) -> Names:
    """Guard names for an article without an analysis: the headline words known as places.

    Without it the place guard has nothing to compare, and "Zjarr në Prizren" joins "Zjarr në
    Gjakovë". Numbers come from the headline itself and need no analysis.
    """
    return Names(places=doc.headline & known_places, numbers=doc.names.numbers, words=doc.headline)


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
    """True when ``terms`` (a headline's) and ``other`` share a term that is not (part of) a
    person's name."""
    return any(t in other and t not in people and not t.startswith("@") for t in terms)


def _weak_overlap(a: frozenset[str], b: frozenset[str]) -> bool:
    """Both non-empty and at most half of the smaller set is shared (overlap coefficient)."""
    return bool(a and b) and len(a & b) <= 0.5 * min(len(a), len(b))


def _disjoint(a: frozenset[str], b: frozenset[str]) -> bool:
    return bool(a and b) and not (a & b)


def conflict_reason(a: Names, b: Names) -> str | None:
    """Which guard separates ``a`` and ``b`` ("places", "numbers", "people", "names") or None."""
    a, b = a.seen_in(b), b.seen_in(a)
    if _weak_overlap(a.places, b.places):
        return "places"
    if _weak_overlap(a.numbers, b.numbers):
        return "numbers"
    if _disjoint(a.people, b.people):
        return "people"
    a_all = a.people | a.places | a.orgs
    b_all = b.people | b.places | b.orgs
    if len(a_all) >= 2 and len(b_all) >= 2 and _disjoint(a_all, b_all):
        return "names"
    return None


def names_conflict(a: Names, b: Names) -> bool:
    """True when the headlines name different places, people or numbers.

    Overlap is measured on name-word stems, so "Osmani" matches "Vjosa Osmani". Places and
    numbers must mostly agree (half of the smaller side): "Prizren + Prishtinë" vs "Pejë +
    Prishtinë" (two accidents on two roads) conflicts. People need only one in common: outlets
    quote different people on one event, and keyword-rule entities type phrases such as
    "Mësuesit e Ferizajt" as people. Entity types are noisy (a person typed as a place), so
    headlines that both name two or more name words of any type must share at least one. A
    name found in one headline counts for the other when that headline contains it too.
    """
    return conflict_reason(a, b) is not None
