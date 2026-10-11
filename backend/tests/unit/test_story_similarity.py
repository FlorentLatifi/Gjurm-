"""Story clustering text similarity: tokens, TF-IDF, name guards and the calibration pairs."""

from __future__ import annotations

import pytest

from gjurme.config import Settings
from gjurme.sources.ratings import bias_group
from gjurme.stories.similarity import (
    Doc,
    Names,
    cosine,
    idf_table,
    name_stems,
    names_conflict,
    shares_event_term,
    tokens,
    vector,
)


def test_tokens_fold_stem_and_drop_noise() -> None:
    # Inflections of one word share a stem; stopwords, outlet labels and 1-digit numbers go.
    assert tokens("Prishtinë, Prishtinës dhe Prishtinën") == ["prish", "prish", "prish"]
    # short names keep their case endings within six letters; one ending is dropped
    assert tokens("Kurti, Kurtin, Kurtit") == ["kurt", "kurt", "kurt"]
    assert tokens("Prizren Prizrenit") == ["prizr", "prizr"]
    assert tokens("presidenti presioni") == ["presid", "presio"]  # long words stay apart
    assert tokens("VIDEO: Kuvendi i Kosovës për 2 orë") == ["kuvend", "kosov"]
    assert tokens("Buxheti 2027") == tokens("buxhetin 2027") == ["buxhe", "2027"]
    assert tokens(None) == [] and tokens("") == []


def test_name_stems_match_partial_names() -> None:
    assert name_stems(["Vjosa Osmani"]) & name_stems(["Osmanit"]) == {"osman"}
    assert name_stems(["e"]) == frozenset()


def test_idf_weights_rare_terms_higher() -> None:
    docs = [Doc(i, "Kuvendi mblidhet sot") for i in range(5)] + [Doc(9, "Kuvendi dhe Prizreni")]
    idf = idf_table(docs)
    assert idf["prizr"] > idf["kuvend"]
    v = vector(docs[-1], idf)
    assert v["prizr"] > v["kuvend"]
    assert cosine(v, v) == pytest.approx(1.0)
    assert vector(Doc(1, "dhe e në"), idf) == {}  # nothing but stopwords


@pytest.mark.parametrize(
    ("a", "b", "conflict"),
    [
        # same places / one side names none → no conflict
        (Names(places=frozenset({"durres"})), Names(places=frozenset({"durres", "tirane"})), False),
        (Names(places=frozenset({"prizr"})), Names(), False),
        # two accidents on two roads: half shared → conflict
        (
            Names(places=frozenset({"prizr", "prish"})),
            Names(places=frozenset({"pej", "prish"})),
            True,
        ),
        # an extra person named on one side does not split a story
        (
            Names(people=frozenset({"bahri", "hyseni", "kosove"})),
            Names(people=frozenset({"bahri", "hyseni"})),
            False,
        ),
        (Names(people=frozenset({"kurti"})), Names(people=frozenset({"osmani"})), True),
        # entity types are noisy: a person typed as a place still conflicts with other people
        (
            Names(places=frozenset({"vlora", "hoxha"})),
            Names(people=frozenset({"agron", "rexhep"})),
            True,
        ),
        # a single combined name on one side is not enough to call it a conflict
        (Names(places=frozenset({"prish"})), Names(people=frozenset({"muriqi", "rashic"})), False),
    ],
)
def test_names_conflict(a: Names, b: Names, conflict: bool) -> None:
    assert names_conflict(a, b) is conflict
    assert names_conflict(b, a) is conflict


SAME_EVENT = [
    (
        ("KQZ certifikon rezultatet përfundimtare të zgjedhjeve lokale", "KQZ", None),
        ("Certifikohen rezultatet e zgjedhjeve, KQZ jep dritën e gjelbër", "KQZ", None),
    ),
    (
        ("Tërmet 4.2 ballë në Durrës, banorët dalin në rrugë", None, "Durrës"),
        ("Lëkundje tërmeti 4.2 ballë në Durrës, nuk ka të lënduar", None, "Durrës"),
    ),
    (
        ("Kuvendi miraton buxhetin për vitin 2027", "Kuvendi", None),
        ("Miratohet buxheti i 2027-s, Kuvendi voton me 61 vota", "Kuvendi", None),
    ),
]
DIFFERENT_EVENT = [
    (
        ("Zjarr në një ndërtesë banimi në Prizren", None, "Prizren"),
        ("Zjarr në një ndërtesë banimi në Gjakovë", None, "Gjakovë"),
    ),
    (
        ("Gjykata në Prizren dënon ish-zyrtarin me 3 vjet burg", None, "Prizren"),
        ("Gjykata në Pejë dënon ish-zyrtarin me 5 vjet burg", None, "Pejë"),
    ),
]
BACKGROUND = [
    "Policia arreston dy persona në Ferizaj",
    "Rriten çmimet e energjisë elektrike",
    "Qeveria miraton projektligjin për arsimin",
    "Ndeshja përfundon pa gola në Mitrovicë",
    "Ministri takon ambasadorin gjerman",
    "Shkollat nisin vitin e ri mësimor",
    "Aksident trafiku në rrugën për Pejë",
    "Festivali i filmit hap dyert në Prizren",
]


def _doc(i: int, title: str, org: str | None, place: str | None) -> Doc:
    return Doc(i, title, None, (), [place] if place else [], [org] if org else [])


def _sim_and_conflict(a: Doc, b: Doc, background: list[Doc]) -> tuple[float, bool]:
    idf = idf_table([a, b, *background])
    return cosine(vector(a, idf), vector(b, idf)), names_conflict(a.names, b.names)


def test_calibration_pairs_against_default_threshold() -> None:
    """Paraphrases of one event pass the default threshold; template-alike events don't."""
    threshold = Settings(_env_file=None).story_similarity_threshold  # type: ignore[call-arg]
    background = [Doc(100 + i, t) for i, t in enumerate(BACKGROUND)]
    for a, b in SAME_EVENT:
        sim, conflict = _sim_and_conflict(_doc(1, *a), _doc(2, *b), background)
        assert sim >= threshold and not conflict, (a[0], b[0], sim)
    for a, b in DIFFERENT_EVENT:
        sim, conflict = _sim_and_conflict(_doc(1, *a), _doc(2, *b), background)
        # they *look* alike (higher than most paraphrases); only the name guard separates them
        assert sim >= threshold and conflict, (a[0], b[0], sim)


def test_a_shared_person_alone_is_not_a_shared_event() -> None:
    a = Doc(1, "Blerta Zeqiri prezanton programin zgjedhor", people=["Blerta Zeqiri"])
    b = Doc(2, "Blerta Zeqiri kërkon seancë në Kuvend", people=["Blerta Zeqiri"])
    c = Doc(3, "Blerta Zeqiri prezanton programin në Prizren", people=["Blerta Zeqiri"])
    idf = idf_table([a, b, c])
    people = a.names.people | b.names.people
    assert not shares_event_term(vector(a, idf), vector(b, idf), people)
    assert shares_event_term(vector(a, idf), vector(c, idf), people)  # "prezanton programin"


def test_bias_groups() -> None:
    assert [bias_group(b) for b in ("left", "lean_left", "center", "lean_right", "right")] == [
        "left",
        "left",
        "center",
        "right",
        "right",
    ]
    assert bias_group("unrated") == bias_group("bogus") == "unrated"
