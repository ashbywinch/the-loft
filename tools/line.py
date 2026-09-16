"""One line of writing: the marks on it, and the baseline fitted through them."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from tools.mark import SCALE, Mark
from tools.pagescale import PageScale
from tools.trace import Box


def dominant_row(values: Sequence[float], spread: float = 6.0) -> float:
    """The row a line's members most agree on: the centre of the densest
    window of values. One outlier (a crossbar word, a loop word, a descender)
    is never the mode - the survey's robust estimator for baselines (mark
    bottoms) and x-heights (measured sizes) alike."""
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return 0.0
    best: list[float] = []
    j = 0
    for i, low in enumerate(ordered):
        while j < len(ordered) and ordered[j] - low <= spread:
            j += 1
        window = ordered[i:j]
        if len(window) > len(best):
            best = window
    return float(sum(best) / len(best))


SLOPE_LIMIT = 0.13  # ≈7.5°: writing on a page never slopes more than this
MERGE_DIVISOR = 4  # pitch ÷ this: how close two fits are the same line
CAP = 0.8  # × pitch: a box never exceeds this above/below its baseline


@dataclass
class Line:
    """One line of writing: the shapes on it, and the baseline fitted through them."""

    shapes: list[Mark] = field(default_factory=list)
    a: float = 0.0
    b: float = 0.0

    def y_at(self, x: float) -> float:
        return self.a * x + self.b

    def distance(self, x: float, y: float) -> float:
        """Perpendicular distance from a point to this baseline."""
        return abs(y - self.y_at(x)) / math.sqrt(1 + self.a * self.a)

    def offset(self, shape: Mark) -> float:
        """Raw vertical offset of a shape's baseline from this line's, signed."""
        return shape.baseline - self.y_at(shape.cx)

    def signed_distance(self, shape: Mark) -> float:
        """The same offset, measured perpendicular to the baseline (cosine-corrected)."""
        return self.distance(shape.cx, shape.baseline) * (1 if self.offset(shape) >= 0 else -1)

    def refit(self) -> None:
        """Fit the baseline through the shapes' densest rows, sloped like writing.

        A fit beyond SLOPE_LIMIT is not a writing slope — it is a few shapes
        strung across the page by chance — so the line falls back to its median
        level.
        """
        xs = np.array([s.cx for s in self.shapes], dtype=float)
        ys = np.array([s.baseline for s in self.shapes], dtype=float)
        if len(xs) >= 2 and (xs.max() - xs.min()) > 1:
            slope, intercept = np.polyfit(xs, ys, 1)
            if abs(slope) <= SLOPE_LIMIT:
                self.a, self.b = float(slope), float(intercept)
                return
        self.a, self.b = 0.0, float(np.median(ys))

    def matches(self, other: Line, pitch: float, divisor: float = MERGE_DIVISOR) -> bool:
        """Is this the same line of writing as `other`?

        Compared WHERE THEY OVERLAP: a slope and an intercept are not comparable
        across different x ranges, so two fits of one physical line — one from
        its left half, one from its right — have different coefficients and the
        same baseline. Comparing coefficients left two identical lines in the
        model, which split a reviewer's stroke between them so no box could hold
        it. When the two fits do not overlap at all, the comparison is made
        between their centres.
        """
        xs_here = [s.cx for s in self.shapes]
        xs_there = [s.cx for s in other.shapes]
        low = max(min(xs_here), min(xs_there))
        high = min(max(xs_here), max(xs_there))
        samples = (
            [low, (low + high) / 2, high]
            if high > low
            else [(min(xs_here) + max(xs_here) + min(xs_there) + max(xs_there)) / 4]
        )
        return max(abs(self.y_at(x) - other.y_at(x)) for x in samples) < pitch / divisor

    def frame(self, shapes: list[Mark]) -> tuple[float, float, float, float, float, float]:
        """The local frame used to measure boxes: origin, and the unit vectors."""
        x_ref = shapes[0].cx if shapes else 0.0
        y_ref = self.y_at(x_ref)
        norm = math.sqrt(1 + self.a * self.a)
        return x_ref, y_ref, 1 / norm, self.a / norm, -self.a / norm, 1 / norm

    def project(self, shapes: list[Mark], shape: Mark) -> tuple[np.ndarray, np.ndarray]:
        """The shape's ink in the line's own frame: along the line, and across it."""
        x_ref, y_ref, ux, uy, nx, ny = self.frame(shapes)
        ys, xs = shape.pix
        return (xs - x_ref) * ux + (ys - y_ref) * uy, (xs - x_ref) * nx + (ys - y_ref) * ny

    def box(self, shapes: list[Mark], u0: float, u1: float, v0: float, v1: float) -> Box:
        """A box [u0, u1] along the line by [v0, v1] across it, in page pixels."""
        x_ref, y_ref, ux, uy, nx, ny = self.frame(shapes)
        return [
            [(x_ref + u * ux + v * nx) * SCALE, (y_ref + u * uy + v * ny) * SCALE]
            for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))
        ]

    def u_span(self, shapes: list[Mark], poly: Box) -> tuple[float, float]:
        """Where a box lies along this line, in the line's own units."""
        x_ref, y_ref, ux, uy, _, _ = self.frame(shapes)
        us = [((px / SCALE - x_ref) * ux + (py / SCALE - y_ref) * uy) for px, py in poly]
        return min(us), max(us)

    def boxes(self, scale: PageScale) -> list[Box]:
        """The line's ink as one or more boxes, split at column-sized x gaps.

        Measured alternative (2026-09-10): splitting relative to the line's own
        word gaps, and clipping each box at the midline to the neighbouring
        baseline. Both are in principle right — a fixed threshold cut 10 of this
        letter's lines, and a box should never contain a neighbour's baseline —
        but the pair regressed the jig (two lines ended in two boxes) and needs
        the composition re-derived, so the plain version stands.
        """
        pitch = scale.pitch
        shapes = sorted(self.shapes, key=lambda s: s.cx)
        if not shapes:
            return []
        runs: list[list[Mark]] = []
        current = [shapes[0]]
        edge = self.project(shapes, shapes[0])[0].max()
        for shape in shapes[1:]:
            along, _ = self.project(shapes, shape)
            if along.min() - edge > scale.join_gap:
                runs.append(current)
                current = [shape]
            else:
                current.append(shape)
            edge = max(edge, along.max())
        runs.append(current)
        out: list[Box] = []
        for run in runs:
            us, vs = zip(*(self.project(run, shape) for shape in run), strict=False)
            along, across = np.concatenate(us), np.concatenate(vs)
            out.append(
                self.box(
                    run,
                    float(along.min()),
                    float(along.max()),
                    max(float(np.percentile(across, 2)), -CAP * pitch / SCALE),
                    min(float(np.percentile(across, 98)), CAP * pitch / SCALE),
                )
            )
        return out
