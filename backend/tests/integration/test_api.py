from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from gjurme.api.app import create_app
from gjurme.config import Settings
from gjurme.db.models import Article, PipelineRun
from gjurme.enrichment.schema import EnrichmentOutput
from gjurme.enrichment.service import apply_output
from gjurme.ingestion.normalize import normalize_key, sha256_hex
from gjurme.runtime_settings import ENRICHMENT_PAUSE, RUN_REQUEST, get_setting
from tests.integration.helpers import add_source

pytestmark = pytest.mark.integration
TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TZ = ZoneInfo("Europe/Tirane")


def today() -> date:
    return datetime.now(TZ).date()


def make_article(
    s: Session,
    source_id: int,
    title: str,
    day: date,
    *,
    topic: str = "politics",
    sentiment: str = "neutral",
    score: float = 0.0,
    entities: list[tuple[str, str]] | None = None,
    hidden: bool = False,
    hour: int = 10,
) -> int:
    published = datetime(day.year, day.month, day.day, hour, tzinfo=TZ).astimezone(UTC)
    art = Article(
        source_id=source_id,
        url=f"https://x.example.com/{sha256_hex(title, str(day))}",
        canonical_url="x",
        url_hash=sha256_hex(title, str(day), str(source_id)),
        title=title,
        title_normalized=normalize_key(title),
        title_hash=sha256_hex(title),
        excerpt="SECRET-EXCERPT publisher text",
        language="sq",
        published_at=published,
        published_date=day,
        content_hash=sha256_hex(title),
        is_hidden=hidden,
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
            sentiment_score=score,
            event_type="other",
            summary_en=f"Summary of {title}",
            entities=[{"name": n, "type": t} for n, t in (entities or [])],
            countries=["XK"],
            confidence=0.9,
        ),
    )
    return art.id


@pytest.fixture
def dataset(db: sessionmaker[Session]) -> dict[str, Any]:
    t = today()
    ids: dict[str, Any] = {}
    with db() as s, s.begin():
        a = add_source(s, "alfa")
        b = add_source(s, "beta")
        # Elections: 2 articles in the previous week, 8 in the current week → accelerating.
        for i in range(8):
            make_article(
                s,
                a.id if i % 2 else b.id,
                f"Zgjedhjet lajmi {i}",
                t - timedelta(days=i % 7),
                topic="elections",
                sentiment="positive",
                score=0.5,
                entities=[("KQZ", "organization")],
            )
        for i in range(2):
            make_article(
                s, a.id, f"Zgjedhjet e vjetra {i}", t - timedelta(days=8 + i), topic="elections"
            )
        # Crime: negative.
        for i in range(5):
            make_article(
                s,
                b.id,
                f"Arrestim në Prizren {i}",
                t - timedelta(days=i),
                topic="crime_justice",
                sentiment="negative",
                score=-0.6,
                entities=[("Policia e Kosovës", "organization"), ("Prizren", "location")],
            )
        # A person spiking today (6 mentions today, none before).
        for i in range(6):
            make_article(
                s,
                a.id,
                f"Drita Berisha deklaratë {i}",
                t,
                hour=8 + i,
                entities=[("Drita Berisha", "person"), ("KQZ", "organization")],
            )
        ids["hidden"] = make_article(
            s,
            a.id,
            "Artikull i fshehur pas kërkesës",
            t,
            entities=[("Drita Berisha", "person")],
            hidden=True,
        )
        ids["visible"] = make_article(
            s, b.id, "Artikull i dukshëm për Prizren", t, entities=[("Prizren", "location")]
        )
        s.add(
            PipelineRun(
                trigger="schedule",
                stages=["ingest"],
                status="succeeded",
                started_at=datetime.now(UTC) - timedelta(minutes=5),
                finished_at=datetime.now(UTC) - timedelta(minutes=4),
            )
        )
    return ids


@pytest.fixture
def api_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "admin_api_token": SecretStr(TOKEN),
            "api_cache_ttl_seconds": 0,
            "rate_limit_per_minute": 10_000,
            "rate_limit_search_per_minute": 10_000,
            "cors_origins": ["https://gjurme.example"],
        }
    )


@pytest.fixture
def client(db: sessionmaker[Session], api_settings: Settings) -> TestClient:
    return TestClient(create_app(api_settings, db))


# ------------------------------------------------------------------------------------------
def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/health/ready").json()
    assert ready["database"] is True and ready["migrations"] == "0001"


def test_ready_reports_database_down(api_settings: Settings) -> None:
    def broken() -> Session:
        raise RuntimeError("db down")

    app = create_app(api_settings, broken)  # type: ignore[arg-type]
    resp = TestClient(app).get("/health/ready")
    assert resp.status_code == 503 and resp.json()["database"] is False


