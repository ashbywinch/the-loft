"""A rectangle in page pixels: the geometry every box shares.

Every box on a page is a rectangle — a word's box, a row's band, a line's box —
and the wire record it travels as is the four fields `to_dict` writes and
`from_dict` reads, the one box shape the rows and the readings share.
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple


class Rectangle(NamedTuple):
    """A rectangle in page pixels: the geometry every box shares."""

    x0: float
    y0: float
    x1: float
    y1: float

    # the fields a box record carries; a record with any other field is a word's
    # record (its line, baseline and waistline are measures, not a box's)
    _FIELDS = ("x0", "y0", "x1", "y1")

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
        missing = [key for key in cls._FIELDS if key not in raw]
        if missing:
            raise ValueError(f"a box record is missing {sorted(missing)}")
        extra = [key for key in raw if key not in cls._FIELDS]
        if extra:
            raise ValueError(f"a box record carries fields that are not a box's: {sorted(extra)}")
        return cls(float(raw["x0"]), float(raw["y0"]), float(raw["x1"]), float(raw["y1"]))

    def to_dict(self) -> dict[str, Any]:
        """The rectangle as its wire box record — the four fields, and only
        those."""
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}

    def overlaps(self, other: Rectangle) -> bool:
        """Whether the two rectangles share any area — the test every box
        layout needs (a label that covers ink, two labels on one another)."""
        return self.x0 < other.x1 and other.x0 < self.x1 and self.y0 < other.y1 and other.y0 < self.y1

    def join_band(self, other: Rectangle) -> Rectangle:
        """The band joining this rectangle to the adjacent one in its row — as
        tall as the shorter of the two, centred on their vertical overlap (or
        their centres when they do not overlap). The row's tint, and the SVG
        the review screen draws, both use this one rule."""
        width = other.x0 - self.x1
        if width <= 0:
            return Rectangle(self.x1, min(self.y1, other.y1), self.x1, min(self.y1, other.y1))
        top = max(self.y0, other.y0)
        bottom = min(self.y1, other.y1)
        if bottom <= top:  # no vertical overlap: centre on the gap midpoint
            centre = (self.y1 + other.y0) / 2
            top, bottom = centre, centre
        height = min(self.height, other.height)
        mid = (top + bottom) / 2
        return Rectangle(self.x1, mid - height / 2, other.x0, mid + height / 2)

    def distance_to_segment(self, a: tuple[float, float], b: tuple[float, float]) -> float:
        """How far this rectangle lies from the segment a-b: 0 where the segment
        touches or crosses it. The reviewer's drawn line is a chain of such
        segments, and a word belongs to a line exactly when the line passes
        through (or touches) its box."""
        if self.crosses_segment(a, b):
            return 0.0
        corners = ((self.x0, self.y0), (self.x1, self.y0), (self.x0, self.y1), (self.x1, self.y1))
        return min(
            self.distance_to_point(*a),
            self.distance_to_point(*b),
            *(point_segment_distance(x, y, a, b) for x, y in corners),
        )

    def crosses_segment(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        """Whether the segment a-b crosses this box (Liang–Barsky's clip test)."""
        t0, t1 = 0.0, 1.0
        (ax, ay), (bx, by) = a, b
        dx, dy = bx - ax, by - ay
        for p, q in ((-dx, ax - self.x0), (dx, self.x1 - ax), (-dy, ay - self.y0), (dy, self.y1 - ay)):
            if p == 0:
                if q < 0:
                    return False
                continue
            r = q / p
            if p < 0:
                if r > t1:
                    return False
                t0 = max(t0, r)
            else:
                if r < t0:
                    return False
                t1 = min(t1, r)
        return True

    def distance_to_point(self, x: float, y: float) -> float:
        """How far the point lies from this box (0 inside it)."""
        return math.hypot(max(self.x0 - x, 0.0, x - self.x1), max(self.y0 - y, 0.0, y - self.y1))


def point_segment_distance(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    """How far the point lies from the segment a-b."""
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if not length2 else min(1.0, max(0.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
