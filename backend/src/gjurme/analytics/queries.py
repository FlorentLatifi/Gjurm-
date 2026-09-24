"""Analytical queries — one function per question the product answers.

All queries:
* are parameterized SQL (no string interpolation of user input);
* filter on ``published_date`` (the local calendar day in Europe/Tirane), which is indexed;
* exclude articles hidden by takedown (``NOT is_hidden``);
* return plain dicts that the API maps onto typed response models.

Trend methods are deliberately transparent statistics (see docs/ARCHITECTURE.md#analytics);
each trend function returns a ``method`` string that the dashboard shows as an explanation.
"""

# ruff: noqa: S608
# f-strings in this module only splice *static* SQL fragments (the shared WHERE clause, a
# whitelisted ORDER BY from SORTS, a group-by column chosen from a fixed dict). Every user-provided
# value is passed as a bound parameter. The API layer additionally validates all inputs.
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from gjurme.ingestion.normalize import normalize_key


@dataclass(frozen=True, slots=True)
class Range:
    start: date
    end: date
    sources: tuple[str, ...] = ()

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous(self) -> Range:
        """The equally long window immediately before this one (for period-over-period)."""
        return Range(
            self.start - timedelta(days=self.days), self.start - timedelta(days=1), self.sources
        )

    def params(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "sources": list(self.sources),
            "all_sources": not self.sources,
        }


# Common WHERE fragment for articles aliased ``a`` joined to sources ``s``.
WHERE = """
    a.published_date BETWEEN :start AND :end
    AND NOT a.is_hidden
    AND (:all_sources OR s.slug = ANY(:sources))
"""


def _rows(session: Session, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in session.execute(text(sql), params)]


def _f(value: Any, digits: int = 3) -> float | None:
    return None if value is None else round(float(value), digits)


# =============================================================================================
# Overview
# =============================================================================================
def overview(session: Session, rng: Range, today: date) -> dict[str, Any]:
    p = {**rng.params(), "today": today, "yesterday": today - timedelta(days=1)}
    head = (
        session.execute(
            text(f"""
        SELECT
          count(*)                                                  AS articles,
          count(DISTINCT coalesce(a.duplicate_of_id, a.id))         AS unique_stories,
          count(*) FILTER (WHERE a.published_date = :today)         AS today,
          count(*) FILTER (WHERE a.published_date = :yesterday)     AS yesterday,
          count(DISTINCT a.source_id)                               AS sources,
          count(*) FILTER (WHERE a.enrichment_status = 'succeeded') AS enriched,
          count(*) FILTER (WHERE a.sentiment_label = 'negative')    AS negative,
          count(*) FILTER (WHERE a.sentiment_label = 'neutral')     AS neutral,
          count(*) FILTER (WHERE a.sentiment_label = 'positive')    AS positive,
          avg(a.sentiment_score)                                    AS avg_sentiment,
          max(a.ingested_at)                                        AS last_ingested_at
        FROM core.articles a JOIN core.sources s ON s.id = a.source_id
        WHERE {WHERE}
    """),
            p,
        )
        .one()
        ._mapping
    )
    total = session.execute(
        text("SELECT count(*) FROM core.articles WHERE NOT is_hidden")
    ).scalar_one()
    top_topic = _rows(
        session,
        f"""
        SELECT t.slug, t.name_en, count(*) AS articles
        FROM core.articles a JOIN core.sources s ON s.id = a.source_id
        JOIN core.topics t ON t.id = a.primary_topic_id
        WHERE {WHERE}
        GROUP BY t.slug, t.name_en ORDER BY articles DESC, t.slug LIMIT 1
    """,
        p,
    )
    top_entity = top_entities(session, rng, entity_type=None, limit=1)
    enriched = head["enriched"] or 0
    return {
        "range": {"start": rng.start, "end": rng.end, "days": rng.days},
        "articles_total": total,
        "articles": head["articles"],
        "unique_stories": head["unique_stories"],
        "today": head["today"],
        "yesterday": head["yesterday"],
        "sources": head["sources"],
        "enriched": enriched,
        "enriched_share": _f(enriched / head["articles"]) if head["articles"] else None,
        "sentiment": {
            "negative": head["negative"],
            "neutral": head["neutral"],
            "positive": head["positive"],
            "average": _f(head["avg_sentiment"]),
        },
        "top_topic": (
            {**top_topic[0], "share": _f(top_topic[0]["articles"] / enriched) if enriched else None}
            if top_topic
            else None
        ),
        "top_entity": top_entity[0] if top_entity else None,
        "last_ingested_at": head["last_ingested_at"],
    }


