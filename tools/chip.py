"""A word's number chip: which render id it carries and where it sits.

The chip is what the numbered render draws — a thin ring around the number's
own footprint, the page showing through — and what the caller reports when a
number found no free position.
"""

from __future__ import annotations

from dataclasses import dataclass

from document.colour import Colour

Box = tuple[float, float, float, float]  # x0, y0, x1, y1, section px


@dataclass(frozen=True)
class Chip:
    """A word's number chip: which render id it carries, its footprint and
    the font size its text is drawn at."""

    render_id: int  # 1-based, the number drawn on the chip
    rect: Box  # section px: the text bbox + CHIP_PAD, clamped to MAX_CHIP
    colour: Colour
    verdict: str  # "corner" | "above" | "below" | "left" | "right" | perimeter | UNPLACED
    font_size: float  # section px: the size the number is drawn at
