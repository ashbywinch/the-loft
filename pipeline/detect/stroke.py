"""One stroke the reviewer drew: the points it passes through.

strokes.json holds each stroke as a list of normalized [x, y] pairs, so the class
owns that wire too (`from_wire`). The page's own conversion stays with `Strokes`,
which knows the page: a drawn point is clamped to it and scaled to its pixels,
because the sketch records normalized coordinates and a drag outside the image
can exceed [0, 1].
"""

from __future__ import annotations

from dataclasses import dataclass

from document.point import Point


@dataclass(frozen=True)
class Stroke:
    """One drawn stroke: the points it passes through, in the caller's unit."""

    points: list[Point]

    @classmethod
    def from_wire(cls, raw: list[list[float]]) -> Stroke:
        """The stroke strokes.json records: its points, as normalized pairs."""
        return cls([Point(float(x), float(y)) for x, y in raw])
