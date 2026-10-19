"""The scale of the normalised projection: page pixels per normalised pixel.

`split_by_bands` measures on a copy of the box resized to a fixed height, so
every normalised coordinate has to be converted back to page pixels — and the
pair is what does it: how many page pixels one normalised column spans, and
how many one normalised row spans. The two numbers are meaningless apart
(swapping them is the bug the named fields rule out), so they travel as one
record, and the conversion is the record's own.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectionScale:
    """Page pixels per normalised pixel, `x` and `y`."""

    x: float
    y: float

    def page_x(self, origin: float, column: float) -> float:
        """The page x of a normalised column, measured from `origin`."""
        return origin + column * self.x

    def page_y(self, origin: float, row: float) -> float:
        """The page y of a normalised row, measured from `origin`."""
        return origin + row * self.y