# =============================================================================================
# Volume
# =============================================================================================
def volume(session: Session, rng: Range, group_by: str | None = None) -> dict[str, Any]:
    """Daily article counts with gap filling and a trailing 7-day moving average."""
    if group_by is None:
        rows = _rows(
            session,
            f"""
            WITH days AS (SELECT d::date AS day FROM generate_series(:start, :end,
                                                                     interval '1 day') d),
                 counts AS (
                   SELECT a.published_date AS day, count(*) AS n,
                          count(DISTINCT coalesce(a.duplicate_of_id, a.id)) AS stories
                   FROM core.articles a JOIN core.sources s ON s.id = a.source_id
                   WHERE {WHERE} GROUP BY 1)
            SELECT days.day, coalesce(c.n, 0) AS articles, coalesce(c.stories, 0) AS stories,
                   round(avg(coalesce(c.n, 0)) OVER (ORDER BY days.day
                         ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS ma7
            FROM days LEFT JOIN counts c USING (day) ORDER BY days.day
        """,
            rng.params(),
        )
        return {
            "series": [{**r, "ma7": _f(r["ma7"], 2)} for r in rows],
            "method": "Daily count of articles by local publication date; ma7 is the "
            "trailing 7-day mean (days without articles count as 0).",
        }
    key = {"source": "s.slug", "topic": "t.slug"}[group_by]
    rows = _rows(
        session,
        f"""
        SELECT a.published_date AS day, {key} AS key, count(*) AS articles
        FROM core.articles a JOIN core.sources s ON s.id = a.source_id
        LEFT JOIN core.topics t ON t.id = a.primary_topic_id
        WHERE {WHERE} AND {key} IS NOT NULL
        GROUP BY 1, 2 ORDER BY 1, 2
    """,
        rng.params(),
    )
    return {
        "series": rows,
        "group_by": group_by,
        "method": f"Daily article count per {group_by} (primary topic for topics).",
    }


# =============================================================================================
# Topics
# =============================================================================================
def topics(session: Session, rng: Range) -> list[dict[str, Any]]:
    prev = rng.previous()
    return [
        {
            **r,
            "share": _f(r["share"]),
            "avg_sentiment": _f(r["avg_sentiment"]),
            "change": _f((r["articles"] - r["previous"]) / max(r["previous"], 5)),
        }
        for r in _rows(
            session,
            f"""
            WITH cur AS (
              SELECT a.primary_topic_id AS topic_id, count(*) AS n,
                     avg(a.sentiment_score) AS avg_sentiment,
                     count(*) FILTER (WHERE a.sentiment_label = 'negative') AS negative,
                     count(*) FILTER (WHERE a.sentiment_label = 'positive') AS positive
              FROM core.articles a JOIN core.sources s ON s.id = a.source_id
              WHERE {WHERE} AND a.primary_topic_id IS NOT NULL GROUP BY 1),
            prev AS (
              SELECT a.primary_topic_id AS topic_id, count(*) AS n
              FROM core.articles a JOIN core.sources s ON s.id = a.source_id
              WHERE a.published_date BETWEEN :pstart AND :pend AND NOT a.is_hidden
                AND (:all_sources OR s.slug = ANY(:sources))
                AND a.primary_topic_id IS NOT NULL GROUP BY 1),
            total AS (SELECT sum(n) AS n FROM cur)
            SELECT t.slug, t.name_en, t.name_sq, coalesce(cur.n, 0) AS articles,
                   coalesce(prev.n, 0) AS previous,
                   coalesce(cur.n, 0)::numeric / nullif(total.n, 0) AS share,
                   cur.avg_sentiment, coalesce(cur.negative, 0) AS negative,
                   coalesce(cur.positive, 0) AS positive
            FROM core.topics t CROSS JOIN total
            LEFT JOIN cur ON cur.topic_id = t.id LEFT JOIN prev ON prev.topic_id = t.id
            ORDER BY articles DESC, t.sort_order
        """,
            {**rng.params(), "pstart": prev.start, "pend": prev.end},
        )
    ]


