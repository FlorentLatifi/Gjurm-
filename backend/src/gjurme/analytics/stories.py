"""Story queries: the feed, one story, blindspots and source profiles.

A story's numbers are computed from its *visible* member articles at query time, so takedowns
and changed source ratings apply immediately. Coverage counts **distinct outlets** (an outlet
that ran two articles on one story counts once), split by the outlet's bias group, factuality,
ownership and country.

Blindspots (method strings below are shown on the site):

* **perspective** — at least ``BLINDSPOT_MIN_RATED`` rated outlets covered the story, one side
  (left or right) supplies ≥ ``BLINDSPOT_DOMINANT_SHARE`` of them and the other side
  ≤ ``BLINDSPOT_MISSING_SHARE``;
* **region** — the story is about a country (≥ half of its analysed articles name it), at least
  ``BLINDSPOT_MIN_SOURCES`` outlets covered it, the site follows outlets based in that country,
  and none of them covered it.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from gjurme.analytics.queries import Range, _f, _rows
from gjurme.ingestion.normalize import normalize_key
from gjurme.sources.ratings import bias_group

BLINDSPOT_MIN_RATED = 3
BLINDSPOT_DOMINANT_SHARE = 0.6
BLINDSPOT_MISSING_SHARE = 0.15
BLINDSPOT_MIN_SOURCES = 3
REGION_ABOUT_SHARE = 0.5

# The only SQL spliced into a query (``_PAGE_SQL.format``): a whitelisted ORDER BY. All user input
# is passed as bound parameters.
STORY_SORTS = {
    "top": "agg.source_count DESC, agg.article_count DESC, agg.last_at DESC, agg.story_id DESC",
    "latest": "agg.last_at DESC, agg.story_id DESC",
}

BLINDSPOT_METHOD = (
    f"Perspective blindspot: at least {BLINDSPOT_MIN_RATED} rated outlets covered the story, "
    f"≥ {BLINDSPOT_DOMINANT_SHARE:.0%} of them from one side (left or right) and "
    f"≤ {BLINDSPOT_MISSING_SHARE:.0%} from the other. Region blindspot: the story is about a "
    f"country (named in at least half of its analysed articles), {BLINDSPOT_MIN_SOURCES}+ "
    "outlets covered it, and none of the followed outlets based in that country did. Outlets "
    "are counted once per story; unrated outlets are not part of the perspective rule."
)
BLINDSPOT_METHOD_SQ = (
    f"Pikë e verbër sipas këndvështrimit: të paktën {BLINDSPOT_MIN_RATED} media të vlerësuara "
    f"e raportuan lajmin, ≥ {BLINDSPOT_DOMINANT_SHARE:.0%} prej tyre nga njëra anë (majtas ose "
    f"djathtas) dhe ≤ {BLINDSPOT_MISSING_SHARE:.0%} nga tjetra. Pikë e verbër sipas rajonit: "
    "lajmi ka të bëjë me një shtet (të përmendur në të paktën gjysmën e artikujve të analizuar), "
    f"{BLINDSPOT_MIN_SOURCES}+ media e raportuan, dhe asnjë nga mediat e ndjekura me seli në atë "
    "shtet. Secila media numërohet një herë për lajm; mediat pa vlerësim nuk hyjnë në rregullin "
    "e këndvështrimit."
)

_FACTUALITY_GROUP = {
    "very_high": "high",
    "high": "high",
    "mixed": "mixed",
    "low": "low",
    "very_low": "low",
}


# =============================================================================================
# Building blocks
# =============================================================================================
# A story spans at most 48 h from its first article (clustering.STORY_WINDOW), and its local
# date is that first article's. So the members of stories dated [start, end] were published on
# [start, end + 2]; queries bound articles by ``published_date`` to [start, end + 3] (a day of
# margin) to use its index instead of scanning every article for matching story ids.
_PAGE_SQL = """
    WITH cand AS (
      SELECT st.id FROM core.stories st
      WHERE st.published_date BETWEEN :start AND :end
        AND (CAST(:topic AS text) IS NULL
             OR st.primary_topic_id = (SELECT id FROM core.topics WHERE slug = :topic))),
    per AS (
      SELECT a.story_id, a.source_id, count(*) AS n,
             min(a.published_at) AS first_at, max(a.published_at) AS last_at
      FROM core.articles a JOIN cand ON cand.id = a.story_id
      WHERE NOT a.is_hidden AND a.published_date BETWEEN :start AND CAST(:end AS date) + 3
      GROUP BY 1, 2),
    agg AS (
      SELECT p.story_id, count(*) AS source_count, sum(p.n)::int AS article_count,
             min(p.first_at) AS first_at, max(p.last_at) AS last_at
      FROM per p JOIN core.sources s ON s.id = p.source_id
      GROUP BY 1
      HAVING count(*) >= :min_sources
         AND (:all_sources OR bool_or(s.slug = ANY(:sources)))
         AND (CAST(:country AS text) IS NULL OR bool_or(s.country = :country)))
    SELECT agg.story_id, agg.source_count, agg.article_count, agg.first_at, agg.last_at,
           count(*) OVER () AS total
    FROM agg
    WHERE CAST(:key AS text) IS NULL OR EXISTS (
          SELECT 1 FROM core.articles a WHERE a.story_id = agg.story_id AND NOT a.is_hidden
            AND a.title_normalized LIKE '%' || :key || '%')
    ORDER BY {order} LIMIT :limit OFFSET :offset
