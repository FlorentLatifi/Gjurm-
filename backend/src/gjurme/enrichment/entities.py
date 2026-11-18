"""One entity per real person or place: outlet self-references and Albanian case forms.

Two faults made the entity pages unreliable on live data (2026-11-17):

* **Self-references.** An outlet's feed repeats its own name in every excerpt (Reporteri.net's
  "Gazeta Online Reporteri"), and the keyword rules took it for a *person* in 1,444 articles,
  third among all names. An outlet's own name or alias (``aliases`` in sources.yaml) is never an
  entity of its own articles.
* **Case forms.** Albanian inflects names: *Kosova / Kosovë / Kosovës / Kosovën*, *Thaçi /
  Thaçit*, *Rama / Ramës*. The keyword rules keep the form the headline uses, and models do not
  always return the nominative they are asked for, so one place or person was split over up to
  five entities ("Kosovës" 2,474, "Kosova" 2,316, "Kosovë" 1,313, "Kosovën" 525) and every
  ranking, spike and co-mention counted each form apart.

Two names of a person or a place are forms of one name when every word but the last is the
same, and the last words share a stem (4 letters; 3 after a first name, for *Rama / Ramës*)
followed by case endings only. Organisations are left alone: their first word inflects
("Policia" / "Policisë së Kosovës") and short acronyms collide. The rule is deliberately
narrower than the grounding check's (``grounding._ENDINGS``): a false merge joins two people,
a missed one only leaves two entries apart. ``gjurme entities-cleanup`` merges the forms
already stored, after a dry run that lists them.

A third fault came from the keyword rules (two thirds of the articles on the free path): runs of
capitalised words joined by "i", "e", "të" became *persons*: "Vitomiricë të Pejës" (a village,
460 articles), "i Kosovës" (349), "Kuvendit të Kosovës" (201). Albanian personal names have no
such word, so a "person" with one is read again by the rules (``providers.rule_entity``): a
place, an organisation, or nothing.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from gjurme.enrichment.providers import CONNECTORS, rule_entity
from gjurme.enrichment.schema import EntityOut
from gjurme.ingestion.normalize import normalize_key

log = logging.getLogger(__name__)

INFLECTED_TYPES = frozenset({"person", "location"})
# Case and definiteness endings (diacritics folded: ë → e).
_ENDINGS = frozenset(
    {"", "a", "e", "i", "u", "n", "s", "t", "en", "es", "in", "it", "ut", "un", "se", "ne"}
)
# "Kosovo" is how English and Serbian name "Kosova"; a place only.
_LOCATION_ENDINGS = _ENDINGS | {"o"}
# Oblique forms (genitive, dative, ablative, accusative): never the name an entity is shown by.
_OBLIQUE = ("s", "n", "t", "se", "ne")
MIN_STEM = 4
MIN_STEM_AFTER_FIRST_NAME = 3


def _endings(etype: str) -> frozenset[str]:
    return _LOCATION_ENDINGS if etype == "location" else _ENDINGS


def _split(key: str) -> tuple[str, str]:
    head, _, last = key.rpartition(" ")
    return head, last


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


def _min_stem(head: str) -> int:
    return MIN_STEM_AFTER_FIRST_NAME if head else MIN_STEM


def same_entity(key_a: str, key_b: str, etype: str) -> bool:
    """Whether two normalized names of one type are forms of one name."""
    if key_a == key_b:
        return True
    if etype not in INFLECTED_TYPES:
        return False
    head_a, last_a = _split(key_a)
    head_b, last_b = _split(key_b)
    if head_a != head_b:
        return False
    n = _common_prefix(last_a, last_b)
    if n < _min_stem(head_a):
        return False
    stem_end = last_a[n - 1]
    return _is_ending(last_a[n:], stem_end, etype) and _is_ending(last_b[n:], stem_end, etype)


def _is_ending(ending: str, stem_end: str, etype: str) -> bool:
    """Whether ``ending`` after a stem ending in ``stem_end`` is a case ending. "-në" and "-së"
    follow an "-i" (Serbi|në, Shqipëri|së): Bera|ne (Berane) is not Bera|t (Berat). An "-n"
    does not follow an "-a" (Ramë|n, Kurti|n): Serbia|n is English, not a case of Serbia."""
    if ending not in _endings(etype):
        return False
    if ending in ("ne", "se"):
        return stem_end == "i"
    if ending == "n":
        return stem_end != "a"
    return True


def variant_keys(key: str, etype: str) -> set[str]:
    """Normalized names that may be another form of ``key`` (``key`` itself excluded)."""
    if etype not in INFLECTED_TYPES:
        return set()
    head, last = _split(key)
    endings = _endings(etype)
    stems = {
        last[: len(last) - len(e)]
        for e in endings
        if last.endswith(e) and len(last) - len(e) >= _min_stem(head)
    }
    prefix = f"{head} " if head else ""
    found = {f"{prefix}{stem}{e}" for stem in stems for e in endings}
    return {k for k in found if k != key and same_entity(key, k, etype)}


# ---------------------------------------------------------------------------------------------
# Outlets naming themselves
# ---------------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _self_names_by_outlet() -> dict[str, frozenset[str]]:
    """Display name → normalized names the outlet calls itself (name, name without its domain
    ending, aliases), for every outlet in sources.yaml."""
    from gjurme.sources.registry import load_registry  # the pipeline's import, not the API's

    names: dict[str, frozenset[str]] = {}
    for cfg in load_registry().sources:
        keys = {normalize_key(cfg.name), *(normalize_key(a) for a in cfg.aliases)}
        bare = cfg.name.rsplit(".", 1)[0] if "." in cfg.name else ""
        if bare:  # "Reporteri.net" → "reporteri", "Faktoje.al" → "faktoje"
            keys.add(normalize_key(bare))
        names[cfg.name] = frozenset(k for k in keys if k)
    return names


def self_names(source_name: str) -> frozenset[str]:
    return _self_names_by_outlet().get(source_name, frozenset())


def drop_self_references(
    entities: list[EntityOut], source_name: str
) -> tuple[list[EntityOut], list[EntityOut]]:
    """Split ``entities`` into those kept and the outlet's own names."""
    own = self_names(source_name)
    if not own:
        return list(entities), []
    kept: list[EntityOut] = []
    dropped: list[EntityOut] = []
    for ent in entities:
        (dropped if normalize_key(ent.name) in own else kept).append(ent)
    return kept, dropped