def topic_momentum(
    session: Session,
    today: date,
    *,
    window: int = 7,
    min_articles: int = 5,
    sources: tuple[str, ...] = (),
) -> dict[str, Any]:
    cur = Range(today - timedelta(days=window - 1), today, sources)
    rows = [r for r in topics(session, cur) if r["articles"] >= min_articles]
    rows.sort(key=lambda r: r["change"] or 0, reverse=True)
    return {
        "window_days": window,
        "items": [
            {
                "slug": r["slug"],
                "name_en": r["name_en"],
                "current": r["articles"],
                "previous": r["previous"],
                "growth": r["change"],
            }
            for r in rows
        ],
        "method": (
            f"growth = (current − previous) / max(previous, 5), comparing the last "
            f"{window} days with the {window} days before; topics with fewer than "
            f"{min_articles} articles are omitted. The floor of 5 keeps tiny counts "
            "from producing huge percentages."
        ),
    }


def topic_detail(session: Session, slug: str, rng: Range) -> dict[str, Any] | None:
    topic = session.execute(
        text("SELECT id, slug, name_en, name_sq, description FROM core.topics WHERE slug = :slug"),
        {"slug": slug},
    ).first()
    if topic is None:
        return None
    p = {**rng.params(), "topic_id": topic.id}
    series = _rows(
        session,
        f"""
        WITH days AS (SELECT d::date AS day FROM generate_series(:start, :end, interval '1 day') d),
             c AS (SELECT a.published_date AS day, count(*) AS n, avg(a.sentiment_score) AS s
                   FROM core.articles a JOIN core.sources s ON s.id = a.source_id
                   JOIN core.article_topics at ON at.article_id = a.id AND at.topic_id = :topic_id
                    AND at.published_date BETWEEN :start AND :end
                   WHERE {WHERE} GROUP BY 1)
        SELECT days.day, coalesce(c.n, 0) AS articles, c.s AS avg_sentiment
        FROM days LEFT JOIN c USING (day) ORDER BY days.day
    """,
        p,
    )
    entities = _rows(
        session,
        f"""
        SELECT e.id, e.name, e.type, count(*) AS mentions
        FROM core.articles a JOIN core.sources s ON s.id = a.source_id
        JOIN core.article_topics at ON at.article_id = a.id AND at.topic_id = :topic_id
                    AND at.published_date BETWEEN :start AND :end
        JOIN core.article_entities ae ON ae.article_id = a.id
        JOIN core.entities e ON e.id = ae.entity_id
        WHERE {WHERE} GROUP BY e.id, e.name, e.type ORDER BY mentions DESC, e.name, e.id LIMIT 15
    """,
        p,
    )
    by_source = _rows(
        session,
        f"""
        SELECT s.slug, s.name, count(*) AS articles, avg(a.sentiment_score) AS avg_sentiment
        FROM core.articles a JOIN core.sources s ON s.id = a.source_id
        JOIN core.article_topics at ON at.article_id = a.id AND at.topic_id = :topic_id
                    AND at.published_date BETWEEN :start AND :end
        WHERE {WHERE} GROUP BY s.slug, s.name ORDER BY articles DESC, s.slug
    """,
        p,
    )
    return {
        "topic": dict(topic._mapping),
        "series": [{**r, "avg_sentiment": _f(r["avg_sentiment"])} for r in series],
        "top_entities": entities,
        "sources": [{**r, "avg_sentiment": _f(r["avg_sentiment"])} for r in by_source],
    }


