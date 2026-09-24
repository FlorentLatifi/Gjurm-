"""Analytics query benchmark at production scale.

Creates a scratch database, applies the real migrations, bulk-generates N articles (default
365k ≈ one year at 1,000 articles/day) with topics, sentiment and ~3 entity mentions each using
set-based SQL, then times every analytics query the API exposes (median / p95 over several runs)
using the same engine settings as the API.

    uv run python scripts/benchmark.py --url postgresql+psycopg://postgres@localhost:5433/postgres \
        --articles 365000

Results are recorded in docs/TESTING.md#performance.
"""

from __future__ import annotations

import argparse
import statistics
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from gjurme.analytics import queries as q
from gjurme.cli import alembic_config
from gjurme.db.reference import sync_topics
from gjurme.db.session import build_engine

DB = "gjurme_benchmark"


def setup(admin_url: str, articles: int) -> str:
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"))
        c.execute(text(f"CREATE DATABASE {DB}"))
    admin.dispose()
    url = admin_url.rsplit("/", 1)[0] + f"/{DB}"
    command.upgrade(alembic_config(url), "head")
    eng = create_engine(url)
    t0 = time.perf_counter()
    with eng.begin() as c:
        sync_topics(Session(bind=c))
        c.execute(
            text("""
            INSERT INTO core.sources (slug, name, homepage_url, feed_url, language, country)
            SELECT 'src-' || g, 'Source ' || g, 'https://s' || g || '.example.com/',
                   'https://s' || g || '.example.com/feed', 'sq', 'XK'
            FROM generate_series(1, 8) g""")
        )
        c.execute(
            text("""
            INSERT INTO core.entities (type, name, normalized_key)
            SELECT (ARRAY['person','organization','location'])[1 + g % 3], 'Entity ' || g,
                   'entity ' || g
            FROM generate_series(1, 5000) g""")
        )
        # Articles spread over 365 days; skewed topics; sentiment correlated with topic.
        c.execute(
            text("""
            INSERT INTO core.articles (source_id, url, canonical_url, url_hash, title,
                title_normalized, title_hash, language, published_at, published_date,
                content_hash, enrichment_status, primary_topic_id, sentiment_label,
                sentiment_score, summary_en, enriched_at, duplicate_of_id)
            SELECT 1 + (g % 8), 'https://x.example.com/' || g, 'https://x.example.com/' || g,
                   md5(g::text) || md5((g + 1)::text), 'Lajmi numër ' || g || ' për temën',
                   'lajmi numer ' || g || ' per temen ' || (g % 97), md5('t' || g), 'sq',
                   ts, (ts AT TIME ZONE 'Europe/Tirane')::date, md5('c' || g), 'succeeded',
                   1 + floor(power(random(), 2) * 19)::int, s.label, s.score,
                   'Summary ' || g, ts, NULL
            FROM generate_series(1, :n) g
            -- NB: the lateral subqueries must reference g, otherwise PostgreSQL evaluates the
            -- uncorrelated random() once and every row gets the same value.
            CROSS JOIN LATERAL (
                SELECT now() - ((g % 365) + random()) * interval '1 day' AS ts) t
            CROSS JOIN LATERAL (
                SELECT CASE WHEN r < 0.35 THEN 'negative' WHEN r < 0.7 THEN 'neutral'
                            ELSE 'positive' END AS label,
                       round((r * 2 - 1)::numeric, 3) AS score
                FROM (SELECT random() + g * 0 AS r) x) s"""),
            {"n": articles},
        )
        dist = c.execute(
            text("""
            SELECT count(DISTINCT published_date) AS days,
                   count(DISTINCT sentiment_label) AS labels,
                   count(DISTINCT primary_topic_id) AS topics FROM core.articles""")
        ).one()
        if not (dist.days >= 360 and dist.labels == 3 and dist.topics >= 15):
            raise SystemExit(f"generated data is not varied enough: {dist}")
        c.execute(
            text("""
            INSERT INTO core.article_topics (article_id, topic_id, is_primary)
            SELECT id, primary_topic_id, true FROM core.articles""")
        )
        # ~3 mentions per article, Zipf-like popularity (a few entities are very frequent).
        c.execute(
            text("""
            INSERT INTO core.article_entities (article_id, entity_id)
            SELECT DISTINCT a.id, 1 + floor(power(random() + k * 0 + a.id * 0, 3) * 4999)::int
            FROM core.articles a CROSS JOIN generate_series(1, 3) k
            ON CONFLICT DO NOTHING""")
        )
        c.execute(text("ANALYZE"))
    print(f"generated {articles:,} articles in {time.perf_counter() - t0:.1f}s")
    eng.dispose()
    return url