def test_overview_numbers(client: TestClient, dataset: dict[str, Any]) -> None:
    body = client.get("/api/v1/analytics/overview", params={"days": 7}).json()
    # 8 elections + 5 crime + 6 person + 1 visible = 20 in the last 7 days (hidden excluded)
    assert body["articles"] == 20
    # elections i=0 and i=7 (7 % 7 == 0), crime i=0, 6 person articles, the visible one
    assert body["today"] == 2 + 1 + 6 + 1
    assert body["top_topic"]["slug"] == "elections"
    assert body["sentiment"]["negative"] == 5 and body["sentiment"]["positive"] == 8
    assert body["articles_total"] == 22  # hidden excluded


def test_topic_momentum(client: TestClient, dataset: dict[str, Any]) -> None:
    body = client.get("/api/v1/analytics/trends/topics").json()
    elections = next(i for i in body["items"] if i["slug"] == "elections")
    assert elections == {
        "slug": "elections",
        "name_en": "Elections",
        "current": 8,
        "previous": 2,
        "growth": pytest.approx((8 - 2) / 5),
    }
    assert "max(previous, 5)" in body["method"]


def test_entity_spike(client: TestClient, dataset: dict[str, Any]) -> None:
    items = client.get("/api/v1/analytics/trends/entities").json()["items"]
    drita = next(i for i in items if i["name"] == "Drita Berisha")
    assert drita["last_24h"] == 6 and drita["is_spike"] and drita["z"] == 6.0


def test_topics_and_detail(client: TestClient, dataset: dict[str, Any]) -> None:
    topics = client.get("/api/v1/topics", params={"days": 7}).json()
    assert topics[0]["slug"] in ("elections", "politics")
    assert len(topics) == 19  # every taxonomy topic is listed, zero-filled
    detail = client.get("/api/v1/topics/crime_justice", params={"days": 7}).json()
    assert sum(p["articles"] for p in detail["series"]) == 5
    assert {e["name"] for e in detail["top_entities"]} == {"Policia e Kosovës", "Prizren"}
    assert client.get("/api/v1/topics/nonexistent").status_code == 404


def test_entities_list_detail_and_search(client: TestClient, dataset: dict[str, Any]) -> None:
    people = client.get("/api/v1/entities", params={"type": "person", "days": 7}).json()
    assert [p["name"] for p in people] == ["Drita Berisha"]
    assert people[0]["mentions"] == 6  # hidden article not counted
    found = client.get("/api/v1/entities", params={"q": "prizr"}).json()
    assert found[0]["name"] == "Prizren"
    detail = client.get(f"/api/v1/entities/{found[0]['id']}", params={"days": 7}).json()
    assert detail["mentions"] == 6
    assert {c["name"] for c in detail["co_mentions"]} == {"Policia e Kosovës"}


def test_articles_search_filters_and_never_leaks_excerpt(
    client: TestClient, dataset: dict[str, Any]
) -> None:
    resp = client.get("/api/v1/articles", params={"q": "Arrestim", "page_size": 2})
    body = resp.json()
    assert body["total"] == 5 and body["pages"] == 3 and len(body["items"]) == 2
    assert "SECRET-EXCERPT" not in resp.text and "excerpt" not in resp.text
    neg = client.get("/api/v1/articles", params={"sentiment": "negative"}).json()
    assert neg["total"] == 5
    by_topic = client.get("/api/v1/articles", params={"topic": "elections", "days": 7}).json()
    assert by_topic["total"] == 8
    by_source = client.get("/api/v1/articles", params={"source": "beta", "days": 30}).json()
    assert all(i["source_slug"] == "beta" for i in by_source["items"])
    oldest = client.get("/api/v1/articles", params={"sort": "oldest"}).json()["items"][0]
    assert oldest["title"].startswith("Zgjedhjet e vjetra")


def test_hidden_article_is_invisible(client: TestClient, dataset: dict[str, Any]) -> None:
    assert client.get(f"/api/v1/articles/{dataset['hidden']}").status_code == 404
    detail = client.get(f"/api/v1/articles/{dataset['visible']}")
    assert detail.status_code == 200 and "SECRET-EXCERPT" not in detail.text
    listed = client.get("/api/v1/articles", params={"q": "fshehur"}).json()
    assert listed["total"] == 0


