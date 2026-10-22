"""One numbered word: the render id it carries, where it sits, its hue.

Stage 1's entry — the pure data the render draws and the tests and locate
logic read: the word's render id (its reading-order position, 1-based), the
index it held in the caller's word list, its box in page pixels, and the
palette colour it is outlined in.
"""

from __future__ import annotations

from dataclasses import dataclass

Box = tuple[float, float, float, float]  # x0, y0, x1, y1, page px


@dataclass(frozen=True)
class NumberedWord:
    """One word of the numbered render."""

    render_id: int  # 1-based, the number drawn on the chip
    page_index: int  # the word's position in the caller's word list
    box: Box  # page px: the word's own box
    colour: tuple[int, int, int]  # the palette hue its box is outlined in