def timed(fn: Callable[[], Any], runs: int) -> tuple[float, float]:
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return statistics.median(samples), samples[min(len(samples) - 1, int(len(samples) * 0.95))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="admin URL (database is created/dropped)")
    ap.add_argument("--articles", type=int, default=365_000)
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--skip-setup", action="store_true")
    args = ap.parse_args()
    url = (
        (args.url.rsplit("/", 1)[0] + f"/{DB}")
        if args.skip_setup
        else setup(args.url, args.articles)
    )
    # The production engine factory: same session settings (statement timeout, plan cache mode)
    # as the API, so the numbers reflect what the deployed service runs.
    factory = sessionmaker(bind=build_engine(url, statement_timeout_ms=120_000))
    today = datetime.now(UTC).date()
    r30 = q.Range(today - timedelta(days=29), today)
    r7 = q.Range(today - timedelta(days=6), today)
    r365 = q.Range(today - timedelta(days=364), today)
    with factory() as s:
        eid = s.execute(
            text(
                "SELECT entity_id FROM core.article_entities GROUP BY 1 "
                "ORDER BY count(*) DESC LIMIT 1"
            )
        ).scalar_one()
        cases: dict[str, Callable[[], Any]] = {
            "overview 30d": lambda: q.overview(s, r30, today),
            "volume 30d": lambda: q.volume(s, r30),
            "volume 365d by topic": lambda: q.volume(s, r365, "topic"),
            "topics 30d": lambda: q.topics(s, r30),
            "topic momentum": lambda: q.topic_momentum(s, today),
            "topic detail 30d": lambda: q.topic_detail(s, "politics", r30),
            "top entities 7d": lambda: q.top_entities(s, r7, entity_type=None),
            "top entities 30d": lambda: q.top_entities(s, r30, entity_type="person"),
            "entity search 30d": lambda: q.top_entities(s, r30, entity_type=None, q="entity 12"),
            "entity spikes": lambda: q.entity_spikes(s, datetime.now(UTC)),
            "entity detail 30d (top)": lambda: q.entity_detail(s, eid, r30),
            "co-occurrence 7d": lambda: q.co_occurrence(s, r7),
            "sentiment series 30d": lambda: q.sentiment_series(s, r30),
            "sentiment by source 30d": lambda: q.sentiment_series(s, r30, "source"),
            "sentiment shift": lambda: q.sentiment_shift(s, today),
            "sources compare 30d": lambda: q.sources_compare(s, r30),
            "articles page 1": lambda: q.search_articles(
                s,
                r30,
                q=None,
                topic=None,
                entity_id=None,
                sentiment=None,
                sort="newest",
                limit=20,
                offset=0,
            ),
            "articles keyword": lambda: q.search_articles(
                s,
                r30,
                q="numer 12345",
                topic=None,
                entity_id=None,
                sentiment=None,
                sort="newest",
                limit=20,
                offset=0,
            ),
            "articles by entity": lambda: q.search_articles(
                s,
                r30,
                q=None,
                topic=None,
                entity_id=eid,
                sentiment=None,
                sort="newest",
                limit=20,
                offset=0,
            ),
        }
        print(f"\n{'query':<28}{'median ms':>12}{'p95 ms':>10}")
        for name, fn in cases.items():
            med, p95 = timed(fn, args.runs)
            print(f"{name:<28}{med:>12.1f}{p95:>10.1f}")


if __name__ == "__main__":
    main()
