"""One entity per person or place: Albanian case forms and outlets' own names."""

from __future__ import annotations

import pytest

from gjurme.enrichment.entities import (
    _merge_plan,
    _Stored,
    drop_self_references,
    retype_persons,
    same_entity,
    self_names,
    variant_keys,
)
from gjurme.enrichment.providers import rule_entity
from gjurme.enrichment.schema import EntityOut
from gjurme.ingestion.normalize import normalize_key


def _k(name: str) -> str:
    return normalize_key(name)


@pytest.mark.parametrize(
    ("a", "b", "etype"),
    [
        ("Kosova", "Kosovës", "location"),
        ("Kosova", "Kosovën", "location"),
        ("Kosovë", "Kosova", "location"),
        ("Kosovo", "Kosova", "location"),
        ("Prishtina", "Prishtinës", "location"),
        ("Serbia", "Serbisë", "location"),
        ("Shqipëria", "Shqipërinë", "location"),
        ("Maqedonisë", "Maqedoninë", "location"),
        ("Hashim Thaçi", "Hashim Thaçin", "person"),
        ("Edon Zhegrova", "Edon Zhegrovën", "person"),
        ("Tirana", "Tiranë", "location"),
        ("Hashim Thaçi", "Hashim Thaçit", "person"),
        ("Albin Kurti", "Albin Kurtin", "person"),
        ("Edi Rama", "Edi Ramës", "person"),  # a 3-letter stem after a first name
        ("Arlinda Zekaj", "Arlinda Zekajt", "person"),
        ("Donald Trump", "Donald Trumpit", "person"),
    ],
)
def test_case_forms_are_one_entity(a: str, b: str, etype: str) -> None:
    assert same_entity(_k(a), _k(b), etype) and same_entity(_k(b), _k(a), etype)
    assert _k(b) in variant_keys(_k(a), etype)


@pytest.mark.parametrize(
    ("a", "b", "etype"),
    [
        ("Albin Kurti", "Arben Kurti", "person"),  # another first name: another person
        ("Kosova", "Kosovare", "location"),  # an adjective, not a case form
        ("Iran", "Irak", "location"),
        ("Australia", "Austria", "location"),
        ("Shqipëria", "Shqiptarët", "location"),
        ("Peja", "Pejton", "location"),
        ("Kosova", "Kosovo", "person"),  # "-o" is a form of a place only
        ("Policia", "Policisë", "organization"),  # organisations are left as they are
        ("Rama", "Ramë", "person"),  # a single word needs a 4-letter stem
        # found on live data (2026-11-18): a Montenegrin town, an English adjective
        ("Berat", "Berane", "location"),
        ("Serbia", "Serbian", "location"),
    ],
)
def test_different_names_stay_apart(a: str, b: str, etype: str) -> None:
    assert not same_entity(_k(a), _k(b), etype)
    assert _k(b) not in variant_keys(_k(a), etype)


def test_an_outlet_is_not_an_entity_of_its_own_articles() -> None:
    """Reporteri.net's feed ends every excerpt with "Gazeta Online Reporteri" (sources.yaml
    alias); the keyword rules took it for a person in 1,444 articles."""
    assert {"gazeta online reporteri", "reporteri net", "reporteri"} <= self_names("Reporteri.net")
    entities = [
        EntityOut(name="Gazeta Online Reporteri", type="person"),
        EntityOut(name="Reporteri", type="organization"),
        EntityOut(name="Albin Kurti", type="person"),
    ]
    kept, dropped = drop_self_references(entities, "Reporteri.net")
    assert [e.name for e in kept] == ["Albin Kurti"]
    assert [e.name for e in dropped] == ["Gazeta Online Reporteri", "Reporteri"]
    # another outlet's article may name it: that is news about the outlet
    kept, dropped = drop_self_references(entities, "KOHA")
    assert len(kept) == 3 and not dropped
    assert drop_self_references(entities, "Unknown outlet") == (entities, [])


def test_merge_keeps_the_most_linked_entity_under_its_nominative_name() -> None:
    forms = [
        _Stored(15, "location", "kosoves", "Kosovës", 2474),
        _Stored(18, "location", "kosova", "Kosova", 2316),
        _Stored(114, "location", "kosove", "Kosovë", 1313),
        _Stored(32, "location", "kosoven", "Kosovën", 525),
    ]
    [plan] = _merge_plan([forms])
    assert plan["keep_id"] == 15 and plan["name"] == "Kosova"
    assert plan["mentions"] == 6628 and [m["id"] for m in plan["merged"]] == [15, 18, 114, 32]
    people = [
        _Stored(3013, "person", "hashim thaci", "Hashim Thaçi", 217),
        _Stored(20049, "person", "hashim thacit", "Hashim Thaçit", 24),
    ]
    [plan] = _merge_plan([people])
    assert plan["keep_id"] == 3013 and plan["name"] == "Hashim Thaçi"
    # the genitive is the most used form here, but never the name shown
    people[1].mentions = 900
    [plan] = _merge_plan([people])
    assert plan["keep_id"] == 20049 and plan["name"] == "Hashim Thaçi"


