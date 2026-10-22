"""The reviewer's drawn row indications: one polyline per row they drew.

The reviewer draws a line along each row of writing the detector got wrong, and
the app sends those lines to the correction. The drawn lines are the
row-adjustments artefact: one polyline of normalised (0..1) x/y points per
line, under the wire key ``lines``. That file (and the HTTP body that carries
the same shape) is this class's wire — `from_dict` validates it and `to_dict`
writes it, so the file loader and the write seam share ONE rule: a line that is
not a polyline of [x, y] pairs is refused, never half-read.

The lines are normalised against the page, so they are measured into page
pixels by whoever knows the page's size (`Rows.adjust`), never here.
"""

from __future__ import annotations

from typing import Any

# one polyline per drawn line: normalised (0..1) points, as the app draws them
RowLines = list[list[tuple[float, float]]]


class RowAdjustments:
    """The reviewer's drawn row lines — the row-adjustments artefact."""

    def __init__(self, lines: RowLines) -> None:
        self.lines = lines

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RowAdjustments:
        """The drawn lines a row-adjustments file (or request body) holds.

        Every line must be a polyline of [x, y] pairs of numbers — the one rule
        the file loader and the HTTP boundary share."""
        lines = raw.get("lines")
        if not isinstance(lines, list):
            raise ValueError("not a RowAdjustments (no top-level 'lines' list)")
        for index, line in enumerate(lines):
            if not isinstance(line, list) or not all(_is_point(point) for point in line):
                raise ValueError(f"lines[{index}] — expected a polyline of [x, y] pairs")
        return cls(lines)

    def to_dict(self) -> dict[str, Any]:
        """The drawn lines as the row-adjustments artefact — as drawn."""
        return {"lines": [[list(point) for point in line] for line in self.lines]}


def _is_point(point: Any) -> bool:
    """Whether a value is one [x, y] point of a drawn polyline."""
    return isinstance(point, list) and len(point) == 2 and all(isinstance(c, (int, float)) for c in point)