def test_sources_compare(client: TestClient, dataset: dict[str, Any]) -> None:
    rows = {r["slug"]: r for r in client.get("/api/v1/sources", params={"days": 7}).json()}
    assert rows["beta"]["negative"] == 5
    assert rows["alfa"]["articles"] + rows["beta"]["articles"] == 20


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"from": "2026-09-10", "to": "2026-09-01"}, "invalid_range"),
        ({"from": "2020-01-01", "to": "2026-01-01"}, "invalid_range"),
        ({"to": "2099-01-01"}, "invalid_range"),
        ({"days": 0}, "validation_error"),
        ({"source": "BAD SLUG!"}, "invalid_source"),
    ],
)
def test_invalid_ranges(client: TestClient, params: dict[str, Any], code: str) -> None:
    resp = client.get("/api/v1/analytics/overview", params=params)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == code


def test_invalid_article_params(client: TestClient) -> None:
    for params in (
        {"page_size": 1000},
        {"page": 0},
        {"sort": "random"},
        {"q": "x"},
        {"sentiment": "angry"},
        {"topic": "DROP TABLE"},
    ):
        resp = client.get("/api/v1/articles", params=params)
        assert resp.status_code == 422, params


def test_sql_injection_attempt_is_inert(client: TestClient, dataset: dict[str, Any]) -> None:
    resp = client.get("/api/v1/articles", params={"q": "' OR 1=1; DROP TABLE core.articles; --"})
    assert resp.status_code == 200 and resp.json()["total"] == 0
    assert client.get("/api/v1/articles").json()["total"] == 22


def test_security_and_cache_headers(client: TestClient) -> None:
    resp = client.get("/api/v1/topics")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["cache-control"].startswith("public, max-age=60")
    assert len(resp.headers["x-request-id"]) >= 8
    assert client.get("/api/v1/status").headers["cache-control"] == "no-store"
    rid = client.get("/health", headers={"X-Request-ID": "trace-12345678"})
    assert rid.headers["x-request-id"] == "trace-12345678"


