"""Dedup layer L3b: one outlet re-publishing an article with its headline edited (ADR-034)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from gjurme.api.app import create_app
from gjurme.config import Settings
from gjurme.db.models import Article, FeedItem, Source
from gjurme.ingestion.ingest import ingest_all
from gjurme.ingestion.normalize import normalize_key, sha256_hex
from gjurme.ingestion.processor import REVISION_HIDDEN_REASON, process_pending
from gjurme.ingestion.revisions import fold_revisions
from gjurme.stories.clustering import cluster_pending
from tests.conftest import feed_server
from tests.integration.helpers import add_source, pubdate, rss

pytestmark = pytest.mark.integration
TZ = ZoneInfo("Europe/Tirane")

ZULFAJ = (
    "Zulfaj e quan {} interpretimin e muzikës së këngës nacionaliste serbe në Forumin e "
    "Zgjerimit të BE-së"
)


def _ingest(db, settings, make_fetcher, feeds: dict[str, list[dict[str, str]]]) -> None:
    routes = {}
    with db() as s, s.begin():
        for slug, items in feeds.items():
            url = f"https://{slug}.example.com/feed/"
            add_source(s, slug, url)
            routes[url] = (200, rss(items), {})
    ingest_all(db, make_fetcher(feed_server(routes)), settings)


def _item(slug: str, n: int, title: str, hours_ago: float) -> dict[str, str]:
    return {
        "title": title,
        "link": f"https://{slug}.example.com/{n}",
        "guid": f"{slug}-{n}",
        "pubDate": pubdate(hours_ago),
        "description": f"Përshkrimi {n}.",
    }


def test_edited_headlines_fold_into_the_newest_wording(
    db: sessionmaker[Session], settings: Settings, make_fetcher
) -> None:
    _ingest(
        db,
        settings,
        make_fetcher,
        {
            "koha": [
                _item("koha", 1, ZULFAJ.format("skandaloze"), 3.0),
                _item("koha", 2, ZULFAJ.format("skandaloz"), 2.99),
                _item("koha", 3, ZULFAJ.format("skandal"), 2.98),
                # words joined by a typo, then fixed
                _item("koha", 4, "Kënga nacionalisteserbe në Bruksel, Gërvalla kërkon masa", 2),
                _item("koha", 5, "Kënga nacionaliste serbe në Bruksel, Gërvalla kërkon masa", 1.9),
                # different articles that look alike: numbers, series, live updates, negation
                _item("koha", 6, "Aksident në Prishtinë, 3 të vdekur dhe disa të plagosur", 5),
                _item("koha", 7, "Aksident në Prishtinë, 5 të vdekur dhe disa të plagosur", 4.5),
                _item("koha", 8, "Dosja e privatizimit të PTK-së, pjesa e parë", 6),
                _item("koha", 9, "Dosja e privatizimit të PTK-së, pjesa e dytë", 5.5),
                _item("koha", 10, "LIVE: Numërohen votat në qendrat e votimit në Kosovë", 4),
                _item("koha", 11, "LIVE: Numërohen votat në qendrat e numërimit në Kosovë", 3.5),
                _item("koha", 12, "Kurti do të marrë pjesë në takimin e Brukselit", 7),
                _item("koha", 13, "Kurti nuk do të marrë pjesë në takimin e Brukselit", 6.5),
                # the same wording a day apart is a new article (outside the window)
                _item(
                    "koha", 14, "Moti nesër me shi në gjithë vendin dhe temperatura të ulëta", 30
                ),
                _item(
                    "koha", 15, "Moti nesër me shira në gjithë vendin dhe temperatura të ulëta", 2
                ),
            ],
            # another outlet with the same edit is not a revision (that is L4 / stories)
            "zeri": [_item("zeri", 1, ZULFAJ.format("skandaloz"), 2.5)],
        },
    )
    with db() as s:
        stats = process_pending(s, settings)
    assert stats.duplicates == {"l3_revision": 3}
    assert stats.accepted == 13

    with db() as s:
        rows = {a.guid: a for a in s.scalars(select(Article))}
        first, second, third = rows["koha-1"], rows["koha-2"], rows["koha-3"]
        # the article readers see keeps its URL and time, and shows the newest wording
        assert not first.is_hidden and first.url == "https://koha.example.com/1"
        assert first.title == ZULFAJ.format("skandal")
        assert first.title_normalized == normalize_key(first.title)
        assert first.excerpt == "Përshkrimi 3."
        for rev in (second, third):
            assert rev.is_hidden and rev.hidden_reason == REVISION_HIDDEN_REASON
            assert rev.duplicate_of_id == first.id and rev.enrichment_status == "skipped"
        assert rows["koha-5"].duplicate_of_id == rows["koha-4"].id
        assert rows["koha-4"].title.startswith("Kënga nacionaliste serbe")
        visible = {g for g, a in rows.items() if not a.is_hidden}
        assert {f"koha-{n}" for n in (6, 7, 8, 9, 10, 11, 12, 13, 14, 15)} <= visible
        assert "zeri-1" in visible
        reasons = dict(s.execute(select(FeedItem.guid, FeedItem.rejection_reason)).all())
        assert reasons["koha-2"] == reasons["koha-3"] == "dup_l3_revision"
        assert s.scalar(select(FeedItem.article_id).where(FeedItem.guid == "koha-3")) == third.id

    with db() as s:  # rerun: idempotent
        assert process_pending(s, settings).processed == 0


def test_a_revision_published_out_of_order_keeps_the_newest_wording(
    db: sessionmaker[Session], settings: Settings, make_fetcher
) -> None:
    newest, older = ZULFAJ.format("skandal"), ZULFAJ.format("skandaloze")
    _ingest(db, settings, make_fetcher, {"koha": [_item("koha", 1, newest, 1)]})
    with db() as s:
        process_pending(s, settings)
    later = [_item("koha", 2, older, 2)]  # seen later, dated earlier
    routes = {"https://koha.example.com/feed/": (200, rss(later), {})}
    ingest_all(db, make_fetcher(feed_server(routes)), settings)
    with db() as s:
        assert process_pending(s, settings).duplicates == {"l3_revision": 1}
        shown = s.scalar(select(Article).where(Article.is_hidden.is_(False)))
        assert shown is not None and shown.title == newest


def test_a_chain_of_edits_folds_into_the_first_beyond_the_window(
    db: sessionmaker[Session], settings: Settings, make_fetcher
) -> None:
    t = "Kënga {} në Bruksel, Gërvalla kërkon masa konkrete nga Komisioni"
    items = [
        _item("zeri", 1, t.format("nacionalisteserbe"), 5),
        _item("zeri", 2, t.format("nacionaliste serbe"), 3.5),  # 1.5 h after the first
        _item("zeri", 3, t.format("nacionaliste serbe") + " Evropian", 1),  # 4 h after
    ]
    _ingest(db, settings, make_fetcher, {"zeri": items})
    with db() as s:
        assert process_pending(s, settings).duplicates == {"l3_revision": 2}
        shown = list(s.scalars(select(Article).where(Article.is_hidden.is_(False))))
        assert [a.guid for a in shown] == ["zeri-1"]
        hidden = s.scalars(select(Article.duplicate_of_id).where(Article.is_hidden.is_(True)))
        assert set(hidden) == {shown[0].id}


def _article(s: Session, source: Source, title: str, at: datetime) -> Article:
    art = Article(
        source_id=source.id,
        url=f"https://{source.slug}.example.com/{sha256_hex(title, at.isoformat())[:12]}",
        canonical_url="x",
        url_hash=sha256_hex(title, at.isoformat(), source.slug),
        title=title,
        title_normalized=normalize_key(title),
        title_hash=sha256_hex(normalize_key(title)),
        language="sq",
        published_at=at,
        published_date=at.astimezone(TZ).date(),
        content_hash=sha256_hex(title),
        enrichment_status="succeeded",
    )
    s.add(art)
    s.flush()
    return art


def test_backfill_reports_then_folds_stored_revisions(
    db: sessionmaker[Session], settings: Settings
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    with db() as s, s.begin():
        koha, zeri = add_source(s, "koha"), add_source(s, "zeri")
        a1 = _article(s, koha, ZULFAJ.format("skandaloze"), now - timedelta(hours=3))
        a2 = _article(
            s, koha, ZULFAJ.format("skandaloz"), now - timedelta(hours=3) + timedelta(seconds=35)
        )
        a3 = _article(
            s, koha, ZULFAJ.format("skandal"), now - timedelta(hours=3) + timedelta(seconds=35)
        )
        z1 = _article(s, zeri, ZULFAJ.format("skandaloz"), now - timedelta(hours=2))
        _article(
            s,
            koha,
            "Aksident në Prishtinë, 3 të vdekur dhe disa të plagosur",
            now - timedelta(hours=2),
        )
        _article(
            s,
            koha,
            "Aksident në Prishtinë, 5 të vdekur dhe disa të plagosur",
            now - timedelta(hours=1),
        )
        z1.duplicate_of_id = a2.id  # an L4 copy of what becomes a revision
        ids = (a1.id, a2.id, a3.id, z1.id)
    with db() as s:
        cluster_pending(s, settings)

    since = (now - timedelta(days=2)).astimezone(TZ).date()
    with db() as s, s.begin():
        report = fold_revisions(s, TZ, since)
    assert report["revisions"] == 2 and report["by_source"] == {"koha": 2}
    assert report["applied"] is False
    with db() as s:  # a report changes nothing
        assert s.scalar(select(Article.is_hidden).where(Article.id == ids[1])) is False

    with db() as s, s.begin():
        report = fold_revisions(s, TZ, since, apply=True)
    assert report["applied"] is True
    with db() as s:
        rows = {a.id: a for a in s.scalars(select(Article).where(Article.id.in_(ids)))}
        assert rows[ids[0]].title == ZULFAJ.format("skandal") and not rows[ids[0]].is_hidden
        assert rows[ids[1]].is_hidden and rows[ids[1]].duplicate_of_id == ids[0]
        assert rows[ids[2]].is_hidden and rows[ids[2]].duplicate_of_id == ids[0]
        assert rows[ids[3]].duplicate_of_id == ids[0]  # re-pointed at what is shown
        story_id = rows[ids[0]].story_id
    with db() as s, s.begin():  # a second run finds nothing new
        assert fold_revisions(s, TZ, since, apply=True)["revisions"] == 0

    # the story counts and lists one KOHA article, with the newest headline
    client = TestClient(create_app(settings, db))
    story = client.get(f"/api/v1/stories/{story_id}").json()
    koha_titles = [a["title"] for a in story["articles"] if a["source_slug"] == "koha"]
    assert koha_titles.count(ZULFAJ.format("skandal")) == 1
    assert ZULFAJ.format("skandaloze") not in koha_titles
