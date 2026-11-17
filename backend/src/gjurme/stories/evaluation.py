"""Measure story clustering against hand-labelled real news (``gjurme stories-eval``).

The evaluation set is a sample of live articles exported by ``gjurme stories-sample`` (the
*Source validation* workflow runs it on the live feeds) in which every article carries the
event it reports, labelled by hand. Only metadata and derived data are kept (ADR-003):
headline, outlet, time, URL, the analysis' entity names and the excerpt's *content words* — the
folded, stopword-free words of its first ``EXCERPT_MAX_WORDS`` words, deduplicated and sorted,
which is all the clustering reads of it and cannot be read back as the text.

**Labels.** ``event`` names the event an article reports; articles with the same label must
share a story. ``null`` is an event no other article of the sample reports. A label with a
slash (``specialja/presidency``) is a part of a larger event: two articles with the same part
must share a story, two with different parts of one event are *related* and may go either way —
a reaction to a verdict can be a story of its own or part of the verdict's. ``related`` lists
other events an article belongs to as well (one press conference about a verdict and a law).

**Scores.** Over pairs of articles: *precision* is the share of the pairs the clustering put in
one story that report the same event (a false pair is two events merged: wrong coverage), and
*recall* is the share of the same-event pairs it put in one story (a missed pair is an event
split: less coverage, maybe a false blindspot). Related pairs count for neither. Large events
weigh more (pairs grow with the square of their size), so the event counts are given too: how
many stories mix events and how many events are split.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from gjurme.stories.clustering import ClusterParams, _load, _Row, group
from gjurme.stories.similarity import EXCERPT_MAX_WORDS, Doc, content_words, resolve_names

_META_SQL = text("""
    SELECT a.id, s.slug, a.url FROM core.articles a JOIN core.sources s ON s.id = a.source_id
    WHERE a.id = ANY(:ids)
