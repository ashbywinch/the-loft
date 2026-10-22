"""The reviewer's drawn lines, sampled: one polyline of page-pixel points each.

The jig works from the trace's strokes — normalised 0..1 points — sampled onto
the page, so every drawn line is one polyline of `Point`s. The shape is a list
of lists because that IS what the callers iterate (a line indexes as a list of
points); naming it keeps the two nesting levels from being read the wrong way
round, the way `Box` names the traced polygons.
"""

from __future__ import annotations

from document.point import Point

DrawnLines = list[list[Point]]
