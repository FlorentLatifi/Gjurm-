"""Fold headline revisions already in the database (dedup layer L3b, ADR-034).

The PROCESS stage folds a revision as it arrives (``processor._find_same_source_revision``).
Articles stored before that rule existed are folded here, by ``gjurme dedup-revisions``: the
same rule, applied in publication order per outlet. Nothing is deleted. A revision becomes a
hidden row (``is_hidden``, ``hidden_reason``) linked to the article readers see
(``duplicate_of_id``), which takes the newest wording; ``ops`` can unhide it like a takedown.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from gjurme.db.models import Article
from gjurme.ingestion.processor import (
    REVISION_HIDDEN_REASON,
    REVISION_WINDOW,
    RevisionRow,
    adopt_wording,
    find_revision_root,
)
from gjurme.stories.clustering import refresh_stories


@dataclass(slots=True)
class ArticleRow:
    id: int
    source: str
    title: str
    title_normalized: str
    published_at: datetime
    story_id: int | None
    root_id: int  # itself, or the article an earlier revision was folded into
    folded: bool = False  # already hidden as a revision before this run


@dataclass(slots=True)
class FoldPlan:
    """Revisions to fold: revision id → root id, and each root's newest member."""

    folds: dict[int, int] = field(default_factory=dict)
    newest: dict[int, ArticleRow] = field(default_factory=dict)
    rows: dict[int, ArticleRow] = field(default_factory=dict)


def plan_folds(rows: list[ArticleRow]) -> FoldPlan:
    """Apply the rule in publication order per outlet. Pure: no database."""
    plan = FoldPlan(rows={r.id: r for r in rows})
    by_source: dict[str, list[ArticleRow]] = defaultdict(list)
    for r in rows:
        by_source[r.source].append(r)
    for items in by_source.values():
        items.sort(key=lambda r: (r.published_at, r.id))
        seen: list[ArticleRow] = []  # visible articles and their revisions, oldest first
        for r in items:
            while seen and r.published_at - seen[0].published_at > REVISION_WINDOW:
                seen.pop(0)
            if not r.folded:
                group = [
                    RevisionRow(s.id, s.root_id, s.title_normalized, s.published_at)
                    for s in reversed(seen)
                ]
                root = find_revision_root(r.title_normalized, group)
                if root is not None:
                    r.root_id = root
                    plan.folds[r.id] = root
            if r.root_id != r.id:
                newest = plan.newest.get(r.root_id)
                if newest is None or (r.published_at, r.id) >= (newest.published_at, newest.id):
                    plan.newest[r.root_id] = r
            seen.append(r)
    return plan


_LOAD_SQL = text("""
    SELECT a.id, s.slug AS source, a.title, a.title_normalized, a.published_at, a.story_id,
           a.is_hidden, a.duplicate_of_id
    FROM core.articles a JOIN core.sources s ON s.id = a.source_id
    WHERE a.published_at >= :start
      AND (NOT a.is_hidden OR (a.hidden_reason = :reason AND a.duplicate_of_id IS NOT NULL))
    ORDER BY a.published_at, a.id
""")


def fold_revisions(
    session: Session, tz: ZoneInfo, since: date, *, apply: bool = False, show: int = 40
) -> dict[str, Any]:
    """Find (and with ``apply``, fold) the revisions published on or after ``since``."""
    start = datetime.combine(since, datetime.min.time(), tzinfo=tz) - REVISION_WINDOW
    rows = [
        ArticleRow(
            r.id,
            r.source,
            r.title,
            r.title_normalized,
            r.published_at,
            r.story_id,
            int(r.duplicate_of_id) if r.is_hidden else r.id,
            folded=bool(r.is_hidden),
        )
        for r in session.execute(_LOAD_SQL, {"start": start, "reason": REVISION_HIDDEN_REASON})
    ]
    plan = plan_folds(rows)
    per_source: dict[str, int] = defaultdict(int)
    for rid in plan.folds:
        per_source[plan.rows[rid].source] += 1
    examples = [
        {
            "source": plan.rows[rid].source,
            "kept_id": root,
            "kept": plan.rows[root].title if root in plan.rows else None,
            "revision_id": rid,
            "revision": plan.rows[rid].title,
        }
        for rid, root in list(plan.folds.items())[:show]
    ]
    report: dict[str, Any] = {
        "articles_checked": len(rows),
        "revisions": len(plan.folds),
        "by_source": dict(sorted(per_source.items(), key=lambda kv: -kv[1])),
        "examples": examples,
        "applied": False,
    }
    if not apply or not plan.folds:
        return report

    stories: set[int] = set()
    for rid, root in plan.folds.items():
        session.execute(
            update(Article)
            .where(Article.id == rid)
            .values(is_hidden=True, hidden_reason=REVISION_HIDDEN_REASON, duplicate_of_id=root)
        )
        # other outlets' near-verbatim copies (L4) of the revision now point at what is shown
        session.execute(
            update(Article)
            .where(Article.duplicate_of_id == rid, Article.id != rid)
            .values(duplicate_of_id=root)
        )
        for i in (rid, root):
            story = plan.rows[i].story_id if i in plan.rows else None
            if story is not None:
                stories.add(story)
    for root, newest in plan.newest.items():
        if newest.id == root or root not in plan.rows:
            continue
        kept = session.get(Article, root)
        excerpt = session.scalar(select(Article.excerpt).where(Article.id == newest.id))
        if kept is not None and kept.title != newest.title:
            adopt_wording(kept, newest.title, excerpt)
    refresh_stories(session, tz, stories)
    report["applied"] = True
    report["stories_refreshed"] = len(stories)
    return report
