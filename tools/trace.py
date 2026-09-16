"""One line the reviewer traced: the strokes drawn along it, and the box they define.

A trace IS a line - the reviewer's statement about where a line of writing is.
Its box is the extent of what was drawn, extended to the marks the strokes
pass over, but by no more than the stroke tolerance beyond the strokes at
either end, so a trace cannot silently claim half the page.
"""

from __future__ import annotations

from dataclasses import dataclass

from tools.mark import SCALE, Mark

Box = list[list[float]]  # a quadrilateral's four corners, page pixels


@dataclass
class Trace:
    """A line the reviewer traced: the strokes drawn along it, and the box they define.

    A mark IS a line — the reviewer's statement about where a line of writing is.
    Its box is the extent of what was drawn, extended to the shapes the strokes
    pass over, but by no more than TOL beyond the strokes at either end, so a
    trace cannot silently claim half the page.
    """

    strokes: list[list[tuple[float, float]]]
    line_index: int
    covered: list[Mark]

    def box(self, stroke_tol: float) -> Box:
        points = [(p[0] / SCALE, p[1] / SCALE) for stroke in self.strokes for p in stroke]
        sx0, sx1 = min(p[0] for p in points), max(p[0] for p in points)
        sy0, sy1 = min(p[1] for p in points), max(p[1] for p in points)
        x0 = min(sx0, max(min((w.x0 for w in self.covered), default=sx0), sx0 - stroke_tol))
        x1 = max(sx1, min(max((w.x1 for w in self.covered), default=sx1), sx1 + stroke_tol))
        y0 = min(sy0, min((w.y0 for w in self.covered), default=sy0))
        y1 = max(sy1, max((w.y1 for w in self.covered), default=sy1))
        return [[x0 * SCALE, y0 * SCALE], [x1 * SCALE, y0 * SCALE], [x1 * SCALE, y1 * SCALE], [x0 * SCALE, y1 * SCALE]]
