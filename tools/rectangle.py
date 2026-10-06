"""A rectangle in page pixels: the geometry every box shares."""

from __future__ import annotations

from typing import NamedTuple


class Rectangle(NamedTuple):
    """A rectangle in page pixels: the geometry every box shares."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def overlaps(left: Rectangle, right: Rectangle) -> bool:
    """Whether two rectangles share any area — the test every box layout needs
    (a label that covers ink, two labels on one another)."""
    return left.x0 < right.x1 and right.x0 < left.x1 and left.y0 < right.y1 and right.y0 < left.y1


def gap(left: Rectangle, right: Rectangle) -> float:
    """The whitespace between two rectangles, horizontally."""
    return max(0.0, abs(left.cx - right.cx) - (left.width + right.width) / 2)