"""

_HEADS_SQL = """
    SELECT st.id, st.representative_article_id, t.slug AS topic_slug, t.name_en AS topic_name
    FROM core.stories st LEFT JOIN core.topics t ON t.id = st.primary_topic_id
    WHERE st.id = ANY(:ids)
"""

_MEMBERS_SQL = """
    SELECT a.story_id, a.id, a.title, a.url, a.published_at, a.language, a.summary_en,
           a.sentiment_label, a.countries, a.enrichment_status,
           s.slug AS source_slug, s.name AS source_name, s.country AS source_country,
           s.bias AS source_bias, s.factuality AS source_factuality,
           s.ownership AS source_ownership
    FROM core.articles a JOIN core.sources s ON s.id = a.source_id
    WHERE a.story_id = ANY(:ids) AND NOT a.is_hidden
    ORDER BY a.story_id, a.published_at, a.id
"""


def _source_countries(session: Session) -> set[str]:
    """Countries the site follows outlets in (active ones, or any that has articles)."""
    return {
        r[0]
        for r in session.execute(
            text("""
            SELECT DISTINCT s.country FROM core.sources s
            WHERE s.is_active OR EXISTS (SELECT 1 FROM core.articles a WHERE a.source_id = s.id)
        """)
        )
    }


def blindspots_of(
    members: list[dict[str, Any]], followed_countries: set[str]
) -> list[dict[str, str]]:
    """Blindspots of one story given its visible member rows (see module docstring)."""
    out: list[dict[str, str]] = []
    outlets = {m["source_slug"]: m for m in members}
    groups = Counter(bias_group(m["source_bias"]) for m in outlets.values())
    rated = groups["left"] + groups["center"] + groups["right"]
    if rated >= BLINDSPOT_MIN_RATED:
        for side, other in (("left", "right"), ("right", "left")):
            if (
                groups[side] / rated >= BLINDSPOT_DOMINANT_SHARE
                and groups[other] / rated <= BLINDSPOT_MISSING_SHARE
            ):
                out.append({"kind": "perspective", "missing": other})
    if len(outlets) >= BLINDSPOT_MIN_SOURCES:
        analysed = [m for m in members if m["enrichment_status"] == "succeeded"]
        mentioned = Counter(c for m in analysed for c in set(m["countries"] or ()))
        covering = {m["source_country"] for m in outlets.values()}
        for country, n in sorted(mentioned.items()):
            if (
                analysed
                and n / len(analysed) >= REGION_ABOUT_SHARE
                and country in followed_countries
                and country not in covering
            ):
                out.append({"kind": "region", "missing": country})
    return out


def _summary(
    head: dict[str, Any],
    agg: dict[str, Any],
    members: list[dict[str, Any]],
    followed: set[str],
) -> dict[str, Any]:
    """One story card: representative headline, coverage split, tone, first reporter."""
    rep = next((m for m in members if m["id"] == head["representative_article_id"]), None)
    rep = rep or members[0]
    first = members[0]
    outlets: dict[str, dict[str, Any]] = {}
    for m in members:
        outlets.setdefault(m["source_slug"], m)
    bias: Counter[str] = Counter({"left": 0, "center": 0, "right": 0, "unrated": 0})
    factuality: Counter[str] = Counter({"high": 0, "mixed": 0, "low": 0, "unrated": 0})
    ownership: Counter[str] = Counter()
    region: Counter[str] = Counter()
    for m in outlets.values():
        bias[bias_group(m["source_bias"])] += 1
        factuality[_FACTUALITY_GROUP.get(m["source_factuality"], "unrated")] += 1
        ownership[m["source_ownership"]] += 1
        region[m["source_country"]] += 1
    tone = Counter(m["sentiment_label"] for m in members if m["sentiment_label"])
    return {
        "id": head["id"],
        "title": rep["title"],
        "url": rep["url"],
        "language": rep["language"],
        "summary_en": rep["summary_en"],
        "source_slug": rep["source_slug"],
        "source_name": rep["source_name"],
        "first_published_at": agg["first_at"],
        "last_published_at": agg["last_at"],
        "article_count": agg["article_count"],
        "source_count": agg["source_count"],
        "topic_slug": head["topic_slug"],
        "topic_name": head["topic_name"],
        "first_source_slug": first["source_slug"],
        "first_source_name": first["source_name"],
        "coverage": {
            "bias": dict(bias),
            "factuality": dict(factuality),
            "ownership": dict(ownership.most_common()),
            "region": dict(region.most_common()),
        },
        "tone": {k: tone.get(k, 0) for k in ("negative", "neutral", "positive")},
        "sources": [
            {
                "slug": m["source_slug"],
                "name": m["source_name"],
                "bias": m["source_bias"],
                "country": m["source_country"],
            }
            for m in outlets.values()
        ],
        "blindspots": blindspots_of(members, followed),
    }


def _summaries(session: Session, aggs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = [a["story_id"] for a in aggs]
    if not ids:
        return []
    heads = {h["id"]: h for h in _rows(session, _HEADS_SQL, {"ids": ids})}
    members: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
    for m in _rows(session, _MEMBERS_SQL, {"ids": ids}):
        members[m["story_id"]].append(m)
    followed = _source_countries(session)
    return [
        _summary(heads[a["story_id"]], a, members[a["story_id"]], followed)
        for a in aggs
        if members[a["story_id"]]
    ]


# =============================================================================================
# Public queries
# =============================================================================================
def list_stories(
    session: Session,
    rng: Range,
    *,
    topic: str | None = None,
    country: str | None = None,
    q: str | None = None,
    min_sources: int = 1,
    sort: str = "top",
    limit: int = 20,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """Stories that started in the range, with their coverage (newest-first or biggest-first)."""
    aggs = _rows(
        session,
        _PAGE_SQL.format(order=STORY_SORTS[sort]),
        {
            **rng.params(),
            "topic": topic,
            "country": country,
            "key": normalize_key(q) if q else None,
            "min_sources": min_sources,
            "limit": limit,
            "offset": offset,
        },
    )
    total = int(aggs[0]["total"]) if aggs else 0
    return total, _summaries(session, aggs)


# Stories that may be blindspots: the rules of ``blindspots_of`` applied in SQL, so every story
# in the range is checked (not only the biggest few thousand) and only these are summarised.
# ``blindspots_of`` still decides; this only has to keep every story it would accept.
_BLINDSPOT_SQL = f"""
    WITH cand AS (
      SELECT st.id FROM core.stories st WHERE st.published_date BETWEEN :start AND :end),
    mem AS MATERIALIZED (
      SELECT a.story_id, a.id, a.source_id, a.published_at, a.enrichment_status, a.countries,
             s.bias, s.country
      FROM core.articles a JOIN cand ON cand.id = a.story_id
      JOIN core.sources s ON s.id = a.source_id
      WHERE NOT a.is_hidden AND a.published_date BETWEEN :start AND CAST(:end AS date) + 3),
    agg AS MATERIALIZED (
      SELECT story_id, count(DISTINCT source_id) AS source_count, count(*)::int AS article_count,
             min(published_at) AS first_at, max(published_at) AS last_at,
             count(DISTINCT source_id) FILTER (WHERE bias IN ('left', 'lean_left')) AS l,
             count(DISTINCT source_id) FILTER (WHERE bias = 'center') AS c,
             count(DISTINCT source_id) FILTER (WHERE bias IN ('lean_right', 'right')) AS r,
             array_agg(DISTINCT country) AS covering,
             count(*) FILTER (WHERE enrichment_status = 'succeeded') AS analysed
      FROM mem GROUP BY 1 HAVING count(DISTINCT source_id) >= :min_sources),
    followed AS (
      SELECT DISTINCT s.country FROM core.sources s
      WHERE s.is_active OR EXISTS (SELECT 1 FROM core.articles a WHERE a.source_id = s.id)),
    named AS MATERIALIZED (  -- per story and country: analysed articles that name it
      SELECT m.story_id, c.country, count(*) AS n
      FROM mem m CROSS JOIN LATERAL (SELECT DISTINCT unnest(m.countries) AS country) c
      WHERE m.enrichment_status = 'succeeded'
      GROUP BY 1, 2),
    region AS MATERIALIZED (  -- about a followed country whose outlets did not cover it
      SELECT DISTINCT nm.story_id FROM named nm
      JOIN agg ON agg.story_id = nm.story_id
      JOIN followed f ON f.country = nm.country
      WHERE nm.n >= {REGION_ABOUT_SHARE} * agg.analysed AND NOT nm.country = ANY(agg.covering))
    SELECT agg.story_id, agg.source_count, agg.article_count, agg.first_at, agg.last_at
    FROM agg LEFT JOIN region ON region.story_id = agg.story_id
    WHERE (l + c + r >= {BLINDSPOT_MIN_RATED}
           AND ((l >= {BLINDSPOT_DOMINANT_SHARE} * (l + c + r)
                 AND r <= {BLINDSPOT_MISSING_SHARE} * (l + c + r))
             OR (r >= {BLINDSPOT_DOMINANT_SHARE} * (l + c + r)
                 AND l <= {BLINDSPOT_MISSING_SHARE} * (l + c + r))))
       OR region.story_id IS NOT NULL
    ORDER BY {STORY_SORTS["top"]}
