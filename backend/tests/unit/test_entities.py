"""One entity per person or place: Albanian case forms and outlets' own names."""

from __future__ import annotations

import pytest

from gjurme.enrichment.entities import (
    _merge_plan,
    _Stored,
    drop_self_references,
    same_entity,
    self_names,
    variant_keys,
)
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
