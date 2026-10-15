"""CLUSTER stage: group articles that report the same event into stories (``core.stories``).

Single-pass clustering in publication order. Each unclustered article is compared with the
stories it can join without the story spanning more than ``STORY_WINDOW`` (first to last
article). A fixed window, not a rolling one: rolling windows chain separate occurrences of a
recurring event (two dialogue rounds in Brussels four days apart) into one story.

1. a near-verbatim copy (``duplicate_of_id``, dedup layer L4) joins its original's story;
2. otherwise it joins the most similar story whose centroid has cosine similarity ≥
   ``settings.story_similarity_threshold``, with which its headline shares a word that is not a
   person's name (``similarity.shares_event_term``), and whose names do not conflict
   (``similarity.names_conflict``);
3. otherwise it starts a new story.

Assignments are never revisited by later runs, so story ids (and URLs) are stable;
``rebuild`` re-clusters a period from scratch after a threshold change. The IDF weights come
from all articles loaded for the batch (the batch ± the story window), i.e. the news of the
same few days. See docs/DECISIONS.md (ADR-020).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from gjurme.config import Settings
from gjurme.db.models import Article, Story
from gjurme.stories.similarity import (
    Doc,
    Names,
    apply_place_lexicon,
    cosine,
    idf_table,
    names_conflict,
    place_lexicon,
    shares_event_term,
    vector,
)

log = logging.getLogger(__name__)

STORY_WINDOW = timedelta(hours=48)  # first to last article of one story
# Stories whose topic and representative may change because members were (re-)analysed.
REFRESH_RECENT = timedelta(days=3)


@dataclass(slots=True)
class ClusterStats:
    considered: int = 0
    joined_existing: int = 0
    new_stories: int = 0
    via_duplicate: int = 0
    stories_refreshed: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "joined_existing": self.joined_existing,
            "new_stories": self.new_stories,
            "via_duplicate": self.via_duplicate,
            "stories_refreshed": self.stories_refreshed,
        }


@dataclass(slots=True)
class _Cluster:
    key: int  # story id, or a negative placeholder until the story row is inserted
    first_at: datetime
    last_at: datetime
    centroid: dict[str, float] = field(default_factory=dict)
    names: Names = field(default_factory=Names)
    people_all: frozenset[str] = frozenset()
    members: list[int] = field(default_factory=list)
    norm: float = 0.0

    def add(self, article_id: int, vec: dict[str, float], doc: Doc) -> None:
        for term, weight in vec.items():
            self.centroid[term] = self.centroid.get(term, 0.0) + weight
        self.norm = sum(x * x for x in self.centroid.values()) ** 0.5
        self.names = self.names | doc.names
        self.people_all = self.people_all | doc.people_all
        self.members.append(article_id)

    def similarity(self, vec: dict[str, float]) -> float:
        return cosine(vec, self.centroid) / self.norm if self.norm else 0.0

    def fits(self, at: datetime) -> bool:
        """With an article published ``at``, the story still spans at most ``STORY_WINDOW``."""
        return max(self.last_at, at) - min(self.first_at, at) <= STORY_WINDOW

    def extend(self, at: datetime) -> None:
        self.first_at, self.last_at = min(self.first_at, at), max(self.last_at, at)


@dataclass(frozen=True, slots=True)
class _Row:
    id: int
    published_at: datetime
    story_id: int | None
    duplicate_of_id: int | None
    doc: Doc


_LOAD_SQL = text("""
    SELECT a.id, a.title, a.excerpt, a.published_at, a.story_id, a.duplicate_of_id,
           coalesce(array_agg(e.name) FILTER (WHERE e.type = 'person'), '{}') AS people,
           coalesce(array_agg(e.name) FILTER (WHERE e.type = 'location'), '{}') AS places,
           coalesce(array_agg(e.name) FILTER (WHERE e.type = 'organization'), '{}') AS orgs
    FROM core.articles a
    LEFT JOIN core.article_entities ae ON ae.article_id = a.id
    LEFT JOIN core.entities e ON e.id = ae.entity_id
    WHERE a.published_at BETWEEN :start AND :end
    GROUP BY a.id
    ORDER BY a.published_at, a.id
