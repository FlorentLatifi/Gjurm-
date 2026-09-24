from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from gjurme.config import Settings
from gjurme.db.models import Article, FeedFetch, FeedItem, Source
from gjurme.ingestion.ingest import ingest_all
from gjurme.ingestion.processor import process_pending
from tests.conftest import feed_server, fixture_bytes
from tests.integration.helpers import add_source, pubdate, rss

pytestmark = pytest.mark.integration


def _count(s: Session, model: type) -> int:
    return int(s.scalar(select(func.count()).select_from(model)) or 0)


def test_ingest_is_idempotent_and_isolates_failures(
    db: sessionmaker[Session], settings: Settings, make_fetcher
) -> None:
    with db() as s, s.begin():
        add_source(s, "good", "https://good.example.com/feed/")
        add_source(s, "broken", "https://broken.example.com/feed/")
        add_source(s, "html", "https://html.example.com/feed/")
    handler = feed_server(
        {
            "https://good.example.com/feed/": (200, fixture_bytes("wordpress_sq.xml"), {}),
            "https://broken.example.com/feed/": (500, b"oops", {}),
            "https://html.example.com/feed/": (200, fixture_bytes("not_a_feed.html"), {}),
        }
    )
    fetcher = make_fetcher(handler)

    first = ingest_all(db, fetcher, settings)
    by_slug = {x.slug: x for x in first.sources}
    assert by_slug["good"].status == "ok" and by_slug["good"].items_new == 3
    assert by_slug["broken"].status == "http_error"
    assert by_slug["html"].status == "parse_error"

    second = ingest_all(db, fetcher, settings)
    assert {x.slug: x.items_new for x in second.sources}["good"] == 0

    with db() as s:
        assert _count(s, FeedItem) == 3
        assert _count(s, FeedFetch) == 6
        broken = s.scalar(select(Source).where(Source.slug == "broken"))
        assert broken is not None and broken.consecutive_failures == 2 and broken.is_active


def test_not_modified_keeps_validators_and_counts_as_success(db, settings, make_fetcher) -> None:
    with db() as s, s.begin():
        add_source(s, "cond", "https://cond.example.com/feed/")
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.headers))
        if request.headers.get("if-none-match") == '"abc"':
            return httpx.Response(304)
        return httpx.Response(200, content=fixture_bytes("atom.xml"), headers={"etag": '"abc"'})

    fetcher = make_fetcher(handler)
    ingest_all(db, fetcher, settings)
    stats = ingest_all(db, fetcher, settings)
    assert stats.sources[0].status == "not_modified"
    with db() as s:
        src = s.scalar(select(Source))
        assert src is not None and src.etag == '"abc"' and src.consecutive_failures == 0


def test_source_auto_disabled_after_threshold(db, settings, make_fetcher) -> None:
    with db() as s, s.begin():
        add_source(s, "dead", "https://dead.example.com/feed/")
    fetcher = make_fetcher(feed_server({}))  # everything 404
    cfg = settings.model_copy(update={"source_failure_disable_threshold": 3})
    for _ in range(3):
        stats = ingest_all(db, fetcher, cfg)
    assert stats.sources[0].auto_disabled
    with db() as s:
        src = s.scalar(select(Source))
        assert (
            src is not None and not src.is_active and "auto-disabled" in (src.disabled_reason or "")
        )
    assert ingest_all(db, fetcher, cfg).sources == []  # disabled sources are skipped


def test_changed_item_is_requeued(db, settings, make_fetcher) -> None:
    with db() as s, s.begin():
        add_source(s, "src", "https://src.example.com/feed/")
    body = {
        "v": rss(
            [
                {
                    "title": "Titulli i parë i lajmit",
                    "link": "https://src.example.com/a",
                    "guid": "g1",
                    "pubDate": pubdate(),
                }
            ]
        )
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body["v"])

    fetcher = make_fetcher(handler)
    ingest_all(db, fetcher, settings)
    with db() as s:
        process_pending(s, settings)
    body["v"] = rss(
        [
            {
                "title": "Titulli i korrigjuar i lajmit",
                "link": "https://src.example.com/a",
                "guid": "g1",
                "pubDate": pubdate(),
            }
        ]
    )
    stats = ingest_all(db, fetcher, settings)
    assert stats.sources[0].items_changed == 1
    with db() as s:
        result = process_pending(s, settings)
        assert result.updated == 1
        art = s.scalar(select(Article))
        assert art is not None and art.title == "Titulli i korrigjuar i lajmit"
        assert _count(s, Article) == 1


def _ingest_items(db, settings, make_fetcher, feeds: dict[str, list[dict[str, str]]]) -> None:
    routes = {}
    with db() as s, s.begin():
        for slug, items in feeds.items():
            url = f"https://{slug}.example.com/feed/"
            add_source(s, slug, url)
            routes[url] = (200, rss(items), {})
    ingest_all(db, make_fetcher(feed_server(routes)), settings)