# ---------------------------------------------------------------------------------------------
# "Persons" that are no person
# ---------------------------------------------------------------------------------------------
def _is_junk_person(key: str, etype: str) -> bool:
    tokens = key.split()
    return bool(tokens) and (
        tokens[0] in CONNECTORS or (etype == "person" and any(t in CONNECTORS for t in tokens))
    )


def _reread(name: str, etype: str) -> tuple[str, str] | None:
    """What a junk entity is: a person by the rules' reading; another type keeps its type
    without the leading connector ("e Kosovës" → "Kosovës")."""
    if etype == "person":
        return rule_entity(name)
    words = name.split()
    while words and normalize_key(words[0]) in CONNECTORS:
        words = words[1:]
    return (" ".join(words), etype) if words else None


def retype_persons(entities: list[EntityOut]) -> tuple[list[EntityOut], list[str]]:
    """Read again a person with "i", "e", "të" in its name, and any name that starts with one:
    returns the entities to keep (retyped where needed) and the names changed or dropped."""
    kept: list[EntityOut] = []
    changed: list[str] = []
    for ent in entities:
        if not _is_junk_person(normalize_key(ent.name), ent.type):
            kept.append(ent)
            continue
        changed.append(ent.name)
        found = _reread(ent.name, ent.type)
        if found is not None and all(
            normalize_key(k.name) != normalize_key(found[0]) for k in kept
        ):
            kept.append(EntityOut(name=found[0], type=found[1]))
    return kept, changed


# ---------------------------------------------------------------------------------------------
# Merging the forms already stored
# ---------------------------------------------------------------------------------------------
@dataclass(slots=True)
class _Stored:
    id: int
    type: str
    key: str
    name: str
    mentions: int


