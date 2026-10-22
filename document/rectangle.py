"""A rectangle in page pixels: the geometry every box shares.

Every box on a page is a rectangle — a word's box, a row's band, a line's box —
and the wire record it travels as is the four fields `to_dict` writes and
`from_dict` reads, the one box shape the rows and the readings share.
"""

from __future__ import annotations

from typing import Any, NamedTuple

# the fields a box record carries; a record with any other field is a word's
# record (its line, baseline and waistline are measures, not a box's)
BOX_FIELDS = ("x0", "y0", "x1", "y1")


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

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Rectangle:
        """The rectangle a wire box record states — the four fields, and only
        those: a record carrying a measure (a word's line, baseline or
        waistline) is a word's record, not a box's."""
        if not isinstance(raw, dict):
            raise ValueError("a box record is not an object")
        missing = [key for key in BOX_FIELDS if key not in raw]
        if missing:
            raise ValueError(f"a box record is missing {sorted(missing)}")
        extra = [key for key in raw if key not in BOX_FIELDS]
        if extra:
            raise ValueError(f"a box record carries fields that are not a box's: {sorted(extra)}")
        return cls(float(raw["x0"]), float(raw["y0"]), float(raw["x1"]), float(raw["y1"]))

    def to_dict(self) -> dict[str, Any]:
        """The rectangle as its wire box record — the four fields, and only
        those."""
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}


def overlaps(left: Rectangle, right: Rectangle) -> bool:
    """Whether two rectangles share any area — the test every box layout needs
    (a label that covers ink, two labels on one another)."""
    return left.x0 < right.x1 and right.x0 < left.x1 and left.y0 < right.y1 and right.y0 < left.y1


def gap(left: Rectangle, right: Rectangle) -> float:
    """The whitespace between two rectangles, horizontally."""
    return max(0.0, abs(left.cx - right.cx) - (left.width + right.width) / 2)