def test_process_accepts_rejects_and_dedups(db, settings, make_fetcher) -> None:
    title = "Qeveria miraton projektligjin e ri për energjinë dhe tarifat"
    _ingest_items(
        db,
        settings,
        make_fetcher,
        {
            "alpha": [
                {
                    "title": title,
                    "link": "https://alpha.example.com/a1?utm_source=rss",
                    "guid": "a1",
                    "pubDate": pubdate(2),
                    "description": "<p>Përshkrimi.</p>",
                },
                # L2: same canonical URL, different guid
                {
                    "title": title,
                    "link": "https://www.alpha.example.com/a1/",
                    "guid": "a1-copy",
                    "pubDate": pubdate(2),
                },
                # L3: same title, same source, new slug within 48 h
                {
                    "title": title,
                    "link": "https://alpha.example.com/a1-edited",
                    "guid": "a1-b",
                    "pubDate": pubdate(1),
                },
                {"title": "", "link": "https://alpha.example.com/empty", "guid": "e"},
                # no <link> and no <guid>: nothing to link to (a bare <guid> would be a permalink)
                {"title": "Lajm pa lidhje", "pubDate": pubdate(1)},
                {
                    "title": "Lajm me lidhje të rrezikshme",
                    "link": "javascript:alert(1)",
                    "guid": "js",
                    "pubDate": pubdate(1),
                },
                {
                    "title": "Lajm shumë i vjetër nga arkivi",
                    "link": "https://alpha.example.com/old",
                    "guid": "old",
                    "pubDate": "Mon, 01 Jan 2024 10:00:00 +0000",
                },
                {
                    "title": "Lajm pa datë publikimi fare",
                    "link": "https://alpha.example.com/nodate",
                    "guid": "nd",
                },
            ],
            # L4: another outlet, near-identical headline → kept, linked
            "beta": [
                {
                    "title": title.replace("ri ", "ri, ") + "!",
                    "link": "https://beta.example.com/x",
                    "guid": "b1",
                    "pubDate": pubdate(1),
                }
            ],
        },
    )
    with db() as s:
        stats = process_pending(s, settings)
    assert stats.accepted == 3  # alpha a1, alpha nodate, beta x
    assert stats.duplicates == {"l2_url": 1, "l3_title": 1}
    assert stats.rejected == {"missing_title": 1, "missing_url": 1, "invalid_url": 1, "too_old": 1}
    assert stats.date_issues["missing_date"] == 1
    assert stats.near_duplicates == 1

    with db() as s:
        alpha = s.scalar(select(Article).where(Article.url.like("%alpha%a1%")))
        beta = s.scalar(select(Article).where(Article.url.like("%beta%")))
        nodate = s.scalar(select(Article).where(Article.url.like("%nodate")))
        assert alpha and beta and nodate
        assert alpha.url == "https://alpha.example.com/a1"  # tracking removed
        assert alpha.excerpt == "Përshkrimi."
        assert beta.duplicate_of_id == alpha.id
        assert nodate.published_at_estimated
        reasons = dict(
            s.execute(
                select(FeedItem.guid, FeedItem.rejection_reason).where(FeedItem.guid.is_not(None))
            ).all()
        )
        assert reasons["js"].startswith("invalid_url")
        # nothing left unprocessed, nothing silently dropped
        assert s.scalar(select(func.count()).where(FeedItem.processed_at.is_(None))) == 0

    with db() as s:  # rerun: idempotent
        again = process_pending(s, settings)
        assert again.processed == 0
        assert _count(s, Article) == 3


def test_published_date_uses_local_timezone(db, settings, make_fetcher) -> None:
    # 23:30 UTC on 23 Sep is 01:30 on 24 Sep in Europe/Tirane (CEST, UTC+2)
    ts = datetime.now(UTC).replace(hour=23, minute=30, second=0, microsecond=0) - timedelta(days=1)
    _ingest_items(
        db,
        settings,
        make_fetcher,
        {
            "tz": [
                {
                    "title": "Lajm i publikuar pas mesnatës",
                    "link": "https://tz.example.com/1",
                    "guid": "t1",
                    "pubDate": ts.strftime("%a, %d %b %Y %H:%M:%S +0000"),
                }
            ]
        },
    )
    with db() as s:
        process_pending(s, settings)
        art = s.scalar(select(Article))
        assert art is not None
        assert (
            art.published_date == (ts + timedelta(hours=2)).date()
            or art.published_date == (ts + timedelta(hours=1)).date()
        )
        assert art.published_date != ts.date()


def test_unicode_survives_round_trip(db, settings, make_fetcher) -> None:
    with db() as s, s.begin():
        add_source(s, "moji", "https://moji.example.com/feed/")
    ingest_all(
        db,
        make_fetcher(
            feed_server(
                {"https://moji.example.com/feed/": (200, fixture_bytes("mojibake.xml"), {})}
            )
        ),
        settings,
    )
    with db() as s:
        stats = process_pending(s, settings)
        art = s.scalar(select(Article))
    assert stats.accepted == 1 and art is not None
    assert art.title == "Kosovë dhe Shqipëri nënshkruajnë marrëveshje për energjinë"
    assert art.excerpt == "Ministrja tha se çmimet do të ulen."
