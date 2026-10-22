"""One placement position a word's chip may take.

`candidates` returns them in the plan's order — "above, below, left, right,
then further along the perimeter" — and the first whose rect collides with no
other word's box wins. The verdict is the position's name; the rect is the
chip's footprint there, in section px.
"""

from __future__ import annotations

from dataclasses import dataclass

Box = tuple[float, float, float, float]  # x0, y0, x1, y1, section px


@dataclass(frozen=True)
class NumberingCandidate:
    """One candidate position for a word's chip."""

    verdict: str  # "corner" | "above" | "below" | "left" | "right" | the perimeter names
    rect: Box  # section px: the chip's footprint at this position