@pytest.mark.parametrize(
    ("run", "expected"),
    [
        ("Presidentja e Kosovës", ("Kosovës", "location")),  # the role goes, then the "e"
        ("Vitomiricë të Pejës", ("Vitomiricë të Pejës", "location")),  # a village of Peja
        ("Kuvendit të Kosovës", ("Kuvendit të Kosovës", "organization")),
        ("Komunën e Prishtinës", ("Komunën e Prishtinës", "organization")),
        ("Policisë së Kosovës", ("Policisë së Kosovës", "organization")),
        ("Gjykata Themelore në Prishtinë", ("Gjykata Themelore në Prishtinë", "organization")),
        ("Trajneri Blerta Zeqiri", ("Blerta Zeqiri", "person")),
        ("Albin Kurti", ("Albin Kurti", "person")),
        ("NATO", ("NATO", "organization")),
        ("Dënimi i Thaçit", ("Dënimi i Thaçit", "organization")),  # no person
        ("Shtetet e Bashkuara", ("Shtetet e Bashkuara", "location")),
        ("Malit të Zi", ("Malit të Zi", "location")),
        ("Dogana e Kosovës", ("Dogana e Kosovës", "organization")),
        ("Lidhjes Demokratike të Kosovës", ("Lidhjes Demokratike të Kosovës", "organization")),
        ("Radio Evropa e Lirë", ("Radio Evropa e Lirë", "organization")),
        ("Kryetarja e Kuvendit të Kosovës", ("Kuvendit të Kosovës", "organization")),
        ("i LDK-së", ("LDK", "organization")),
        ("i SHBA-së", ("SHBA", "location")),
        ("i Izraelit", ("Izraelit", "location")),
        ("Franco Foda", ("Franco Foda", "person")),
        ("Ish-presidentja e Kosovës", ("Kosovës", "location")),
        ("Superligën e Kosovës", ("Superligën e Kosovës", "organization")),  # no village
        ("Gjonaj të Prizrenit", ("Gjonaj të Prizrenit", "location")),  # a village
        ("i Listës Studentore", ("Listës Studentore", "organization")),
        ("e Republikës", None),  # a fragment: "Presidenti i Republikës"
        ("Sipas", None),
    ],
)
def test_keyword_rules_read_names(run: str, expected: tuple[str, str] | None) -> None:
    assert rule_entity(run) == expected


def test_a_person_with_a_connector_is_read_again() -> None:
    """Live data, 2026-11-18: "i Kosovës" (349 articles), "Kuvendit të Kosovës" (201) and
    "Vitomiricë të Pejës" (460) were persons."""
    entities = [
        EntityOut(name="i Kosovës", type="person"),
        EntityOut(name="Kuvendit të Kosovës", type="person"),
        EntityOut(name="Vitomiricë të Pejës", type="person"),
        EntityOut(name="Dënimi i Thaçit", type="person"),
        EntityOut(name="Albin Kurti", type="person"),
        EntityOut(name="Lidhja Demokratike e Kosovës", type="organization"),
        EntityOut(name="e Kosovës", type="organization"),
    ]
    kept, changed = retype_persons(entities)
    assert [(e.name, e.type) for e in kept] == [
        ("Kosovës", "location"),
        ("Kuvendit të Kosovës", "organization"),
        ("Vitomiricë të Pejës", "location"),
        ("Dënimi i Thaçit", "organization"),  # an event, but no person
        ("Albin Kurti", "person"),
        ("Lidhja Demokratike e Kosovës", "organization"),  # an organisation may have an "e"
    ]
    assert changed == [
        "i Kosovës",
        "Kuvendit të Kosovës",
        "Vitomiricë të Pejës",
        "Dënimi i Thaçit",
        "e Kosovës",  # "Kosovës" is kept once
    ]


def test_more_outlet_aliases() -> None:
    assert "gazeta sinjali" in self_names("Sinjali")
    assert "gazeta online reporteri net" in self_names("Reporteri.net")