"""  # noqa: S608 - module constants only, no request input


def blindspots(
    session: Session, rng: Range, *, kind: str | None = None, limit: int = 30
) -> dict[str, Any]:
    """Stories one side of the spectrum (or one country's outlets) barely covered."""
    candidates = _rows(
        session, _BLINDSPOT_SQL, {**rng.params(), "min_sources": BLINDSPOT_MIN_SOURCES}
    )
    items = [
        s
        for s in _summaries(session, candidates)
        if any(kind is None or b["kind"] == kind for b in s["blindspots"])
    ]
    for s in items:
        if kind is not None:
            s["blindspots"] = [b for b in s["blindspots"] if b["kind"] == kind]
    return {"method": BLINDSPOT_METHOD, "method_sq": BLINDSPOT_METHOD_SQ, "items": items[:limit]}


def story_detail(session: Session, story_id: int) -> dict[str, Any] | None:
    agg_rows = _rows(
        session,
        """
        SELECT a.story_id, count(DISTINCT a.source_id) AS source_count,
               count(*)::int AS article_count,
               min(a.published_at) AS first_at, max(a.published_at) AS last_at
        FROM core.articles a WHERE a.story_id = :id AND NOT a.is_hidden GROUP BY 1
        """,
        {"id": story_id},
    )
    if not agg_rows:
        return None
    story = _summaries(session, agg_rows)[0]
    members = _rows(session, _MEMBERS_SQL, {"ids": [story_id]})
    first_id = members[0]["id"]
    story["articles"] = [
        {
            "id": m["id"],
            "title": m["title"],
            "url": m["url"],
            "published_at": m["published_at"],
            "language": m["language"],
            "summary_en": m["summary_en"],
            "sentiment_label": m["sentiment_label"],
            "source_slug": m["source_slug"],
            "source_name": m["source_name"],
            "source_country": m["source_country"],
            "source_bias": m["source_bias"],
            "source_factuality": m["source_factuality"],
            "source_ownership": m["source_ownership"],
            "is_first": m["id"] == first_id,
        }
        for m in members
    ]
    params = {"id": story_id}
    story["entities"] = _rows(
        session,
        """
        SELECT e.id, e.name, e.type, count(DISTINCT a.id) AS articles
        FROM core.articles a JOIN core.article_entities ae ON ae.article_id = a.id
        JOIN core.entities e ON e.id = ae.entity_id
        WHERE a.story_id = :id AND NOT a.is_hidden
        GROUP BY e.id, e.name, e.type ORDER BY articles DESC, e.name, e.id LIMIT 12
        """,
        params,
    )
    story["topics"] = _rows(
        session,
        """
        SELECT t.slug, t.name_en, count(DISTINCT a.id) AS articles
        FROM core.articles a JOIN core.article_topics at ON at.article_id = a.id
        JOIN core.topics t ON t.id = at.topic_id
        WHERE a.story_id = :id AND NOT a.is_hidden
        GROUP BY t.slug, t.name_en, t.sort_order ORDER BY articles DESC, t.sort_order
        """,
        params,
    )
    story["related"] = _related(session, story_id)
    return story


def _related(session: Session, story_id: int, limit: int = 6) -> list[dict[str, Any]]:
    """Other stories within three days that share at least two named entities."""
    aggs = _rows(
        session,
        """
        WITH mine AS (
          SELECT DISTINCT ae.entity_id FROM core.articles a
          JOIN core.article_entities ae ON ae.article_id = a.id
          WHERE a.story_id = :id AND NOT a.is_hidden),
        me AS (SELECT first_published_at AS at, published_date AS d
               FROM core.stories WHERE id = :id),
        shared AS (
          SELECT a.story_id, count(DISTINCT ae.entity_id) AS shared
          FROM core.article_entities ae JOIN mine USING (entity_id)
          JOIN core.articles a ON a.id = ae.article_id
          JOIN core.stories st ON st.id = a.story_id, me
          WHERE a.story_id <> :id AND NOT a.is_hidden
            -- mentions in the days such stories can span: uses (published_date, entity_id)
            -- instead of every mention of a name in the archive
            AND ae.published_date BETWEEN me.d - 4 AND me.d + 6
            AND st.first_published_at
                BETWEEN me.at - interval '3 days' AND me.at + interval '3 days'
          GROUP BY 1 HAVING count(DISTINCT ae.entity_id) >= 2
          ORDER BY shared DESC, a.story_id DESC LIMIT :limit)
        SELECT sh.story_id, count(DISTINCT a.source_id) AS source_count,
               count(*)::int AS article_count,
               min(a.published_at) AS first_at, max(a.published_at) AS last_at, sh.shared
        FROM shared sh JOIN core.articles a ON a.story_id = sh.story_id AND NOT a.is_hidden
        GROUP BY sh.story_id, sh.shared ORDER BY sh.shared DESC, sh.story_id DESC
        """,
        {"id": story_id, "limit": limit},
    )
    return _summaries(session, aggs)


def source_profile(session: Session, slug: str, rng: Range) -> dict[str, Any] | None:
    """One outlet: ratings, how much of the news it covers, what it reports first, its focus."""
    src = _rows(
        session,
        """
        SELECT id, slug, name, homepage_url, language, country, is_active, verification_status,
               last_success_at, bias, factuality, ownership, owner, ratings_note
        FROM core.sources WHERE slug = :slug
        """,
        {"slug": slug},
    )
    if not src:
        return None
    profile = src[0]
    sid = profile.pop("id")
    p = {"start": rng.start, "end": rng.end, "sid": sid}
    head = _rows(
        session,
        """
        WITH st AS (
          SELECT a.story_id, count(DISTINCT a.source_id) AS outlets,
                 bool_or(a.source_id = :sid) AS covered,
                 (array_agg(a.source_id ORDER BY a.published_at, a.id))[1] AS first_source
          FROM core.articles a JOIN core.stories s ON s.id = a.story_id
          WHERE s.published_date BETWEEN :start AND :end AND NOT a.is_hidden
            AND a.published_date BETWEEN :start AND CAST(:end AS date) + 3
          GROUP BY 1)
        SELECT
          (SELECT count(*) FROM core.articles a WHERE a.source_id = :sid AND NOT a.is_hidden
             AND a.published_date BETWEEN :start AND :end) AS articles,
          (SELECT avg(a.sentiment_score) FROM core.articles a WHERE a.source_id = :sid
             AND NOT a.is_hidden AND a.published_date BETWEEN :start AND :end) AS avg_sentiment,
          count(*) FILTER (WHERE covered) AS stories,
          count(*) FILTER (WHERE outlets >= 2) AS multi_source_stories,
          count(*) FILTER (WHERE covered AND outlets >= 2) AS covered_multi_source,
          count(*) FILTER (WHERE outlets >= 2 AND first_source = :sid) AS first_reports,
          count(*) FILTER (WHERE covered AND outlets = 1) AS exclusives
        FROM st
        """,
        p,
    )[0]
    multi = head.pop("multi_source_stories")
    profile.update(
        {
            "range": {"start": rng.start, "end": rng.end, "days": rng.days},
            **head,
            "avg_sentiment": _f(head["avg_sentiment"]),
            "coverage_share": _f(head["covered_multi_source"] / multi) if multi else None,
        }
    )
    profile.pop("covered_multi_source")
    profile["top_topics"] = _rows(
        session,
        """
        SELECT t.slug, t.name_en, count(*) AS articles
        FROM core.articles a JOIN core.topics t ON t.id = a.primary_topic_id
        WHERE a.source_id = :sid AND NOT a.is_hidden AND a.published_date BETWEEN :start AND :end
        GROUP BY t.slug, t.name_en ORDER BY articles DESC, t.slug LIMIT 6
        """,
        p,
    )
    profile["top_entities"] = _rows(
        session,
        """
        SELECT e.id, e.name, e.type, count(*) AS mentions
        FROM core.articles a
        JOIN core.article_entities ae ON ae.article_id = a.id
             AND ae.published_date BETWEEN :start AND :end
        JOIN core.entities e ON e.id = ae.entity_id
        WHERE a.source_id = :sid AND NOT a.is_hidden AND a.published_date BETWEEN :start AND :end
        GROUP BY e.id, e.name, e.type ORDER BY mentions DESC, e.name, e.id LIMIT 10
        """,
        p,
    )
    profile["overlap"] = _rows(
        session,
        """
        WITH mine AS (
          SELECT DISTINCT a.story_id FROM core.articles a JOIN core.stories s ON s.id = a.story_id
          WHERE a.source_id = :sid AND NOT a.is_hidden
            AND s.published_date BETWEEN :start AND :end
            AND a.published_date BETWEEN :start AND CAST(:end AS date) + 3)
        SELECT src.slug, src.name, src.bias, count(DISTINCT a.story_id) AS shared
        FROM core.articles a JOIN mine USING (story_id)
        JOIN core.sources src ON src.id = a.source_id
        WHERE a.source_id <> :sid AND NOT a.is_hidden
          AND a.published_date BETWEEN :start AND CAST(:end AS date) + 3
        GROUP BY src.slug, src.name, src.bias ORDER BY shared DESC, src.slug LIMIT 8
        """,
        p,
    )
    _, profile["recent_stories"] = list_stories(
        session, Range(rng.start, rng.end, (slug,)), sort="latest", limit=8
    )
    return profile
