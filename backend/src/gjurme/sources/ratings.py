"""Editorial ratings of sources: perspective (bias), factuality and ownership.

These are the dimensions a coverage bar splits a story by (as on Ground News). They are
*editorial judgements made by the operator*, declared per source in ``sources.yaml`` with a
note on what they are based on, never computed or guessed by the software. A source without a
documented rating stays ``unrated`` and is shown as such. See docs/SOURCES.md#ratings.
"""

from __future__ import annotations

from typing import Literal

# Ground News uses a 7-point scale; GJURMË keeps 5 points plus "unrated" and folds them into the
# three groups of the coverage bar.
BIAS_VALUES: tuple[str, ...] = ("left", "lean_left", "center", "lean_right", "right", "unrated")
FACTUALITY_VALUES: tuple[str, ...] = ("very_high", "high", "mixed", "low", "very_low", "unrated")
OWNERSHIP_VALUES: tuple[str, ...] = (
    "private",  # privately owned company
    "media_group",  # part of a larger media or business group
    "public",  # national public service broadcaster
    "state",  # controlled by a government
    "public_international",  # foreign public broadcaster (e.g. RFE/RL, BBC, DW)
    "nonprofit",  # NGO / non-profit newsroom
    "unknown",
)

Bias = Literal["left", "lean_left", "center", "lean_right", "right", "unrated"]
BiasGroup = Literal["left", "center", "right", "unrated"]
BIAS_GROUPS: tuple[str, ...] = ("left", "center", "right", "unrated")

_GROUP: dict[str, str] = {
    "left": "left",
    "lean_left": "left",
    "center": "center",
    "lean_right": "right",
    "right": "right",
    "unrated": "unrated",
}


def bias_group(bias: str) -> str:
    """Fold a 5-point bias rating into the coverage bar's three groups (+ unrated)."""
    return _GROUP.get(bias, "unrated")
