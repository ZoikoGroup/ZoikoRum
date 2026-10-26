"""Trust lights: how a trust tier is shown to people.

The tier codes A/B/C stay as they are in the database, API fields, events and filters; people only ever see the
light. A is Green (fully verified), B is Amber (identity verified), C is Red (not verified yet).
"""

from __future__ import annotations

LIGHT_NAME = {"A": "Green", "B": "Amber", "C": "Red"}
LIGHT_LABEL = {"A": "Fully verified", "B": "Identity verified", "C": "Not verified yet"}


def light(tier: str | None) -> str:
    """'Green (fully verified)' for A; an unknown or missing tier reads as Red."""
    t = tier if tier in LIGHT_NAME else "C"
    return f"{LIGHT_NAME[t]} ({LIGHT_LABEL[t].lower()})"
