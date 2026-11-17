"""Measure story clustering against hand-labelled real news (``gjurme stories-eval``).

The evaluation set is a sample of live articles exported by ``gjurme stories-sample`` (the
*Source validation* workflow runs it on the live feeds) in which every article carries the
event it reports, labelled by hand. Only metadata and derived data are kept (ADR-003):
headline, outlet, time, URL, the analysis' entity names and the excerpt's *content words* — the
folded, stopword-free words of its first ``EXCERPT_MAX_WORDS`` words, deduplicated and sorted,
which is all the clustering reads of it and cannot be read back as the text.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from gjurme.stories.clustering import _load
from gjurme.stories.similarity import EXCERPT_MAX_WORDS, content_words

_META_SQL = text("""
    SELECT a.id, s.slug, a.url FROM core.articles a JOIN core.sources s ON s.id = a.source_id
    WHERE a.id = ANY(:ids)
""")


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def export_sample(
    session: Session, *, hours: int = 72, now: datetime | None = None
) -> dict[str, Any]:
    """The articles published in the last ``hours`` as an evaluation sample to label.

    Ids are renumbered 1..n in publication order; ``story`` is the story the current clustering
    put the article in (renumbered too), a starting point for the labels, not a label.
    """
    end = now or datetime.now(UTC)
    rows = _load(session, end - timedelta(hours=hours), end)
    meta = {
        r.id: (r.slug, r.url) for r in session.execute(_META_SQL, {"ids": [r.id for r in rows]})
    }
    local = {r.id: i for i, r in enumerate(rows, 1)}
    stories: dict[int, int] = {}
    articles: list[dict[str, Any]] = []
    for r in rows:
        slug, url = meta[r.id]
        story = None
        if r.story_id is not None:
            story = stories.setdefault(r.story_id, len(stories) + 1)
        articles.append(
            {
                "id": local[r.id],
                "outlet": slug,
                "published_at": _iso(r.published_at),
                "title": r.doc.title,
                "url": url,
                "words": sorted(set(content_words(r.doc.excerpt, max_words=EXCERPT_MAX_WORDS))),
                "people": sorted(set(r.doc.people)),
                "places": sorted(set(r.doc.places)),
                "orgs": sorted(set(r.doc.other_entities)),
                "duplicate_of": local.get(r.duplicate_of_id) if r.duplicate_of_id else None,
                "story": story,
            }
        )
    return {
        "collected_at": _iso(end),
        "hours": hours,
        "articles": articles,
    }


def dumps(sample: dict[str, Any]) -> str:
    """JSON with one article per line (readable diffs, greppable logs)."""
    head = {k: v for k, v in sample.items() if k != "articles"}
    lines = [json.dumps(a, ensure_ascii=False) for a in sample["articles"]]
    body = ",\n    ".join(lines)
    inner = json.dumps(head, ensure_ascii=False, indent=2)[:-2]  # drop the closing "\n}"
    return f'{inner},\n  "articles": [\n    {body}\n  ]\n}}\n'
