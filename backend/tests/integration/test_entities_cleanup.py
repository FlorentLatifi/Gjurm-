"""``gjurme entities-cleanup``: outlets' own names and the case forms already stored."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from gjurme.cli import app
from gjurme.config import get_settings
from gjurme.db.models import Article, ArticleEntity, Entity, Source
from gjurme.db.session import get_engine, get_sessionmaker
from gjurme.enrichment.entities import cleanup_entities
from gjurme.ingestion.normalize import normalize_key, sha256_hex
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.integration


def _source(s: Session, slug: str, name: str) -> Source:
    src = Source(
        slug=slug,
        name=name,
        homepage_url=f"https://{slug}.example.com/",
        feed_url=f"https://{slug}.example.com/feed/",
        language="sq",
        country="XK",
    )
    s.add(src)
    s.flush()
    return src


def _article(s: Session, src: Source, n: int) -> int:
    title = f"Lajm {src.slug} {n}"
    art = Article(
        source_id=src.id,
        url=f"https://{src.slug}.example.com/{n}",
        canonical_url=f"https://{src.slug}.example.com/{n}",
        url_hash=sha256_hex(src.slug, str(n)),
        title=title,
        title_normalized=normalize_key(title),
        title_hash=sha256_hex(title),
        language="sq",
        published_at=datetime(2026, 11, 17, 10, n, tzinfo=UTC),
        published_date=date(2026, 11, 17),
        content_hash=sha256_hex(title, str(n)),
    )
    s.add(art)
    s.flush()
    return art.id


def _entity(s: Session, name: str, etype: str, articles: list[int]) -> int:
    ent = Entity(type=etype, normalized_key=normalize_key(name), name=name)
    s.add(ent)
    s.flush()
    for aid in articles:
        s.add(ArticleEntity(article_id=aid, entity_id=ent.id, published_date=date(2026, 11, 17)))
    s.flush()
    return ent.id


@pytest.fixture
def stored(db: sessionmaker[Session]) -> dict[str, int]:
    with db() as s, s.begin():
        reporteri = _source(s, "reporteri", "Reporteri.net")
        koha = _source(s, "koha", "KOHA")
        r1, r2 = _article(s, reporteri, 1), _article(s, reporteri, 2)
        k1, k2, k3 = (_article(s, koha, n) for n in (1, 2, 3))
        return {
            "kosoves": _entity(s, "Kosovës", "location", [k1, k2, r1]),
            "kosova": _entity(s, "Kosova", "location", [k2, k3]),
            "kosoven": _entity(s, "Kosovën", "location", [k3]),
            "boilerplate": _entity(s, "Gazeta Online Reporteri", "person", [r1, r2, k1]),
            "police": _entity(s, "Policia", "organization", [k1]),
            "policise": _entity(s, "Policisë", "organization", [k2]),
        }


def _links(s: Session, entity_id: int) -> int:
    return (
        s.scalar(
            select(func.count())
            .select_from(ArticleEntity)
            .where(ArticleEntity.entity_id == entity_id)
        )
        or 0
    )


def test_dry_run_reports_and_changes_nothing(db: sessionmaker[Session], stored) -> None:
    with db() as s, s.begin():
        report = cleanup_entities(s, apply=False)
    assert not report["applied"]
    assert report["self_reference_links"] == 2  # Reporteri.net's own two articles only
    assert report["merge_groups"] == 1 and report["entities_merged_away"] == 2
    [merge] = report["largest_merges"]
    assert merge["keep_id"] == stored["kosoves"] and merge["name"] == "Kosova"
    with db() as s:
        assert s.scalar(select(func.count()).select_from(Entity)) == 6
        assert _links(s, stored["boilerplate"]) == 3


def test_apply_merges_forms_and_drops_self_references(db: sessionmaker[Session], stored) -> None:
    with db() as s, s.begin():
        report = cleanup_entities(s, apply=True)
    assert report["applied"] and report["entities_merged_away"] == 2
    with db() as s:
        place = s.get(Entity, stored["kosoves"])
        assert place is not None and place.name == "Kosova"
        assert _links(s, stored["kosoves"]) == 4  # k1, k2, k3, r1: each article once
        assert s.get(Entity, stored["kosova"]) is None and s.get(Entity, stored["kosoven"]) is None
        # still linked to KOHA's article, where naming the outlet is news about it
        assert _links(s, stored["boilerplate"]) == 1
        # organisations are not merged
        assert s.get(Entity, stored["policise"]) is not None
    with db() as s, s.begin():
        again = cleanup_entities(s, apply=True)
    assert again["merge_groups"] == 0 and again["self_reference_links"] == 0


def test_cli_reports_by_default(monkeypatch: pytest.MonkeyPatch, db, stored) -> None:
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("GJURME_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LOG_FORMAT", "text")
    for cached in (get_settings, get_engine, get_sessionmaker):
        cached.cache_clear()
    try:
        result = CliRunner().invoke(app, ["entities-cleanup", "--show", "5"])
        assert result.exit_code == 0, result.output
        report = json.loads(result.output[result.output.index("{") :])
        assert report["applied"] is False and report["entities_merged_away"] == 2
        with db() as s:
            assert s.scalar(select(func.count()).select_from(Entity)) == 6
    finally:
        for cached in (get_settings, get_engine, get_sessionmaker):
            cached.cache_clear()


def test_not_persons_are_read_again_then_forms_merged(db: sessionmaker[Session]) -> None:
    """The keyword rules stored "i Kosovës", "Vitomiricë të Pejës" and "Kuvendit të Kosovës" as
    persons (live data, 2026-11-18): each becomes what it is, and its links follow it."""
    with db() as s, s.begin():
        koha = _source(s, "koha", "KOHA")
        k1, k2, k3 = (_article(s, koha, n) for n in (1, 2, 3))
        kosova = _entity(s, "Kosova", "location", [k1, k2])
        _entity(s, "i Kosovës", "person", [k1, k3])
        _entity(s, "Vitomiricë të Pejës", "person", [k2])
        _entity(s, "Kuvendit të Kosovës", "person", [k3])
        _entity(s, "Dënimi i Thaçit", "person", [k3])
        albin = _entity(s, "Albin Kurti", "person", [k1])
    with db() as s, s.begin():
        report = cleanup_entities(s, apply=False)
    assert report["not_persons"] == 4 and report["not_persons_links"] == 5
    becomes = {j["name"]: j["becomes"] for j in report["not_persons_largest"]}
    assert becomes["i Kosovës"] == {"name": "Kosovës", "type": "location"}
    assert becomes["Dënimi i Thaçit"] == {"name": "Dënimi i Thaçit", "type": "organization"}
    with db() as s, s.begin():
        cleanup_entities(s, apply=True)
    with db() as s:
        found = {(e.name, e.type) for e in s.scalars(select(Entity))}
        assert found == {
            ("Kosova", "location"),  # "i Kosovës" → "Kosovës", then merged into Kosova
            ("Vitomiricë të Pejës", "location"),
            ("Kuvendit të Kosovës", "organization"),
            ("Dënimi i Thaçit", "organization"),
            ("Albin Kurti", "person"),
        }
        assert _links(s, kosova) == 3 and _links(s, albin) == 1
    with db() as s, s.begin():
        again = cleanup_entities(s, apply=True)
    assert again["not_persons"] == 0 and again["merge_groups"] == 0


def test_cli_apply_commits(monkeypatch: pytest.MonkeyPatch, db, stored) -> None:
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("GJURME_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LOG_FORMAT", "text")
    for cached in (get_settings, get_engine, get_sessionmaker):
        cached.cache_clear()
    try:
        result = CliRunner().invoke(app, ["entities-cleanup", "--apply", "--show", "5"])
        assert result.exit_code == 0, result.output
        with db() as s:  # a new session: the change was committed
            assert s.get(Entity, stored["kosova"]) is None
            place = s.get(Entity, stored["kosoves"])
            assert place is not None and place.name == "Kosova"
    finally:
        for cached in (get_settings, get_engine, get_sessionmaker):
            cached.cache_clear()