""")


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------------------------------------
# Export
# ------------------------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------------------------
# Labelled samples
# ------------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Labelled:
    id: int
    outlet: str
    published_at: datetime
    title: str
    event: str | None
    words: tuple[str, ...] = ()
    people: tuple[str, ...] = ()
    places: tuple[str, ...] = ()
    orgs: tuple[str, ...] = ()
    duplicate_of: int | None = None
    related: tuple[str, ...] = ()  # other events (top-level labels) this article is part of

    @property
    def events(self) -> frozenset[str]:
        """The top-level events this article belongs to."""
        top = (self.event.split("/")[0],) if self.event is not None else ()
        return frozenset((*top, *self.related))

    def doc(self) -> Doc:
        return Doc(self.id, self.title, " ".join(self.words), self.people, self.places, self.orgs)


@dataclass(frozen=True, slots=True)
class Sample:
    name: str
    articles: tuple[Labelled, ...]


def load_sample(path: Path) -> Sample:
    data = json.loads(path.read_text("utf-8"))
    articles = tuple(
        Labelled(
            id=a["id"],
            outlet=a["outlet"],
            published_at=datetime.fromisoformat(a["published_at"]),
            title=a["title"],
            event=a.get("event"),
            words=tuple(a.get("words", ())),
            people=tuple(a.get("people", ())),
            places=tuple(a.get("places", ())),
            orgs=tuple(a.get("orgs", ())),
            duplicate_of=a.get("duplicate_of"),
            related=tuple(a.get("related", ())),
        )
        for a in data["articles"]
    )
    return Sample(path.stem, articles)


def load_samples(paths: Iterable[Path]) -> list[Sample]:
    """Every ``*.json`` sample in ``paths`` (files or directories), sorted by name."""
    files: list[Path] = []
    for p in paths:
        files.extend(sorted(p.glob("*.json")) if p.is_dir() else [p])
    return [load_sample(f) for f in files]


def predict(sample: Sample, params: ClusterParams) -> dict[int, int]:
    """Cluster the sample from scratch, in publication order, as one batch: article → story."""
    ordered = sorted(sample.articles, key=lambda a: (a.published_at, a.id))
    rows = [_Row(a.id, a.published_at, None, a.duplicate_of, a.doc()) for a in ordered]
    resolve_names([r.doc for r in rows])
    return group(rows, {r.id for r in rows}, params).story_of


# ------------------------------------------------------------------------------------------------
# Scores
# ------------------------------------------------------------------------------------------------
def relation(a: Labelled, b: Labelled) -> str:
    """Same event (or the same part of one), related (parts of one event: scored neither way)
    or different: "same", "related" or "different"."""
    if a.event is not None and a.event == b.event:
        return "same"
    return "related" if a.events & b.events else "different"


Pair = tuple[Labelled, Labelled]


@dataclass(slots=True)
class Scores:
    true_pairs: int = 0
    false_pairs: int = 0  # different events in one story
    missed_pairs: int = 0  # one event in different stories
    related_pairs: int = 0  # related parts of one event in one story (not scored)
    events: int = 0  # labelled events with two or more articles
    split_events: int = 0  # ... spread over more than one story
    stories: int = 0  # stories with two or more articles
    mixed_stories: int = 0  # ... with articles of different events
    false: list[Pair] = field(default_factory=list)
    missed: list[Pair] = field(default_factory=list)

    @property
    def precision(self) -> float:
        n = self.true_pairs + self.false_pairs
        return self.true_pairs / n if n else 1.0

    @property
    def recall(self) -> float:
        n = self.true_pairs + self.missed_pairs
        return self.true_pairs / n if n else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def add(self, other: Scores) -> None:
        self.true_pairs += other.true_pairs
        self.false_pairs += other.false_pairs
        self.missed_pairs += other.missed_pairs
        self.related_pairs += other.related_pairs
        self.events += other.events
        self.split_events += other.split_events
        self.stories += other.stories
        self.mixed_stories += other.mixed_stories
        self.false.extend(other.false)
        self.missed.extend(other.missed)


def score(articles: Sequence[Labelled], story_of: dict[int, int]) -> Scores:
    s = Scores()
    by_story: dict[int, list[Labelled]] = defaultdict(list)
    by_event: dict[str, list[Labelled]] = defaultdict(list)
    for a in articles:
        by_story[story_of[a.id]].append(a)
        if a.event is not None:
            by_event[a.event].append(a)
    for members in by_story.values():
        if len(members) < 2:
            continue
        s.stories += 1
        mixed = False
        for a, b in combinations(members, 2):
            rel = relation(a, b)
            if rel == "same":
                s.true_pairs += 1
            elif rel == "related":
                s.related_pairs += 1
            else:
                s.false_pairs += 1
                s.false.append((a, b))
                mixed = True
        s.mixed_stories += mixed
    for members in by_event.values():
        if len(members) < 2:
            continue
        s.events += 1
        s.split_events += len({story_of[a.id] for a in members}) > 1
        for a, b in combinations(members, 2):
            if story_of[a.id] != story_of[b.id]:
                s.missed_pairs += 1
                s.missed.append((a, b))
    return s


def evaluate(samples: Sequence[Sample], params: ClusterParams) -> Scores:
    """Scores of ``params`` over all ``samples`` (pairs summed; each sample clustered alone)."""
    total = Scores()
    for sample in samples:
        total.add(score(sample.articles, predict(sample, params)))
    return total


# ------------------------------------------------------------------------------------------------
# Report
# ------------------------------------------------------------------------------------------------
def summary_line(s: Scores) -> str:
    return (
        f"precision {s.precision:.3f}  recall {s.recall:.3f}  F1 {s.f1:.3f}  "
        f"(pairs: {s.true_pairs} right, {s.false_pairs} wrong, {s.missed_pairs} missed, "
        f"{s.related_pairs} related; stories mixing events {s.mixed_stories}/{s.stories}, "
        f"events split {s.split_events}/{s.events})"
    )


def _pair(a: Labelled, b: Labelled) -> str:
    return (
        f"  [{a.outlet}] {a.title}  ({a.event or '—'})\n"
        f"  [{b.outlet}] {b.title}  ({b.event or '—'})"
    )


def report(
    samples: Sequence[Sample], params: ClusterParams, *, errors: int = 20
) -> tuple[Scores, str]:
    s = evaluate(samples, params)
    articles = sum(len(x.articles) for x in samples)
    out = [
        f"{len(samples)} sample(s), {articles} articles; {params}",
        summary_line(s),
    ]
    if s.false:
        out += ["", f"Wrong pairs (different events, one story): {len(s.false)}"]
        out += [_pair(a, b) for a, b in s.false[:errors]]
    if s.missed:
        out += ["", f"Missed pairs (one event, different stories): {len(s.missed)}"]
        out += [_pair(a, b) for a, b in s.missed[:errors]]
    return s, "\n".join(out)
