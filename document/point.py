"""A point: one x/y position, in whatever unit the caller measures in.

The drawn lines, the traced strokes, the pixels a shape covers and the origins a
sheet lays text at are all points; naming the pair keeps the two coordinates
from being read in the wrong order (the class of bug a bare tuple hides). It is
a `NamedTuple` so a point still unpacks as `x, y` and serialises as `[x, y]` —
the wire of a point is its pair.
"""

from __future__ import annotations

from typing import NamedTuple


class Point(NamedTuple):
    """One x/y position: page pixels, or normalised 0..1 where the caller says so."""

    x: float
    y: float