# =============================================================================================
# Entities
# =============================================================================================
def top_entities(
    session: Session,
    rng: Range,
    *,
    entity_type: str | None,
    limit: int = 20,
    q: str | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    prev = rng.previous()
    key = normalize_key(q) if q else None
    # Type/name filters apply before aggregation; the join is omitted when there is nothing to
    # filter (it would cost one lookup per mention). Only fixed SQL fragments are composed.
    entity_filter = (
        """JOIN core.entities e ON e.id = ae.entity_id
               AND (CAST(:etype AS text) IS NULL OR e.type = :etype)
               AND (CAST(:key AS text) IS NULL OR e.normalized_key LIKE '%' || :key || '%')"""
        if entity_type or key
        else ""
    )
    rows = _rows(
        session,
        f"""
        -- Two-level aggregate (entity, source) -> entity instead of count(DISTINCT): hashable,
        -- no sort spill. The previous period is only computed for the page being returned.
        WITH per_source AS (
          SELECT ae.entity_id, a.source_id, count(*) AS n,
                 sum(a.sentiment_score) AS s_sum, count(a.sentiment_score) AS s_n
          FROM core.articles a JOIN core.sources s ON s.id = a.source_id
          JOIN core.article_entities ae ON ae.article_id = a.id
               AND ae.published_date BETWEEN :start AND :end
          {entity_filter}
          WHERE {WHERE} GROUP BY 1, 2),
        page AS (
          SELECT e.id, e.name, e.type, sum(p.n)::int AS mentions,
                 sum(p.s_sum) / nullif(sum(p.s_n), 0) AS avg_sentiment, count(*) AS sources
          FROM per_source p JOIN core.entities e ON e.id = p.entity_id
          GROUP BY e.id ORDER BY mentions DESC, e.name, e.id LIMIT :limit OFFSET :offset),
        prev AS (
          SELECT ae.entity_id, count(*) AS n
          FROM core.articles a JOIN core.sources s ON s.id = a.source_id
          JOIN core.article_entities ae ON ae.article_id = a.id
               AND ae.published_date BETWEEN :pstart AND :pend
               AND ae.entity_id IN (SELECT id FROM page)
          WHERE a.published_date BETWEEN :pstart AND :pend AND NOT a.is_hidden
            AND (:all_sources OR s.slug = ANY(:sources)) GROUP BY 1)
        SELECT page.*, coalesce(prev.n, 0) AS previous
        FROM page LEFT JOIN prev ON prev.entity_id = page.id
        ORDER BY page.mentions DESC, page.name, page.id
    """,
        {
            **rng.params(),
            "pstart": prev.start,
            "pend": prev.end,
            "etype": entity_type,
            "key": key,
            "limit": limit,
            "offset": offset,
        },
    )
    return [
        {
            **r,
            "avg_sentiment": _f(r["avg_sentiment"]),
            "change": _f((r["mentions"] - r["previous"]) / max(r["previous"], 3)),
        }
        for r in rows
    ]


def entity_spikes(
    session: Session,
    as_of: datetime,
    *,
    baseline_days: int = 28,
    min_mentions: int = 5,
    z_threshold: float = 3.0,
    limit: int = 10,
) -> dict[str, Any]:
    rows = _rows(
        session,
        """
        WITH recent AS (
          SELECT ae.entity_id, count(*) AS x
          FROM core.article_entities ae JOIN core.articles a ON a.id = ae.article_id
          WHERE ae.published_date >= CAST(:as_of AS date) - 2
            AND a.published_at > :as_of - interval '24 hours' AND a.published_at <= :as_of
            AND NOT a.is_hidden
          GROUP BY 1 HAVING count(*) >= :min),
        -- Baseline only for candidates that can qualify (not for every entity).
        base AS (
          SELECT ae.entity_id, a.published_at::date AS d, count(*) AS n
          FROM core.article_entities ae JOIN core.articles a ON a.id = ae.article_id
          WHERE ae.published_date >= CAST(:as_of AS date) - (:bdays + 3)
            AND a.published_at > :as_of - make_interval(days => :bdays + 1)
            AND a.published_at <= :as_of - interval '24 hours' AND NOT a.is_hidden
            AND ae.entity_id IN (SELECT entity_id FROM recent)
          GROUP BY 1, 2),
        stats AS (
          SELECT entity_id, sum(n)::numeric / :bdays AS mean,
                 sqrt(greatest(sum(n * n)::numeric / :bdays - (sum(n)::numeric / :bdays) ^ 2, 0))
                   AS std
          FROM base GROUP BY 1)
        SELECT e.id, e.name, e.type, r.x AS last_24h,
               coalesce(st.mean, 0) AS baseline_mean, coalesce(st.std, 0) AS baseline_std,
               (r.x - coalesce(st.mean, 0)) / greatest(coalesce(st.std, 0), 1) AS z
        FROM recent r JOIN core.entities e ON e.id = r.entity_id
        LEFT JOIN stats st ON st.entity_id = r.entity_id
        ORDER BY z DESC, r.x DESC, e.name, e.id LIMIT :limit
    """,
        {"as_of": as_of, "bdays": baseline_days, "min": min_mentions, "limit": limit},
    )
    items = [
        {
            **r,
            "baseline_mean": _f(r["baseline_mean"], 2),
            "baseline_std": _f(r["baseline_std"], 2),
            "z": _f(r["z"], 2),
            "is_spike": float(r["z"]) >= z_threshold,
        }
        for r in rows
    ]
    return {
        "as_of": as_of,
        "items": items,
        "method": (
            f"z = (mentions in the last 24 h − μ) / max(σ, 1), where μ and σ are the mean "
            f"and standard deviation of daily mentions over the previous {baseline_days} "
            f"days (days without mentions count as 0). A spike needs z ≥ {z_threshold:g} "
            f"and at least {min_mentions} mentions."
        ),
    }


def entity_detail(session: Session, entity_id: int, rng: Range) -> dict[str, Any] | None:
    entity = session.execute(
        text("SELECT id, name, type, first_seen_at FROM core.entities WHERE id = :id"),
        {"id": entity_id},
    ).first()
    if entity is None:
        return None
    p = {**rng.params(), "eid": entity_id}
    series = _rows(
        session,
        f"""
        WITH days AS (SELECT d::date AS day FROM generate_series(:start, :end, interval '1 day') d),
             c AS (SELECT a.published_date AS day, count(*) AS n, avg(a.sentiment_score) AS s
                   FROM core.articles a JOIN core.sources s ON s.id = a.source_id
                   JOIN core.article_entities ae ON ae.article_id = a.id AND ae.entity_id = :eid
                    AND ae.published_date BETWEEN :start AND :end
                   WHERE {WHERE} GROUP BY 1)
        SELECT days.day, coalesce(c.n, 0) AS mentions, c.s AS avg_sentiment
        FROM days LEFT JOIN c USING (day) ORDER BY days.day
    """,
        p,
    )
    related = _rows(
        session,
        f"""
        SELECT e.id, e.name, e.type, count(*) AS together
        FROM core.article_entities me
        JOIN core.articles a ON a.id = me.article_id
        JOIN core.sources s ON s.id = a.source_id
        JOIN core.article_entities o ON o.article_id = me.article_id AND o.entity_id <> me.entity_id
        JOIN core.entities e ON e.id = o.entity_id
        WHERE me.entity_id = :eid AND me.published_date BETWEEN :start AND :end
          AND o.published_date BETWEEN :start AND :end AND {WHERE}
        GROUP BY e.id, e.name, e.type ORDER BY together DESC, e.name, e.id LIMIT 12
    """,
        p,
    )
    topic_mix = _rows(
        session,
        f"""
        SELECT t.slug, t.name_en, count(*) AS articles
        FROM core.articles a JOIN core.sources s ON s.id = a.source_id
        JOIN core.article_entities ae ON ae.article_id = a.id AND ae.entity_id = :eid
                    AND ae.published_date BETWEEN :start AND :end
        JOIN core.topics t ON t.id = a.primary_topic_id
        WHERE {WHERE} GROUP BY t.slug, t.name_en ORDER BY articles DESC, t.slug
    """,
        p,
    )
    source_mix = _rows(
        session,
        f"""
        SELECT s.slug, s.name, count(*) AS articles, avg(a.sentiment_score) AS avg_sentiment
        FROM core.articles a JOIN core.sources s ON s.id = a.source_id
        JOIN core.article_entities ae ON ae.article_id = a.id AND ae.entity_id = :eid
                    AND ae.published_date BETWEEN :start AND :end
        WHERE {WHERE} GROUP BY s.slug, s.name ORDER BY articles DESC, s.slug
    """,
        p,
    )
    total = sum(r["mentions"] for r in series)
    sent = [r for r in series if r["avg_sentiment"] is not None]
    return {
        "entity": dict(entity._mapping),
        "mentions": total,
        "avg_sentiment": _f(sum(float(r["avg_sentiment"]) * r["mentions"] for r in sent) / total)
        if total and sent
        else None,
        "series": [{**r, "avg_sentiment": _f(r["avg_sentiment"])} for r in series],
        "co_mentions": related,
        "topics": topic_mix,
        "sources": [{**r, "avg_sentiment": _f(r["avg_sentiment"])} for r in source_mix],
    }


def co_occurrence(
    session: Session, rng: Range, *, limit: int = 30, min_count: int = 2
) -> list[dict[str, Any]]:
    return _rows(
        session,
        f"""
        -- Count pairs on ids first; names are joined only for the returned pairs.
        WITH pairs AS (
          SELECT x.entity_id AS a_id, y.entity_id AS b_id, count(*) AS together
          FROM core.articles a JOIN core.sources s ON s.id = a.source_id
          JOIN core.article_entities x ON x.article_id = a.id
               AND x.published_date BETWEEN :start AND :end
          JOIN core.article_entities y ON y.article_id = a.id AND x.entity_id < y.entity_id
               AND y.published_date BETWEEN :start AND :end
          WHERE {WHERE}
          GROUP BY 1, 2 HAVING count(*) >= :min)
        SELECT e1.id AS a_id, e1.name AS a_name, e1.type AS a_type,
               e2.id AS b_id, e2.name AS b_name, e2.type AS b_type, p.together
        FROM pairs p JOIN core.entities e1 ON e1.id = p.a_id
        JOIN core.entities e2 ON e2.id = p.b_id
        ORDER BY p.together DESC, e1.name, e2.name, e1.id, e2.id LIMIT :limit
    """,
        {**rng.params(), "limit": limit, "min": min_count},
    )


# =============================================================================================
# Sentiment
# =============================================================================================
def sentiment_series(session: Session, rng: Range, group_by: str | None = None) -> dict[str, Any]:
    if group_by is None:
        rows = _rows(
            session,
            f"""
            WITH days AS (SELECT d::date AS day FROM generate_series(:start, :end,
                                                                     interval '1 day') d),
                 c AS (SELECT a.published_date AS day,
                              count(*) FILTER (WHERE a.sentiment_label = 'negative') AS negative,
                              count(*) FILTER (WHERE a.sentiment_label = 'neutral') AS neutral,
                              count(*) FILTER (WHERE a.sentiment_label = 'positive') AS positive,
                              sum(a.sentiment_score) AS total, count(a.sentiment_score) AS n
                       FROM core.articles a JOIN core.sources s ON s.id = a.source_id
                       WHERE {WHERE} GROUP BY 1)
            SELECT days.day, coalesce(negative, 0) AS negative, coalesce(neutral, 0) AS neutral,
                   coalesce(positive, 0) AS positive,
                   total / nullif(n, 0) AS average,
                   sum(total) OVER w / nullif(sum(n) OVER w, 0) AS ma7
            FROM days LEFT JOIN c USING (day)
            WINDOW w AS (ORDER BY days.day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
            ORDER BY days.day
        """,
            rng.params(),
        )
        return {
            "series": [{**r, "average": _f(r["average"]), "ma7": _f(r["ma7"])} for r in rows],
            "method": "Mean sentiment score (−1…1) of enriched articles per day; ma7 is the "
            "article-weighted mean over the trailing 7 days.",
        }
    key = {"source": "s.slug", "topic": "t.slug"}[group_by]
    rows = _rows(
        session,
        f"""
        SELECT {key} AS key, count(a.sentiment_score) AS n, avg(a.sentiment_score) AS average,
               count(*) FILTER (WHERE a.sentiment_label = 'negative') AS negative,
               count(*) FILTER (WHERE a.sentiment_label = 'neutral') AS neutral,
               count(*) FILTER (WHERE a.sentiment_label = 'positive') AS positive
        FROM core.articles a JOIN core.sources s ON s.id = a.source_id
        LEFT JOIN core.topics t ON t.id = a.primary_topic_id
        WHERE {WHERE} AND a.sentiment_score IS NOT NULL AND {key} IS NOT NULL
        GROUP BY 1 ORDER BY average, 1
    """,
        rng.params(),
    )
    return {"groups": [{**r, "average": _f(r["average"])} for r in rows], "group_by": group_by}


def sentiment_shift(
    session: Session, today: date, *, window: int = 7, min_n: int = 5
) -> dict[str, Any]:
    cur = Range(today - timedelta(days=window - 1), today)
    prev = cur.previous()
    rows = _rows(
        session,
        """
        SELECT t.slug, t.name_en,
               avg(a.sentiment_score) FILTER (WHERE a.published_date BETWEEN :cs AND :ce) AS cur,
               count(a.sentiment_score)
                 FILTER (WHERE a.published_date BETWEEN :cs AND :ce) AS n_cur,
               avg(a.sentiment_score) FILTER (WHERE a.published_date BETWEEN :ps AND :pe) AS prev,
               count(a.sentiment_score)
                 FILTER (WHERE a.published_date BETWEEN :ps AND :pe) AS n_prev
        FROM core.articles a JOIN core.topics t ON t.id = a.primary_topic_id
        WHERE a.published_date BETWEEN :ps AND :ce AND NOT a.is_hidden
        GROUP BY t.slug, t.name_en
    """,
        {"cs": cur.start, "ce": cur.end, "ps": prev.start, "pe": prev.end},
    )
    items = [
        {
            "slug": r["slug"],
            "name_en": r["name_en"],
            "current": _f(r["cur"]),
            "previous": _f(r["prev"]),
            "n_current": r["n_cur"],
            "n_previous": r["n_prev"],
            "delta": _f(float(r["cur"]) - float(r["prev"])),
        }
        for r in rows
        if r["n_cur"] >= min_n and r["n_prev"] >= min_n
    ]
    items.sort(key=lambda r: abs(r["delta"] or 0), reverse=True)
    return {
        "window_days": window,
        "items": items,
        "method": f"Mean sentiment of the last {window} days minus the {window} days before, "
        f"per primary topic; both windows need at least {min_n} articles.",
    }


# =============================================================================================
# Sources
# =============================================================================================
def sources_compare(session: Session, rng: Range) -> list[dict[str, Any]]:
    rows = _rows(
        session,
        f"""
        WITH per AS (
          SELECT a.source_id, count(*) AS n,
                 count(*) FILTER (WHERE a.duplicate_of_id IS NULL) AS original,
                 avg(a.sentiment_score) AS avg_sentiment,
                 count(*) FILTER (WHERE a.sentiment_label = 'negative') AS negative,
                 count(*) FILTER (WHERE a.sentiment_label = 'neutral') AS neutral,
                 count(*) FILTER (WHERE a.sentiment_label = 'positive') AS positive,
                 max(a.published_at) AS last_article_at
          FROM core.articles a JOIN core.sources s ON s.id = a.source_id
          WHERE {WHERE} GROUP BY 1),
        topic_rank AS (
          SELECT a.source_id, t.slug, count(*) AS n,
                 row_number() OVER (PARTITION BY a.source_id ORDER BY count(*) DESC, t.slug) AS rk
          FROM core.articles a JOIN core.sources s ON s.id = a.source_id
          JOIN core.topics t ON t.id = a.primary_topic_id
          WHERE {WHERE} GROUP BY a.source_id, t.slug)
        SELECT s.slug, s.name, s.homepage_url, s.language, s.country, s.is_active,
               s.verification_status, s.last_success_at, s.consecutive_failures,
               coalesce(per.n, 0) AS articles, coalesce(per.original, 0) AS original,
               per.avg_sentiment, coalesce(per.negative, 0) AS negative,
               coalesce(per.neutral, 0) AS neutral, coalesce(per.positive, 0) AS positive,
               per.last_article_at,
               coalesce((SELECT json_agg(json_build_object('slug', tr.slug, 'articles', tr.n)
                                         ORDER BY tr.rk)
                         FROM topic_rank tr WHERE tr.source_id = s.id AND tr.rk <= 5),
                        '[]'::json) AS top_topics
        FROM core.sources s LEFT JOIN per ON per.source_id = s.id
        WHERE (:all_sources OR s.slug = ANY(:sources))
          AND (per.n IS NOT NULL OR s.is_active)
        ORDER BY articles DESC, s.name, s.slug
    """,
        rng.params(),
    )
    return [
        {**r, "avg_sentiment": _f(r["avg_sentiment"]), "per_day": _f(r["articles"] / rng.days, 1)}
        for r in rows
    ]


# =============================================================================================
# Articles
# =============================================================================================
SORTS = {"newest": "a.published_at DESC, a.id DESC", "oldest": "a.published_at ASC, a.id ASC"}


def search_articles(
    session: Session,
    rng: Range,
    *,
    q: str | None,
    topic: str | None,
    entity_id: int | None,
    sentiment: str | None,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[int, list[dict[str, Any]]]:
    key = normalize_key(q) if q else None
    params = {
        **rng.params(),
        "key": key,
        "topic": topic,
        "eid": entity_id,
        "sentiment": sentiment,
        "limit": limit,
        "offset": offset,
    }
    where = f"""{WHERE}
        AND (CAST(:key AS text) IS NULL OR a.title_normalized LIKE '%' || :key || '%')
        AND (CAST(:sentiment AS text) IS NULL OR a.sentiment_label = :sentiment)
        AND (CAST(:topic AS text) IS NULL OR EXISTS (
              SELECT 1 FROM core.article_topics at JOIN core.topics t ON t.id = at.topic_id
              WHERE at.article_id = a.id AND t.slug = :topic))
        AND (CAST(:eid AS bigint) IS NULL OR EXISTS (
              SELECT 1 FROM core.article_entities ae
              WHERE ae.article_id = a.id AND ae.entity_id = :eid
                AND ae.published_date BETWEEN :start AND :end))
    """
    total = session.execute(
        text(f"""
        SELECT count(*) FROM core.articles a JOIN core.sources s ON s.id = a.source_id
        WHERE {where}"""),
        params,
    ).scalar_one()
    rows = _rows(
        session,
        f"""
        SELECT a.id, a.title, a.url, a.published_at, a.published_at_estimated, a.language,
               a.summary_en, a.sentiment_label, a.sentiment_score, a.event_type,
               a.enrichment_status, a.duplicate_of_id,
               s.slug AS source_slug, s.name AS source_name,
               t.slug AS topic_slug, t.name_en AS topic_name
        FROM core.articles a JOIN core.sources s ON s.id = a.source_id
        LEFT JOIN core.topics t ON t.id = a.primary_topic_id
        WHERE {where}
        ORDER BY {SORTS[sort]} LIMIT :limit OFFSET :offset
    """,
        params,
    )
    return int(total), [{**r, "sentiment_score": _f(r["sentiment_score"])} for r in rows]


def article_detail(session: Session, article_id: int) -> dict[str, Any] | None:
    rows = _rows(
        session,
        """
        SELECT a.id, a.title, a.url, a.published_at, a.published_at_estimated, a.language,
               a.summary_en, a.sentiment_label, a.sentiment_score, a.event_type, a.countries,
               a.enrichment_status, a.enrichment_confidence, a.feed_categories, a.author,
               a.duplicate_of_id, a.enriched_at,
               s.slug AS source_slug, s.name AS source_name, s.homepage_url AS source_url,
               t.slug AS topic_slug, t.name_en AS topic_name
        FROM core.articles a JOIN core.sources s ON s.id = a.source_id
        LEFT JOIN core.topics t ON t.id = a.primary_topic_id
        WHERE a.id = :id AND NOT a.is_hidden
    """,
        {"id": article_id},
    )
    if not rows:
        return None
    art = rows[0]
    art["sentiment_score"] = _f(art["sentiment_score"])
    art["enrichment_confidence"] = _f(art["enrichment_confidence"])
    art["topics"] = _rows(
        session,
        """
        SELECT t.slug, t.name_en, at.is_primary FROM core.article_topics at
        JOIN core.topics t ON t.id = at.topic_id WHERE at.article_id = :id
        ORDER BY at.is_primary DESC, t.sort_order""",
        {"id": article_id},
    )
    art["entities"] = _rows(
        session,
        """
        SELECT e.id, e.name, e.type FROM core.article_entities ae
        JOIN core.entities e ON e.id = ae.entity_id WHERE ae.article_id = :id
        ORDER BY e.type, e.name, e.id""",
        {"id": article_id},
    )
    art["related"] = _rows(
        session,
        """
        SELECT a.id, a.title, a.url, a.published_at, s.name AS source_name
        FROM core.articles a JOIN core.sources s ON s.id = a.source_id
        WHERE NOT a.is_hidden AND a.id <> :id AND (
              a.duplicate_of_id = coalesce(:root, :id) OR a.id = coalesce(:root, :id))
        ORDER BY a.published_at, a.id LIMIT 10""",
        {"id": article_id, "root": art["duplicate_of_id"]},
    )
    return art
