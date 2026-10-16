"""Stories: the CLUSTER stage, source ratings and the story / blindspot / source-profile API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from gjurme.api.app import create_app
from gjurme.config import Settings
from gjurme.db.models import Article, Source, Story
from gjurme.enrichment.schema import EnrichmentOutput
from gjurme.enrichment.service import apply_output
from gjurme.ingestion.normalize import normalize_key, sha256_hex
from gjurme.quality.checks import check_story_backlog
from gjurme.sources.registry import Registry, SourceConfig, sync_sources
from gjurme.stories.clustering import cluster_pending, rebuild
from gjurme.stories.review import review_report
from tests.integration.helpers import add_source

pytestmark = pytest.mark.integration
TZ = ZoneInfo("Europe/Tirane")
NOW = datetime.now(UTC).replace(microsecond=0)

# outlet -> (bias, factuality, ownership, country)
OUTLETS = {
    "majtas": ("left", "high", "private", "XK"),
    "qendra": ("center", "very_high", "public", "XK"),
    "djathtas": ("right", "mixed", "media_group", "XK"),
    "tirana": ("lean_right", "high", "private", "AL"),
    "pavleresuar": ("unrated", "unrated", "unknown", "MK"),
}


def rated_source(s: Session, slug: str) -> Source:
    bias, factuality, ownership, country = OUTLETS[slug]
    src = add_source(s, slug)
    src.bias, src.factuality, src.ownership, src.country = bias, factuality, ownership, country
    s.flush()
    return src


def article(
    s: Session,
    source: Source,
    title: str,
    at: datetime,
    *,
    excerpt: str | None = None,
    entities: list[tuple[str, str]] | None = None,
    countries: list[str] | None = None,
    topic: str = "politics",
    sentiment: str = "neutral",
    duplicate_of: int | None = None,
) -> int:
    art = Article(
        source_id=source.id,
        url=f"https://{source.slug}.example.com/{sha256_hex(title, at.isoformat())[:12]}",
        canonical_url="x",
        url_hash=sha256_hex(title, at.isoformat(), source.slug),
        title=title,
        title_normalized=normalize_key(title),
        title_hash=sha256_hex(title),
        excerpt=excerpt,
        language="sq",
        published_at=at,
        published_date=at.astimezone(TZ).date(),
        content_hash=sha256_hex(title),
        duplicate_of_id=duplicate_of,
    )
    s.add(art)
    s.flush()
    apply_output(
        s,
        art.id,
        EnrichmentOutput(
            language="sq",
            primary_topic=topic,
            secondary_topics=[],
            sentiment=sentiment,
            sentiment_score={"negative": -0.5, "neutral": 0.0, "positive": 0.5}[sentiment],
            event_type="other",
            summary_en=f"Summary: {title}",
            summary_sq=f"Përmbledhje: {title}",
            entities=[{"name": n, "type": t} for n, t in (entities or [])],
            countries=countries or ["XK"],
            confidence=0.9,
        ),
    )
    return art.id


@pytest.fixture
def newsroom(db: sessionmaker[Session]) -> dict[str, Any]:
    """Three events covered by several outlets, plus look-alike headlines about other places."""
    ids: dict[str, Any] = {}
    t0 = NOW - timedelta(hours=10)
    with db() as s, s.begin():
        src = {slug: rated_source(s, slug) for slug in OUTLETS}
        # Event 1: the budget vote — four outlets, four wordings; the left did not cover it.
        budget = [
            (
                "qendra",
                "Kuvendi miraton buxhetin për vitin 2027",
                "Me 61 vota për, Kuvendi i Kosovës miratoi buxhetin e vitit 2027.",
            ),
            (
                "djathtas",
                "Miratohet buxheti i 2027-s, opozita voton kundër",
                "Kuvendi miratoi buxhetin me 61 vota; opozita kritikoi buxhetin.",
            ),
            (
                "tirana",
                "Buxheti 2027 kalon në Kuvend me 61 vota",
                "Deputetët e Kuvendit votuan buxhetin e vitit 2027.",
            ),
            (
                "pavleresuar",
                "Kuvendi i Kosovës voton buxhetin e vitit 2027",
                "Buxheti u miratua me 61 vota në Kuvend.",
            ),
        ]
        ids["budget"] = [
            article(
                s,
                src[slug],
                title,
                t0 + timedelta(minutes=30 * i),
                excerpt=excerpt,
                entities=[("Kuvendi", "organization")],
                topic="economy" if i else "politics",
                sentiment="positive" if i % 2 else "neutral",
            )
            for i, (slug, title, excerpt) in enumerate(budget)
        ]
        # Event 2: a fire in Prizren (left + right outlets) and a look-alike fire in Gjakovë.
        ids["fire_prizren"] = [
            article(
                s,
                src["majtas"],
                "Zjarr në një ndërtesë banimi në Prizren",
                t0 + timedelta(hours=1),
                excerpt="Zjarrfikësit e Prizrenit shuan zjarrin pa të lënduar.",
                entities=[("Prizren", "location")],
                topic="accidents_disasters",
                sentiment="negative",
            ),
            article(
                s,
                src["djathtas"],
                "Përfshihet nga zjarri një ndërtesë banimi në Prizren",
                t0 + timedelta(hours=2),
                excerpt="Zjarri në ndërtesën e banimit në Prizren u shua pa të lënduar.",
                entities=[("Prizren", "location")],
                topic="accidents_disasters",
                sentiment="negative",
            ),
        ]
        ids["fire_gjakove"] = article(
            s,
            src["qendra"],
            "Zjarr në një ndërtesë banimi në Gjakovë",
            t0 + timedelta(hours=3),
            excerpt="Zjarrfikësit e Gjakovës shuan zjarrin pa të lënduar.",
            entities=[("Gjakovë", "location")],
            topic="accidents_disasters",
            sentiment="negative",
        )
        # Event 3: about Albania, covered by three Kosovo outlets and no Albanian one.
        ids["tirana_story"] = [
            article(
                s,
                src[slug],
                title,
                t0 + timedelta(hours=4, minutes=10 * i),
                excerpt="Kryeministri shqiptar njoftoi reformën në Tiranë.",
                entities=[("Tiranë", "location")],
                countries=["AL"],
            )
            for i, (slug, title) in enumerate(
                [
                    ("majtas", "Tirana njofton reformën e re në arsim"),
                    ("qendra", "Reforma e re në arsim, njoftimi nga Tirana"),
                    ("djathtas", "Tirana prezanton reformën në arsim"),
                ]
            )
        ]
        # A near-verbatim copy (dedup L4) joins its original's story.
        ids["copy"] = article(
            s,
            src["majtas"],
            "VIDEO: Kuvendi miraton buxhetin për vitin 2027",
            t0 + timedelta(hours=5),
            entities=[("Kuvendi", "organization")],
            duplicate_of=ids["budget"][0],
        )
        # The same headline four days later is a different story (outside the 48 h window).
        ids["later"] = article(
            s,
            src["qendra"],
            "Kuvendi miraton buxhetin për vitin 2027",
            t0 - timedelta(days=4),
            excerpt="Me 61 vota për, Kuvendi i Kosovës miratoi buxhetin e vitit 2027.",
            entities=[("Kuvendi", "organization")],
        )
    return ids


def story_of(db: sessionmaker[Session], article_id: int) -> int | None:
    with db() as s:
        return s.scalar(select(Article.story_id).where(Article.id == article_id))


# =============================================================================================
# CLUSTER stage
# =============================================================================================
def test_clustering_groups_paraphrases_and_separates_lookalikes(
    db: sessionmaker[Session], settings: Settings, newsroom: dict[str, Any]
) -> None:
    with db() as s:
        stats = cluster_pending(s, settings)
    assert stats.considered == 12
    budget = {story_of(db, i) for i in newsroom["budget"]}
    assert len(budget) == 1 and None not in budget
    assert story_of(db, newsroom["copy"]) in budget
    assert stats.via_duplicate == 1
    prizren = {story_of(db, i) for i in newsroom["fire_prizren"]}
    assert len(prizren) == 1
    assert story_of(db, newsroom["fire_gjakove"]) not in prizren | budget
    assert len({story_of(db, i) for i in newsroom["tirana_story"]}) == 1
    assert story_of(db, newsroom["later"]) not in budget  # outside the story window

    with db() as s:  # idempotent: nothing left to do
        assert cluster_pending(s, settings).considered == 0
        story = s.get(Story, budget.pop())
        assert story is not None
        assert story.primary_topic_id is not None
        assert story.published_date == story.first_published_at.astimezone(TZ).date()
        assert story.representative_article_id in newsroom["budget"] + [newsroom["copy"]]


LOOKALIKES = [  # (place a, place b, headline template)
    ("Prizren", "Gjakovë", "Zjarr në një ndërtesë banimi në {}"),
    ("Pejë", "Prizren", "Gjykata në {} dënon ish-zyrtarin për korrupsion"),
    ("Ferizaj", "Gjilan", "Aksident trafiku në {}, një i vdekur"),
]


def unanalysed(s: Session, source: Source, title: str, at: datetime, *, waited: bool) -> int:
    """An article whose analysis has not run (budget spent, kill switch): no entities yet."""
    art = Article(
        source_id=source.id,
        url=f"https://{source.slug}.example.com/{sha256_hex(title)[:12]}",
        canonical_url="x",
        url_hash=sha256_hex(title, source.slug),
        title=title,
        title_normalized=normalize_key(title),
        title_hash=sha256_hex(title),
        language="sq",
        published_at=at,
        published_date=at.astimezone(TZ).date(),
        content_hash=sha256_hex(title),
        ingested_at=at if waited else NOW,
    )
    s.add(art)
    s.flush()
    return art.id


def test_clustering_waits_for_the_analysis_and_keeps_lookalikes_apart_without_one(
    db: sessionmaker[Session], settings: Settings
) -> None:
    pairs: list[tuple[int, int]] = []
    with db() as s, s.begin():
        a, b, old = rated_source(s, "qendra"), rated_source(s, "djathtas"), add_source(s, "arkiv")
        # Earlier analyses typed the towns as places (the lexicon an unanalysed article uses).
        towns = sorted({p for pair in LOOKALIKES for p in pair[:2]})
        for i, town in enumerate(towns):
            title = f"Komuna e {town} hap tenderin për rrugët"
            article(s, old, title, NOW - timedelta(days=5, hours=i), entities=[(town, "location")])
        t = NOW - timedelta(hours=10)  # waited longer than STORY_ENRICHMENT_WAIT_MINUTES
        for i, (place_a, place_b, headline) in enumerate(LOOKALIKES):
            at = t + timedelta(hours=i)
            pairs.append(
                (
                    unanalysed(s, a, headline.format(place_a), at, waited=True),
                    unanalysed(
                        s, b, headline.format(place_b), at + timedelta(minutes=20), waited=True
                    ),
                )
            )
        fresh = unanalysed(s, a, "Protestë para Kuvendit për pagat", NOW, waited=False)
    with db() as s:
        stats = cluster_pending(s, settings)
    assert stats.considered == len(towns) + len(LOOKALIKES) * 2  # the fresh article waits
    for left, right in pairs:
        assert story_of(db, left) is not None
        assert story_of(db, left) != story_of(db, right)
    assert story_of(db, fresh) is None

    with db() as s, s.begin():  # its analysis arrives: the next run clusters it
        s.execute(update(Article).where(Article.id == fresh).values(enrichment_status="succeeded"))
    with db() as s:
        assert cluster_pending(s, settings).considered == 1
    assert story_of(db, fresh) is not None


def test_clustering_does_not_wait_when_analysis_is_turned_off(
    db: sessionmaker[Session], settings: Settings
) -> None:
    with db() as s, s.begin():
        fresh = unanalysed(s, add_source(s, "qendra"), "Protestë para Kuvendit", NOW, waited=False)
    with db() as s:
        cluster_pending(s, settings.model_copy(update={"enrichment_enabled": False}))
    assert story_of(db, fresh) is not None


def test_rebuild_reclusters_with_a_new_threshold(
    db: sessionmaker[Session], settings: Settings, newsroom: dict[str, Any]
) -> None:
    with db() as s:
        cluster_pending(s, settings)
    since = (NOW - timedelta(days=2)).astimezone(TZ).date()
    strict = settings.model_copy(update={"story_similarity_threshold": 0.99})
    with db() as s:
        result = rebuild(s, strict, since)
    assert result["articles_released"] == 11  # everything but the article four days earlier
    assert result["stories_deleted"] >= 1
    # With an (absurdly) strict threshold, only the near-verbatim copy still joins a story.
    assert len({story_of(db, i) for i in newsroom["budget"]}) == 4


def test_review_report_lists_stories_weak_members_and_near_misses(
    db: sessionmaker[Session], settings: Settings, newsroom: dict[str, Any]
) -> None:
    with db() as s:
        cluster_pending(s, settings)
    with db() as s:
        report = review_report(s, settings, hours=48)
    assert "### Multi-outlet stories" in report and "outlets" in report
    assert "`qendra` Kuvendi miraton buxhetin për vitin 2027" in report
    assert "### Weakest members" in report
    # the Gjakovë fire is the closest miss of the Prizren fire, kept apart by the name guard
    near = report.split("### Near misses")[1]
    assert "| places |" in near and "Gjakovë" in near
    assert "kritikoi" not in report  # headlines only, never excerpts


def test_story_backlog_check(
    db: sessionmaker[Session], settings: Settings, newsroom: dict[str, Any]
) -> None:
    with db() as s, s.begin():
        s.execute(update(Article).values(ingested_at=NOW - timedelta(hours=3)))
        assert check_story_backlog(s).observed == 12
    with db() as s:
        cluster_pending(s, settings)
    with db() as s, s.begin():
        result = check_story_backlog(s)
    assert result.status == "pass" and result.observed == 0
    with db() as s, s.begin():  # waiting for its analysis is not a backlog, yet
        waiting = unanalysed(s, add_source(s, "arkiv"), "Protestë", NOW, waited=False)
        s.execute(
            update(Article)
            .where(Article.id == waiting)
            .values(ingested_at=NOW - timedelta(hours=3))
        )
        assert check_story_backlog(s).observed == 0
        s.execute(
            update(Article)
            .where(Article.id == waiting)
            .values(ingested_at=NOW - timedelta(hours=9))
        )
        assert check_story_backlog(s).observed == 1


# =============================================================================================
# Registry ratings
# =============================================================================================
def test_ratings_need_a_basis_and_valid_values() -> None:
    base = {
        "slug": "x-source",
        "name": "X",
        "homepage_url": "https://x.example.com/",
        "language": "sq",
        "country": "XK",
    }
    with pytest.raises(ValidationError, match="ratings_note"):
        SourceConfig(**base, enabled=False, bias="left")
    with pytest.raises(ValidationError, match="bias must be one of"):
        SourceConfig(**base, enabled=False, bias="far_left", ratings_note="x")
    with pytest.raises(ValidationError, match="ownership must be one of"):
        SourceConfig(**base, enabled=False, ownership="oligarch")
    ok = SourceConfig(**base, enabled=False, ownership="nonprofit", owner="BIRN")
    assert ok.bias == "unrated" and ok.factuality == "unrated"


def test_sync_writes_and_updates_ratings(session: Session) -> None:
    cfg = {
        "slug": "rated",
        "name": "Rated",
        "homepage_url": "https://rated.example.com/",
        "feed_url": "https://rated.example.com/feed/",
        "language": "sq",
        "country": "XK",
    }
    sync_sources(session, Registry(sources=[SourceConfig(**cfg)]))
    row = session.scalar(select(Source).where(Source.slug == "rated"))
    assert row is not None and (row.bias, row.ownership) == ("unrated", "unknown")
    rated = SourceConfig(
        **cfg, bias="center", factuality="high", ownership="private", ratings_note="Review 2026"
    )
    assert sync_sources(session, Registry(sources=[rated]))["updated"] == 1
    session.refresh(row)
    assert (row.bias, row.factuality, row.ownership, row.ratings_note) == (
        "center",
        "high",
        "private",
        "Review 2026",
    )


# =============================================================================================
# API
# =============================================================================================
@pytest.fixture
def client(db: sessionmaker[Session], settings: Settings) -> TestClient:
    app_settings = settings.model_copy(
        update={
            "api_cache_ttl_seconds": 0,
            "rate_limit_per_minute": 10_000,
            "rate_limit_search_per_minute": 10_000,
        }
    )
    return TestClient(create_app(app_settings, db))


@pytest.fixture
def clustered(
    db: sessionmaker[Session], settings: Settings, newsroom: dict[str, Any]
) -> dict[str, Any]:
    with db() as s:
        cluster_pending(s, settings)
    return {**newsroom, "budget_story": story_of(db, newsroom["budget"][0])}


def test_story_feed_coverage_and_filters(client: TestClient, clustered: dict[str, Any]) -> None:
    body = client.get("/api/v1/stories", params={"days": 3, "min_sources": 2}).json()
    assert body["total"] == 3  # budget, Prizren fire, Tirana reform
    top = body["items"][0]
    assert top["id"] == clustered["budget_story"]
    # four outlets' paraphrases + the left outlet's near-verbatim copy
    assert (top["source_count"], top["article_count"]) == (5, 5)
    assert top["coverage"]["bias"] == {"left": 1, "center": 1, "right": 2, "unrated": 1}
    assert top["coverage"]["factuality"] == {"high": 3, "mixed": 1, "low": 0, "unrated": 1}
    assert top["coverage"]["region"] == {"XK": 3, "AL": 1, "MK": 1}
    assert top["coverage"]["ownership"]["media_group"] == 1
    assert top["first_source_slug"] == "qendra"
    assert sum(top["tone"].values()) == 5
    assert {s["slug"] for s in top["sources"]} == {
        "qendra",
        "djathtas",
        "tirana",
        "pavleresuar",
        "majtas",
    }

    latest = client.get("/api/v1/stories", params={"days": 3, "sort": "latest"}).json()
    times = [i["last_published_at"] for i in latest["items"]]
    assert times == sorted(times, reverse=True)
    searched = client.get("/api/v1/stories", params={"days": 3, "q": "zjarr"}).json()
    assert {i["title"] for i in searched["items"]} >= {"Zjarr në një ndërtesë banimi në Gjakovë"}
    assert all("zjarr" in normalize_key(i["title"]) for i in searched["items"])
    albania = client.get("/api/v1/stories", params={"days": 3, "country": "AL"}).json()
    assert [i["id"] for i in albania["items"]] == [clustered["budget_story"]]
    by_source = client.get("/api/v1/stories", params={"days": 3, "source": "tirana"}).json()
    assert by_source["total"] == 1
    by_topic = client.get("/api/v1/stories", params={"days": 3, "topic": "economy"}).json()
    assert [i["id"] for i in by_topic["items"]] == [clustered["budget_story"]]
    assert client.get("/api/v1/stories", params={"country": "Kosovo"}).status_code == 422


def test_hidden_articles_leave_story_counts(
    client: TestClient, db: sessionmaker[Session], clustered: dict[str, Any]
) -> None:
    with db() as s, s.begin():
        s.execute(
            update(Article)
            .where(Article.id == clustered["budget"][3])
            .values(is_hidden=True, hidden_reason="takedown")
        )
    detail = client.get(f"/api/v1/stories/{clustered['budget_story']}").json()
    assert detail["source_count"] == 4
    assert detail["coverage"]["bias"]["unrated"] == 0
    assert clustered["budget"][3] not in {a["id"] for a in detail["articles"]}


def test_story_detail(client: TestClient, clustered: dict[str, Any]) -> None:
    resp = client.get(f"/api/v1/stories/{clustered['budget_story']}")
    assert resp.status_code == 200
    body = resp.json()
    articles = body["articles"]
    assert [a["is_first"] for a in articles].count(True) == 1 and articles[0]["is_first"]
    assert articles[0]["source_slug"] == "qendra" and articles[0]["source_bias"] == "center"
    assert [a["published_at"] for a in articles] == sorted(a["published_at"] for a in articles)
    assert any(e["name"] == "Kuvendi" and e["articles"] == 5 for e in body["entities"])
    assert {t["slug"] for t in body["topics"]} == {"politics", "economy"}
    assert '"excerpt"' not in resp.text and "kritikoi" not in resp.text  # excerpts never leak
    assert client.get("/api/v1/stories/999999").status_code == 404
    assert client.get("/api/v1/stories/0").status_code == 422


def test_blindspots(client: TestClient, clustered: dict[str, Any]) -> None:
    body = client.get("/api/v1/stories/blindspots", params={"days": 3}).json()
    assert "Perspective blindspot" in body["method"]
    found = {i["id"]: i["blindspots"] for i in body["items"]}
    # Budget: rated outlets = 1 left (the copy), 1 center, 2 right → right 50%: no blindspot.
    assert clustered["budget_story"] not in found
    tirana_story = client.get(f"/api/v1/articles/{clustered['tirana_story'][0]}").json()
    # About Albania (every article names AL), three Kosovo outlets, no Albanian outlet covered it.
    assert {"kind": "region", "missing": "AL"} in found[tirana_story["story_id"]]
    only_perspective = client.get(
        "/api/v1/stories/blindspots", params={"days": 3, "kind": "perspective"}
    ).json()
    assert all(
        b["kind"] == "perspective" for i in only_perspective["items"] for b in i["blindspots"]
    )


def test_perspective_blindspot(
    client: TestClient, db: sessionmaker[Session], settings: Settings, clustered: dict[str, Any]
) -> None:
    # Without the left outlet's copy, the budget story is a blindspot for the left.
    with db() as s, s.begin():
        s.execute(
            update(Article)
            .where(Article.story_id == clustered["budget_story"])
            .where(Article.source_id.in_(select(Source.id).where(Source.slug == "majtas")))
            .values(is_hidden=True)
        )
    body = client.get("/api/v1/stories/blindspots", params={"days": 3}).json()
    found = {i["id"]: i["blindspots"] for i in body["items"]}
    # rated: center 1, right 2 → right 67% ≥ 60%, left 0% ≤ 15%
    assert {"kind": "perspective", "missing": "left"} in found[clustered["budget_story"]]


def test_article_links_to_its_story(client: TestClient, clustered: dict[str, Any]) -> None:
    detail = client.get(f"/api/v1/articles/{clustered['budget'][1]}").json()
    assert detail["story_id"] == clustered["budget_story"]
    # "Same story elsewhere" now lists the other outlets' paraphrases, not only verbatim copies.
    assert {r["id"] for r in detail["related"]} >= set(clustered["budget"]) - {
        clustered["budget"][1]
    }
    listed = client.get("/api/v1/articles", params={"days": 3}).json()["items"]
    assert all(a["story_id"] is not None for a in listed)


def test_source_profile_and_compare(client: TestClient, clustered: dict[str, Any]) -> None:
    resp = client.get("/api/v1/sources/qendra", params={"days": 7})
    assert resp.status_code == 200
    body = resp.json()
    assert (body["bias"], body["factuality"], body["ownership"]) == (
        "center",
        "very_high",
        "public",
    )
    assert body["first_reports"] >= 1  # it published the budget story first
    assert body["stories"] == 4  # budget, Gjakovë fire, Tirana reform, the older budget vote
    assert body["exclusives"] == 2  # the Gjakovë fire and the vote four days earlier
    assert 0 < body["coverage_share"] <= 1
    assert {o["slug"] for o in body["overlap"]} >= {"djathtas", "tirana"}
    assert all(
        "qendra" in {x["slug"] for x in story["sources"]} for story in body["recent_stories"]
    )
    assert client.get("/api/v1/sources/does-not-exist").status_code == 404

    rows = {r["slug"]: r for r in client.get("/api/v1/sources", params={"days": 7}).json()}
    assert rows["qendra"]["bias"] == "center" and rows["qendra"]["first_reports"] >= 1
    assert rows["pavleresuar"]["bias"] == "unrated"
    assert rows["djathtas"]["stories"] == 3


def test_link_preview_carries_the_story_and_escapes_it(
    client: TestClient, db: sessionmaker[Session], clustered: dict[str, Any]
) -> None:
    story_id = clustered["budget_story"]
    resp = client.get(f"/api/share/stories/{story_id}")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/html")
    assert resp.headers["cache-control"] == "public, max-age=300"
    detail = client.get(f"/api/v1/stories/{story_id}").json()
    assert (
        f'<meta property="og:url" content="http://localhost:5173/stories/{story_id}">' in resp.text
    )
    assert f"{detail['source_count']} media e raportuan këtë lajm: " in resp.text
    assert '<html lang="sq">' in resp.text
    # the Albanian summary leads; the English one never appears in an Albanian preview
    assert 'content="Përmbledhje: ' in resp.text and "Summary:" not in resp.text
    assert "kritikoi" not in resp.text  # metadata only: never excerpt text
    assert "og:title" in resp.text and escape_attr(detail["title"]) in resp.text

    # a hostile headline is text, never markup
    with db() as s, s.begin():
        s.execute(
            update(Article)
            .where(Article.story_id == story_id)
            .values(title='Buxheti "><script>alert(1)</script>')
        )
    hostile = client.get(f"/api/share/stories/{story_id}").text
    assert "<script>" not in hostile and "&lt;script&gt;" in hostile

    missing = client.get("/api/share/stories/999999")
    assert missing.status_code == 404 and 'content="http://localhost:5173/"' in missing.text


def test_sitemap_lists_pages_outlets_topics_and_multi_outlet_stories(
    client: TestClient, db: sessionmaker[Session], clustered: dict[str, Any]
) -> None:
    resp = client.get("/api/share/sitemap.xml")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("application/xml")
    assert resp.headers["cache-control"] == "public, max-age=3600"
    xml = resp.text
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<loc>http://localhost:5173/</loc>" in xml and "/blindspot</loc>" in xml
    budget = clustered["budget_story"]
    assert f"<loc>http://localhost:5173/stories/{budget}</loc><lastmod>" in xml
    single = story_of(db, clustered["fire_gjakove"])
    assert f"/stories/{single}<" not in xml  # one outlet: no comparison to offer
    assert "/sources/qendra</loc>" in xml and "/topics/politics</loc>" in xml


def escape_attr(value: str) -> str:
    from html import escape

    return escape(value, quote=True)
