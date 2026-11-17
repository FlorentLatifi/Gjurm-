"""Story clustering evaluation: labels, pair scores, and the labelled live sample."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gjurme.config import Settings
from gjurme.stories.clustering import ClusterParams
from gjurme.stories.evaluation import (
    Labelled,
    Sample,
    dumps,
    evaluate,
    load_sample,
    load_samples,
    predict,
    relation,
    score,
)
from gjurme.stories.similarity import EXCERPT_MAX_WORDS, STOPWORDS, content_words

SAMPLES = Path(__file__).parents[1] / "fixtures" / "stories"
T0 = datetime(2026, 11, 17, 18, 0, tzinfo=UTC)


def _a(i: int, event: str | None, *, related: tuple[str, ...] = (), outlet: str = "a") -> Labelled:
    return Labelled(i, outlet, T0 + timedelta(minutes=i), f"Titulli {i}", event, related=related)


def _defaults() -> ClusterParams:
    return ClusterParams.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]


def test_relation_of_labels() -> None:
    assert relation(_a(1, "x"), _a(2, "x")) == "same"
    assert relation(_a(1, "x/a"), _a(2, "x/a")) == "same"
    # parts of one event may share a story or not
    assert relation(_a(1, "x/a"), _a(2, "x/b")) == "related"
    assert relation(_a(1, "x"), _a(2, "x/b")) == "related"
    # so may an article that is part of a second event
    assert relation(_a(1, "y/c", related=("x",)), _a(2, "x/b")) == "related"
    assert relation(_a(1, "x"), _a(2, "y")) == "different"
    assert relation(_a(1, None), _a(2, None)) == "different"


def test_score_counts_pairs_and_events() -> None:
    articles = [
        _a(1, "x"),
        _a(2, "x"),
        _a(3, "x"),  # split from 1 and 2
        _a(4, "y/a"),
        _a(5, "y/b"),  # related to 4, merged with it: not scored
        _a(6, None),  # merged into x: wrong
    ]
    s = score(articles, {1: 10, 2: 10, 6: 10, 3: 11, 4: 12, 5: 12})
    assert (s.true_pairs, s.false_pairs, s.missed_pairs, s.related_pairs) == (1, 2, 2, 1)
    assert s.precision == pytest.approx(1 / 3)
    assert s.recall == pytest.approx(1 / 3)
    assert (s.stories, s.mixed_stories, s.events, s.split_events) == (2, 1, 1, 1)
    assert {(a.id, b.id) for a, b in s.missed} == {(1, 3), (2, 3)}
    # nothing to score counts as perfect, not as zero
    empty = score([_a(1, None)], {1: 1})
    assert empty.precision == empty.recall == 1.0


def test_predict_groups_paraphrases_and_separates_lookalikes() -> None:
    def art(i: int, title: str, event: str, place: str, minutes: int) -> Labelled:
        return Labelled(i, f"o{i}", T0 + timedelta(minutes=minutes), title, event, places=(place,))

    sample = Sample(
        "toy",
        (
            art(1, "Zjarr në një ndërtesë banimi në Prizren", "fire-prizren", "Prizren", 0),
            art(
                2,
                "Zjarr në ndërtesën e banimit në Prizren, pa të lënduar",
                "fire-prizren",
                "Prizren",
                20,
            ),
            art(3, "Zjarr në një ndërtesë banimi në Gjakovë", "fire-gjakove", "Gjakovë", 40),
            art(4, "Kuvendi në Prishtinë miraton buxhetin e vitit", "budget", "Prishtinë", 60),
        ),
    )
    story = predict(sample, _defaults())
    assert story[1] == story[2]
    assert story[3] != story[1]
    assert story[4] not in {story[1], story[3]}


def test_sample_round_trip(tmp_path: Path) -> None:
    sample = {
        "collected_at": "2026-11-17T21:37:07Z",
        "articles": [
            {"id": 1, "outlet": "a", "published_at": "2026-11-17T20:00:00Z", "title": "T",
             "words": ["kuvendi"], "people": [], "places": ["Prizren"], "orgs": [],
             "duplicate_of": None, "event": "x", "related": ["y"]},
            {"id": 2, "outlet": "b", "published_at": "2026-11-17T20:05:00Z", "title": "U",
             "duplicate_of": 1, "event": None},
        ],
    }  # fmt: skip
    path = tmp_path / "s.json"
    path.write_text(dumps(sample), "utf-8")
    assert json.loads(path.read_text("utf-8")) == sample
    loaded = load_sample(path)
    assert loaded.name == "s"
    first, second = loaded.articles
    assert first.related == ("y",) and first.places == ("Prizren",) and first.event == "x"
    assert second.duplicate_of == 1 and second.words == () and second.event is None
    assert [s.name for s in load_samples([tmp_path])] == ["s"]


# --------------------------------------------------------------------------------------------
# The labelled live sample (tests/fixtures/stories)
# --------------------------------------------------------------------------------------------
def test_live_samples_hold_derived_data_only() -> None:
    """ADR-003: no excerpt text — only its content words, deduplicated and sorted."""
    files = sorted(SAMPLES.glob("*.json"))
    assert files
    for f in files:
        data = json.loads(f.read_text("utf-8"))
        ids = {a["id"] for a in data["articles"]}
        for a in data["articles"]:
            assert set(a) <= {
                "id", "outlet", "published_at", "title", "url", "words", "people", "places",
                "orgs", "duplicate_of", "event", "related",
            }  # fmt: skip
            words = a["words"]
            assert words == sorted(set(words)) and len(words) <= EXCERPT_MAX_WORDS
            assert content_words(" ".join(words)) == words  # no stopwords, nothing to strip
            assert not set(words) & STOPWORDS
            assert a["duplicate_of"] is None or a["duplicate_of"] in ids


def test_live_sample_scores_with_the_default_settings() -> None:
    """The measured quality of the defaults on real news; a change that lowers it must say why
    in docs/DECISIONS.md (ADR-020) and update these numbers."""
    s = evaluate(load_samples([SAMPLES]), _defaults())
    assert s.precision >= 0.99
    assert s.recall >= 0.70
    assert s.mixed_stories <= 1