def test_cors(client: TestClient) -> None:
    ok = client.options(
        "/api/v1/topics",
        headers={"Origin": "https://gjurme.example", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "https://gjurme.example"
    bad = client.options(
        "/api/v1/topics",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers


def test_rate_limit(db: sessionmaker[Session], api_settings: Settings) -> None:
    app = create_app(api_settings.model_copy(update={"rate_limit_per_minute": 3}), db)
    c = TestClient(app)
    codes = [c.get("/api/v1/topics/taxonomy").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    limited = c.get("/api/v1/topics/taxonomy")
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) >= 1
    assert c.get("/health").status_code == 200  # health is never rate limited


def test_admin_requires_token(client: TestClient, db, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/admin/runs").status_code == 401
    assert (
        client.get("/api/v1/admin/runs", headers={"Authorization": "Bearer nope"}).status_code
        == 401
    )
    no_token = TestClient(create_app(settings, db))
    assert no_token.get("/api/v1/admin/runs", headers=AUTH).status_code == 503


def test_admin_actions(client: TestClient, db, dataset: dict[str, Any]) -> None:  # type: ignore[no-untyped-def]
    runs = client.get("/api/v1/admin/runs", headers=AUTH).json()
    assert runs[0]["status"] == "succeeded"
    assert client.post("/api/v1/admin/pipeline/run", headers=AUTH).status_code == 202
    assert client.post(
        "/api/v1/admin/enrichment/pause", headers=AUTH, json={"reason": "budget review"}
    ).json() == {"paused": True}
    assert (
        client.post("/api/v1/admin/enrichment/pause", headers=AUTH, json={"reason": ""}).status_code
        == 422
    )
    with db() as s:
        assert get_setting(s, RUN_REQUEST)["pending"] is True  # type: ignore[index]
        assert get_setting(s, ENRICHMENT_PAUSE)["paused"] is True  # type: ignore[index]
    costs = client.get("/api/v1/admin/costs", headers=AUTH).json()
    assert costs["enrichment_paused"] is True and costs["daily_budget_usd"] == 5.0

    visible = dataset["visible"]
    assert (
        client.post(
            f"/api/v1/admin/articles/{visible}/hide",
            headers=AUTH,
            json={"reason": "publisher request"},
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/articles/{visible}").status_code == 404
    client.post(f"/api/v1/admin/articles/{visible}/unhide", headers=AUTH)
    assert client.get(f"/api/v1/articles/{visible}").status_code == 200
    assert (
        client.post(f"/api/v1/admin/articles/{visible}/reenrich", headers=AUTH).status_code == 202
    )
    with db() as s:
        art = s.get(Article, visible)
        assert art is not None and art.enrichment_status == "pending"

    assert (
        client.post(
            "/api/v1/admin/sources/alfa/disable", headers=AUTH, json={"reason": "terms review"}
        ).json()["is_active"]
        is False
    )
    assert client.post("/api/v1/admin/sources/zzz/enable", headers=AUTH).status_code == 404
    assert isinstance(client.get("/api/v1/admin/failures", headers=AUTH).json()["enrichment"], list)


def test_metrics_access(client: TestClient, dataset: dict[str, Any]) -> None:
    direct = client.get("/metrics")
    assert direct.status_code == 200 and "gjurme_articles_ingested_24h" in direct.text
    proxied = client.get("/metrics", headers={"X-Forwarded-For": "8.8.8.8"})
    assert proxied.status_code == 401
    assert client.get("/metrics", headers={**AUTH, "X-Forwarded-For": "8.8.8.8"}).status_code == 200


def test_public_status(client: TestClient, dataset: dict[str, Any]) -> None:
    body = client.get("/api/v1/status").json()
    assert body["last_run_status"] == "succeeded" and body["status"] in ("ok", "degraded")
    assert body["minutes_since_success"] < 10


def test_openapi_documents_every_public_route(client: TestClient) -> None:
    spec = client.get("/api/openapi.json").json()
    paths = set(spec["paths"])
    for expected in (
        "/api/v1/analytics/overview",
        "/api/v1/articles",
        "/api/v1/entities/{entity_id}",
        "/api/v1/topics/{slug}",
        "/api/v1/sources",
        "/api/v1/status",
        "/api/v1/admin/costs",
    ):
        assert expected in paths
    assert client.get("/api/docs").status_code == 200


def test_unhandled_errors_do_not_leak(
    db,
    api_settings: Settings,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gjurme.analytics.queries as q

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("password=hunter2 in stack trace")

    monkeypatch.setattr(q, "topics", boom)
    c = TestClient(create_app(api_settings, db), raise_server_exceptions=False)
    resp = c.get("/api/v1/topics")
    assert resp.status_code == 500 and "hunter2" not in resp.text
    assert resp.json()["error"]["code"] == "internal_error"


def test_cache_invalidated_by_admin_mutation(
    db,
    api_settings: Settings,  # type: ignore[no-untyped-def]
    dataset: dict[str, Any],
) -> None:
    c = TestClient(create_app(api_settings.model_copy(update={"api_cache_ttl_seconds": 600}), db))
    before = c.get("/api/v1/analytics/overview", params={"days": 7}).json()["articles"]
    c.post(
        f"/api/v1/admin/articles/{dataset['visible']}/hide",
        headers=AUTH,
        json={"reason": "takedown"},
    )
    after = c.get("/api/v1/analytics/overview", params={"days": 7}).json()["articles"]
    assert after == before - 1
    with db() as s:
        assert s.scalar(select(Article.is_hidden).where(Article.id == dataset["visible"]))


def test_volume_and_sentiment_series(client: TestClient, dataset: dict[str, Any]) -> None:
    vol = client.get("/api/v1/analytics/volume", params={"days": 7}).json()
    assert len(vol["series"]) == 7  # gap-filled
    assert sum(p["articles"] for p in vol["series"]) == 20
    assert vol["series"][-1]["ma7"] == pytest.approx(20 / 7, abs=0.01)
    grouped = client.get("/api/v1/analytics/volume", params={"days": 7, "group_by": "source"})
    assert {p["key"] for p in grouped.json()["series"]} == {"alfa", "beta"}
    by_topic = client.get("/api/v1/analytics/volume", params={"days": 7, "group_by": "topic"})
    assert "elections" in {p["key"] for p in by_topic.json()["series"]}
    sent = client.get("/api/v1/analytics/sentiment", params={"days": 7}).json()
    assert sum(p["negative"] for p in sent["series"]) == 5
    groups = client.get(
        "/api/v1/analytics/sentiment", params={"days": 7, "group_by": "topic"}
    ).json()["groups"]
    assert groups[0]["key"] == "crime_justice" and groups[0]["average"] == -0.6
    shift = client.get("/api/v1/analytics/sentiment/shift").json()
    assert "window_days" in shift and "method" in shift


def test_cooccurrence(client: TestClient, dataset: dict[str, Any]) -> None:
    pairs = client.get("/api/v1/analytics/cooccurrence", params={"days": 7}).json()
    names = {frozenset((p["a_name"], p["b_name"])): p["together"] for p in pairs}
    assert names[frozenset(("Drita Berisha", "KQZ"))] == 6
    assert names[frozenset(("Policia e Kosovës", "Prizren"))] == 5


def test_taxonomy(client: TestClient) -> None:
    topics = client.get("/api/v1/topics/taxonomy").json()
    assert [t["slug"] for t in topics][:3] == ["politics", "elections", "kosovo_serbia"]