def _display_rank(member: _Stored, common: int) -> tuple[int, int, int]:
    """Higher is the better name to show: a nominative form, for a place its definite form
    ("Kosova", "Serbia"), then the form used most."""
    ending = _split(member.key)[1][common:]
    nominative = not ending.endswith(_OBLIQUE)
    definite = member.type == "location" and ending.endswith("a")
    return (int(nominative), int(definite), member.mentions)


def _find(parent: list[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _groups(members: Iterable[_Stored]) -> list[list[_Stored]]:
    """Forms of one name, by union-find within buckets that share a type, the first words and
    the first letters of the last word (every match shares at least three)."""
    buckets: dict[tuple[str, str, str], list[_Stored]] = defaultdict(list)
    for m in members:
        head, last = _split(m.key)
        buckets[(m.type, head, last[:MIN_STEM_AFTER_FIRST_NAME])].append(m)
    groups: list[list[_Stored]] = []
    for bucket in buckets.values():
        if len(bucket) < 2:
            continue
        parent = list(range(len(bucket)))
        for i in range(len(bucket)):
            for j in range(i + 1, len(bucket)):
                if same_entity(bucket[i].key, bucket[j].key, bucket[i].type):
                    parent[_find(parent, i)] = _find(parent, j)
        by_root: dict[int, list[_Stored]] = defaultdict(list)
        for i, m in enumerate(bucket):
            by_root[_find(parent, i)].append(m)
        groups += [g for g in by_root.values() if len(g) > 1]
    return groups


def _merge_plan(groups: list[list[_Stored]]) -> list[dict[str, Any]]:
    plan = []
    for group in groups:
        lasts = [_split(m.key)[1] for m in group]
        common = min(_common_prefix(lasts[0], other) for other in lasts[1:])
        # The entity most linked to keeps its id (its page and links stay), with the best name.
        keep = max(group, key=lambda m: (m.mentions, -m.id))
        label = max((_display_rank(m, common), m.name) for m in group)[1]
        members = sorted(group, key=lambda m: (-m.mentions, m.id))
        plan.append(
            {
                "keep_id": keep.id,
                "name": label,
                "type": keep.type,
                "mentions": sum(m.mentions for m in group),
                "merged": [{"id": m.id, "name": m.name, "mentions": m.mentions} for m in members],
            }
        )
    return sorted(plan, key=lambda p: (-int(p["mentions"]), int(p["keep_id"])))


def cleanup_entities(session: Session, *, apply: bool, show: int = 40) -> dict[str, Any]:
    """Remove outlets' self-references from their own articles and merge the case forms of a
    person or place into one entity. Without ``apply`` nothing changes: the report lists what
    would. Idempotent: a second run finds nothing."""
    # 1. An outlet's own names, on its own articles
    self_refs: list[dict[str, Any]] = []
    for source_name, keys in _self_names_by_outlet().items():
        rows = session.execute(
            text("""
            SELECT e.id, e.name, e.type, count(*) AS links
            FROM core.entities e
            JOIN core.article_entities ae ON ae.entity_id = e.id
            JOIN core.articles a ON a.id = ae.article_id
            JOIN core.sources s ON s.id = a.source_id
            WHERE s.name = :source AND e.normalized_key = ANY(:keys)
            GROUP BY e.id, e.name, e.type"""),
            {"source": source_name, "keys": sorted(keys)},
        ).all()
        for r in rows:
            self_refs.append(
                {
                    "source": source_name,
                    "entity_id": r.id,
                    "name": r.name,
                    "type": r.type,
                    "links": r.links,
                }
            )
            if apply:
                session.execute(
                    text("""
                    DELETE FROM core.article_entities ae USING core.articles a, core.sources s
                    WHERE ae.entity_id = :eid AND a.id = ae.article_id AND s.id = a.source_id
                      AND s.name = :source"""),
                    {"eid": r.id, "source": source_name},
                )
    orphans = 0
    if apply and self_refs:
        orphans = session.execute(
            text("""
            DELETE FROM core.entities e WHERE e.id = ANY(:ids)
              AND NOT EXISTS (SELECT 1 FROM core.article_entities ae WHERE ae.entity_id = e.id)"""),
            {"ids": sorted({r["entity_id"] for r in self_refs})},
        ).rowcount  # type: ignore[attr-defined]

    # 2. "Persons" that are no person, and names that start with "i", "e", "të"
    junk: list[dict[str, Any]] = []
    for r in session.execute(
        text("""
        SELECT e.id, e.type, e.name, e.normalized_key, count(ae.article_id) AS links
        FROM core.entities e
        LEFT JOIN core.article_entities ae ON ae.entity_id = e.id
        WHERE split_part(e.normalized_key, ' ', 1) = ANY(:connectors)
           OR (e.type = 'person' AND string_to_array(e.normalized_key, ' ') && :connectors)
        GROUP BY e.id
        ORDER BY links DESC, e.id"""),
        {"connectors": sorted(CONNECTORS)},
    ):
        if not _is_junk_person(r.normalized_key, r.type):
            continue
        found = _reread(r.name, r.type)
        junk.append(
            {
                "entity_id": r.id,
                "name": r.name,
                "type": r.type,
                "links": r.links,
                "becomes": None if found is None else {"name": found[0], "type": found[1]},
            }
        )
        if not apply:
            continue
        if found is not None:
            target = session.execute(
                text("""
                INSERT INTO core.entities (type, normalized_key, name) VALUES (:t, :k, :n)
                ON CONFLICT (type, normalized_key) DO UPDATE SET type = EXCLUDED.type
                RETURNING id"""),
                {"t": found[1], "k": normalize_key(found[0]), "n": found[0]},
            ).scalar_one()
            if target == r.id:
                continue
            session.execute(
                text("""
                INSERT INTO core.article_entities (article_id, entity_id, published_date)
                SELECT article_id, :target, published_date FROM core.article_entities
                WHERE entity_id = :junk
                ON CONFLICT DO NOTHING"""),
                {"target": target, "junk": r.id},
            )
        # its links go with it (ON DELETE CASCADE)
        session.execute(text("DELETE FROM core.entities WHERE id = :junk"), {"junk": r.id})

    # 3. Case forms of one person or place (after step 2 when applied; a report counts the
    # forms as they are stored now)
    stored = [
        _Stored(r.id, r.type, r.normalized_key, r.name, r.mentions)
        for r in session.execute(
            text("""
            SELECT e.id, e.type, e.normalized_key, e.name, count(ae.article_id) AS mentions
            FROM core.entities e
            LEFT JOIN core.article_entities ae ON ae.entity_id = e.id
            WHERE e.type IN ('person', 'location')
            GROUP BY e.id""")
        )
    ]
    plan = _merge_plan(_groups(stored))
    if apply:
        for item in plan:
            others = [m["id"] for m in item["merged"] if m["id"] != item["keep_id"]]
            session.execute(
                text("""
                INSERT INTO core.article_entities (article_id, entity_id, published_date)
                SELECT article_id, :keep, published_date FROM core.article_entities
                WHERE entity_id = ANY(:others)
                ON CONFLICT DO NOTHING"""),
                {"keep": item["keep_id"], "others": others},
            )
            # the forms' links go with them (ON DELETE CASCADE)
            session.execute(
                text("DELETE FROM core.entities WHERE id = ANY(:others)"), {"others": others}
            )
            session.execute(
                text("UPDATE core.entities SET name = :name WHERE id = :keep"),
                {"name": item["name"], "keep": item["keep_id"]},
            )
    result = {
        "applied": apply,
        "self_references": self_refs,
        "self_reference_links": sum(r["links"] for r in self_refs),
        "self_reference_entities_deleted": orphans,
        "not_persons": len(junk),
        "not_persons_links": sum(j["links"] for j in junk),
        "not_persons_largest": junk[:show],
        "merge_groups": len(plan),
        "entities_merged_away": sum(len(p["merged"]) - 1 for p in plan),
        "largest_merges": plan[:show],
    }
    log.info(
        "entities cleanup",
        extra={
            k: v
            for k, v in result.items()
            if k not in ("self_references", "largest_merges", "not_persons_largest")
        },
    )
    return result