""")


def _load(session: Session, start: datetime, end: datetime) -> list[_Row]:
    """Articles published in [start, end] as clustering documents (place lexicon applied)."""
    rows = [
        _Row(
            r.id,
            r.published_at,
            r.story_id,
            r.duplicate_of_id,
            Doc(r.id, r.title, r.excerpt, r.people, r.places, r.orgs),
        )
        for r in session.execute(_LOAD_SQL, {"start": start, "end": end})
    ]
    lexicon = place_lexicon(r.doc for r in rows)
    for r in rows:
        r.doc.names = apply_place_lexicon(r.doc.names, lexicon)
    return rows


def _story_spans(session: Session, ids: set[int]) -> dict[int, tuple[datetime, datetime]]:
    if not ids:
        return {}
    rows = session.execute(
        select(Story.id, Story.first_published_at, Story.last_published_at).where(Story.id.in_(ids))
    ).all()
    return {r.id: (r.first_published_at, r.last_published_at) for r in rows}


def cluster_pending(
    session: Session, settings: Settings, *, batch_size: int = 2000, max_articles: int = 100_000
) -> ClusterStats:
    """Assign every unclustered article to a story; commits after each batch."""
    stats = ClusterStats()
    tz = ZoneInfo(settings.timezone)
    while stats.considered < max_articles:
        pending = session.execute(
            select(Article.id, Article.published_at)
            .where(Article.story_id.is_(None))
            .order_by(Article.published_at, Article.id)
            .limit(batch_size)
        ).all()
        if not pending:
            break
        touched = _cluster_batch(
            session,
            settings,
            [p.id for p in pending],
            pending[0].published_at,
            pending[-1].published_at,
            stats,
        )
        stats.stories_refreshed += refresh_stories(session, tz, touched)
        session.commit()
    recent = set(
        session.scalars(
            select(Story.id).where(Story.last_published_at >= datetime.now(UTC) - REFRESH_RECENT)
        )
    )
    stats.stories_refreshed += refresh_stories(session, tz, recent)
    session.commit()
    log.info("clustering done", extra=stats.as_dict())
    return stats


def _cluster_batch(
    session: Session,
    settings: Settings,
    batch_ids: Sequence[int],
    lo: datetime,
    hi: datetime,
    stats: ClusterStats,
) -> set[int]:
    rows = _load(session, lo - STORY_WINDOW, hi + STORY_WINDOW)
    idf = idf_table(r.doc for r in rows)
    vectors = {r.id: vector(r.doc, idf) for r in rows}
    spans = _story_spans(session, {r.story_id for r in rows if r.story_id is not None})

    clusters: dict[int, _Cluster] = {}
    story_of: dict[int, int] = {}  # article id -> cluster key
    index: dict[str, set[int]] = defaultdict(set)  # term -> cluster keys
    for r in rows:
        if r.story_id is None:
            continue
        c = clusters.get(r.story_id)
        if c is None:
            first, last = spans.get(r.story_id, (r.published_at, r.published_at))
            c = clusters[r.story_id] = _Cluster(r.story_id, first, last)
        c.add(r.id, vectors[r.id], r.doc)
        story_of[r.id] = r.story_id
        _index_terms(index, r.story_id, vectors[r.id])

    threshold = settings.story_similarity_threshold
    by_id = {r.id: r for r in rows}
    wanted = set(batch_ids)
    next_key = -1
    for r in rows:
        if r.id not in wanted:
            continue
        stats.considered += 1
        vec = vectors[r.id]
        key: int | None = None
        original = story_of.get(r.duplicate_of_id) if r.duplicate_of_id is not None else None
        if original is not None and clusters[original].fits(r.published_at):
            key = original
            stats.via_duplicate += 1
        else:
            key = _best_cluster(r, vec, clusters, index, threshold)
            if key is not None:
                stats.joined_existing += 1
        if key is None:
            key = next_key
            next_key -= 1
            clusters[key] = _Cluster(key, r.published_at, r.published_at)
            stats.new_stories += 1
        cluster = clusters[key]
        cluster.add(r.id, vec, r.doc)
        cluster.extend(r.published_at)
        story_of[r.id] = key
        _index_terms(index, key, vec)

    # Insert new stories, then point the batch's articles at their story.
    real: dict[int, int] = {}
    for key, c in clusters.items():
        if key >= 0:
            real[key] = key
            continue
        first = min(by_id[m].published_at for m in c.members)
        story = Story(
            first_published_at=first,
            last_published_at=max(by_id[m].published_at for m in c.members),
            published_date=first.date(),  # corrected to the local date by refresh_stories
        )
        session.add(story)
        session.flush()
        real[key] = story.id
    assignments: dict[int, list[int]] = defaultdict(list)
    for article_id in wanted:
        assignments[real[story_of[article_id]]].append(article_id)
    for story_id, article_ids in assignments.items():
        session.execute(
            update(Article).where(Article.id.in_(article_ids)).values(story_id=story_id)
        )
    # Representative headline: the member closest to the centroid (earliest on ties).
    touched = set(assignments)
    for key, c in clusters.items():
        if real[key] not in touched:
            continue
        rep, rep_sim = c.members[0], -1.0
        for m in sorted(c.members, key=lambda m: (by_id[m].published_at, m)):
            sim = round(c.similarity(vectors[m]), 6)
            if sim > rep_sim:
                rep, rep_sim = m, sim
        session.execute(
            update(Story).where(Story.id == real[key]).values(representative_article_id=rep)
        )
    return touched


def _index_terms(index: dict[str, set[int]], key: int, vec: dict[str, float]) -> None:
    for term in vec:
        index[term].add(key)


def _best_cluster(
    row: _Row,
    vec: dict[str, float],
    clusters: dict[int, _Cluster],
    index: dict[str, set[int]],
    threshold: float,
) -> int | None:
    """Most similar story in the time window that passes the threshold and the guards."""
    # Sparse dot products through the inverted index: cost ~ postings, not stories × terms.
    dots: dict[int, float] = defaultdict(float)
    for term, weight in vec.items():
        for key in index.get(term, ()):
            dots[key] += weight * clusters[key].centroid[term]
    best_key, best = None, threshold
    for key in sorted(dots):
        c = clusters[key]
        sim = dots[key] / c.norm if c.norm else 0.0
        if sim < best or (sim == best and best_key is not None):
            continue
        if not c.fits(row.published_at) or names_conflict(row.doc.names, c.names):
            continue
        if not shares_event_term(row.doc.headline, c.centroid, row.doc.people_all | c.people_all):
            continue  # only a person in common: not the same event
        best_key, best = key, sim
    return best_key


_REFRESH_SQL = text("""
    UPDATE core.stories st SET
      first_published_at = agg.first_at,
      last_published_at = agg.last_at,
      published_date = (agg.first_at AT TIME ZONE :tz)::date,
      primary_topic_id = agg.topic,
      representative_article_id = CASE
        WHEN st.representative_article_id = ANY(agg.members) THEN st.representative_article_id
        ELSE agg.members[1] END,
      updated_at = now()
    FROM (
      SELECT story_id, min(published_at) AS first_at, max(published_at) AS last_at,
             mode() WITHIN GROUP (ORDER BY primary_topic_id) AS topic,
             array_agg(id ORDER BY published_at, id) AS members
      FROM core.articles WHERE story_id = ANY(:ids) GROUP BY story_id
    ) agg
    WHERE st.id = agg.story_id
""")


def refresh_stories(session: Session, tz: ZoneInfo, story_ids: set[int]) -> int:
    """Recompute time span, local date and majority topic of the given stories."""
    if not story_ids:
        return 0
    session.execute(_REFRESH_SQL, {"ids": sorted(story_ids), "tz": tz.key})
    return len(story_ids)


def rebuild(session: Session, settings: Settings, since: date) -> dict[str, Any]:
    """Re-cluster every article published on or after ``since`` (local date) from scratch.

    Use after changing ``STORY_SIMILARITY_THRESHOLD``. Story ids in the period change.
    """
    released = session.execute(
        update(Article).where(Article.published_date >= since).values(story_id=None)
    ).rowcount  # type: ignore[attr-defined]
    deleted = session.execute(
        text("""
        DELETE FROM core.stories st
        WHERE NOT EXISTS (SELECT 1 FROM core.articles a WHERE a.story_id = st.id)
    """)
    ).rowcount  # type: ignore[attr-defined]
    session.commit()
    stats = cluster_pending(session, settings)
    return {"articles_released": released, "stories_deleted": deleted, **stats.as_dict()}
