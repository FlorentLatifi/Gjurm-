"""A Markdown report for checking story clustering on real headlines (``gjurme stories-review``).

Three lists, headlines only (never excerpts, ADR-003):

* **multi-outlet stories** — every member headline, to spot two events merged into one;
* **weakest members** — the members least similar to the rest of their story (false merges
  show up here first);
* **near misses** — the most similar pairs of articles from different outlets that ended up in
  *different* stories, with their similarity and whether the name guard separated them (missed
  paraphrases show up here).

The thresholds of ADR-020 were hand-calibrated; this report is how they are checked on live
data before being changed with ``STORY_SIMILARITY_THRESHOLD`` + ``gjurme cluster --rebuild-days``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from itertools import combinations

from sqlalchemy import text
from sqlalchemy.orm import Session

from gjurme.config import Settings
from gjurme.stories.clustering import STORY_WINDOW, _load
from gjurme.stories.similarity import cosine, idf_table, names_conflict, vector

MAX_ARTICLES = 2000


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def review_report(session: Session, settings: Settings, *, hours: int = 48, top: int = 25) -> str:
    end = datetime.now(UTC)
    rows = _load(session, end - timedelta(hours=hours), end)[-MAX_ARTICLES:]
    slugs: dict[int, str] = {
        r.id: r.slug
        for r in session.execute(
            text(
                "SELECT a.id, s.slug FROM core.articles a "
                "JOIN core.sources s ON s.id = a.source_id WHERE a.id = ANY(:ids)"
            ),
            {"ids": [r.id for r in rows]},
        )
    }
    idf = idf_table(r.doc for r in rows)
    vec = {r.id: vector(r.doc, idf) for r in rows}
    by_story: dict[int, list[int]] = defaultdict(list)
    for r in rows:
        if r.story_id is not None:
            by_story[r.story_id].append(r.id)
    row = {r.id: r for r in rows}
    threshold = settings.story_similarity_threshold

    out = [
        f"## Story clustering review — last {hours} h",
        "",
        f"{len(rows)} articles, {len(by_story)} stories, threshold "
        f"{threshold:g}. Similarities are article-to-article cosines (the clustering compares an "
        "article with the whole story, so they differ slightly).",
        "",
        "### Multi-outlet stories",
        "",
    ]
    multi = {sid: ids for sid, ids in by_story.items() if len({slugs[i] for i in ids}) >= 2}
    for sid, ids in sorted(multi.items(), key=lambda kv: -len(kv[1])):
        out.append(f"**Story {sid}** — {len({slugs[i] for i in ids})} outlets")
        out.extend(f"- `{slugs[i]}` {_cell(row[i].doc.title)}" for i in ids)
        out.append("")
    if not multi:
        out.extend(["None.", ""])

    weakest = []
    for ids in by_story.values():
        if len(ids) < 2:
            continue
        for i in ids:
            best = max(cosine(vec[i], vec[j]) for j in ids if j != i)
            weakest.append((best, i))
    weakest.sort()
    out += ["### Weakest members (lowest best match inside their story)", ""]
    out += ["| best match | outlet | headline | story |", "|---:|---|---|---:|"]
    out += [
        f"| {sim:.2f} | {slugs[i]} | {_cell(row[i].doc.title)} | {row[i].story_id} |"
        for sim, i in weakest[:top]
    ]
    out.append("")

    pairs = []
    for a, b in combinations(rows, 2):
        if (
            a.story_id == b.story_id
            or slugs[a.id] == slugs[b.id]
            or abs(a.published_at - b.published_at) > STORY_WINDOW
        ):
            continue
        sim = cosine(vec[a.id], vec[b.id])
        if sim >= 0.2:
            pairs.append((sim, a, b))
    pairs.sort(key=lambda p: -p[0])
    out += ["### Near misses (different stories, different outlets)", ""]
    out += ["| similarity | names conflict | headline A | headline B |", "|---:|:-:|---|---|"]
    out += [
        f"| {sim:.2f} | {'yes' if names_conflict(a.doc.names, b.doc.names) else 'no'} "
        f"| `{slugs[a.id]}` {_cell(a.doc.title)} | `{slugs[b.id]}` {_cell(b.doc.title)} |"
        for sim, a, b in pairs[:top]
    ]
    out.append("")
    return "\n".join(out)
