"""A mark's rows, read against the page's fitted lines — the cut's proposals.

The reader cuts a mark where its ink stops being one word; the candidates come
from the rows' own fit to the lines. Which line a piece of ink belongs to is
this object's question, and so is the segmentation that follows from it: each
of a mark's rows is nearest one line, a run of rows on one line is a segment,
and a change of line is a cut where the ink narrows to a waist. The gap row and
the underline's band are the same reading of rows against lines.
"""

from __future__ import annotations

import numpy as np

from document.span import Span
from pipeline.detect.gap import Gap
from pipeline.detect.line import Line
from pipeline.detect.mark import Ink, Mark
from pipeline.detect.row_runs import RowRuns
from pipeline.detect.segment import Segment


def nearest_line(shape: Mark, lines: list[Line]) -> int:
    """The index of the line in `lines` this mark sits nearest — the index
    space of the list given, never of some wider fit it came from."""
    return min(range(len(lines)), key=lambda i: lines[i].distance(shape.cx, shape.baseline))


class RowFit:
    """A mark's rows, read against the page's fitted lines — the cut's proposals.

    The reader cuts a mark where its ink stops being one word; the candidates
    come from the rows' own fit to the lines. Which line a piece of ink belongs
    to (`line_of`, `majority`) is this object's question, and so is the
    segmentation that follows from it: each of a mark's rows is nearest one
    line, a run of rows on one line is a segment, and a change of line is a cut
    where the ink narrows to a waist. The underline's band of full-width rows
    is cut into its own segment, so the strip can classify and remove it."""

    ROW_MERGE = 2  # 1/2 px: rows this close belong to the same piece of a cut shape
    GAP_FRACTION = 0.25  # of the flanking ink: a row this much thinner is a gap
    GAP_WINDOW = 4  # rows either side whose median run is the flank
    GAP_MIN_FLANK = 3  # 1/2 px: a gap between scraps of ink cuts nothing
    WAIST_RUN = 10  # columns: a cut row running this far is a band of ink, not a stroke tip
    WAIST_OVERLAP = 0.5  # of the shorter longest-run: this much overlap is one band

    def __init__(self, lines: list[Line]) -> None:
        self.lines = lines

    def line_of(self, shape: Mark) -> int:
        """The fitted line this mark sits nearest — its row in the writing,
        among the lines this writing holds (`nearest_line`)."""
        return nearest_line(shape, self.lines)

    def majority(self, per_row: dict[int, list[int]], ys: list[int]) -> int:
        """The fitted line most of these rows sit nearest — which side of a
        gap this ink belongs to."""
        counts: dict[int, int] = {}
        for y in ys:
            xc = sum(per_row[y]) / len(per_row[y])
            line = min(range(len(self.lines)), key=lambda i: self.lines[i].distance(xc, y))
            counts[line] = counts.get(line, 0) + 1
        return max(counts, key=counts.__getitem__)

    def segments(self, shape: Mark) -> list[Segment]:
        """The cuts the shape's row fit proposes: its ink rows grouped by
        which fitted line each row's centre is nearest, split where the
        assignment changes and the ink narrows to a waist — plus the band
        split: rows whose runs span most of the mark's width are a stroke's
        ink, and a stroke inside a mark is a line to strip (an underline
        welded under its words; user 2026-09-18: 'a regression in your code
        to identify underlines'). A single stray long row is a letter's
        stroke, not a line."""
        per_row = shape.rows()
        ys, xs = shape.pix
        runs = Ink(ys, xs).longest_runs()
        segments: list[Segment] = []
        for y in sorted(per_row):
            xc = sum(per_row[y]) / len(per_row[y])
            nearest = min(range(len(self.lines)), key=lambda i: self.lines[i].distance(xc, y))
            last = segments[-1] if segments else None
            if last is None:
                segments.append(Segment(nearest, y, y))
                continue
            if (last.line == nearest and y - last.y1 <= RowFit.ROW_MERGE) or (
                last.line != nearest and not is_waist(per_row, runs, last.y1, y)
            ):
                segments[-1] = Segment(last.line, last.y0, y)
            else:
                segments.append(Segment(nearest, y, y))
        return self._band_cut(segments, shape, runs)

    def gap(self, shape: Mark) -> int | None:
        """The row whose ink is a deep local minimum, if any: the boundary
        between stacked words or crossed-out rows (user: 'cut where the
        gap is'). The row's longest run must be at most a quarter of the
        flanking ink, the flanks substantial, and the two sides on
        DIFFERENT fitted lines — a gap inside one line is a word's letter
        space."""
        row_runs = self._row_runs(shape)
        gap = self._deepest_gap(row_runs.rows, row_runs.runs)
        if gap.depth >= RowFit.GAP_FRACTION:
            return None  # strict: a tie at the boundary is a letter's internal gap
        per_row = shape.rows()
        upper = [y for y in row_runs.rows if y <= gap.row]
        lower = [y for y in row_runs.rows if y > gap.row]
        if not upper or not lower:
            return None
        if self.majority(per_row, upper) == self.majority(per_row, lower):
            return None
        return gap.row

    @staticmethod
    def _row_runs(shape: Mark) -> RowRuns:
        """The shape's rows and each row's longest run."""
        runs = Ink(np.asarray(shape.pix[0]).astype(int), np.asarray(shape.pix[1]).astype(int)).longest_runs()
        return RowRuns(rows=sorted(runs), runs=runs)

    @staticmethod
    def _deepest_gap(rows: list[int], runs: dict[int, int]) -> Gap:
        """The deepest local ink minimum among the rows, away from the mark's
        edges, with both flanks substantial."""
        best = Gap(depth=1.0, row=rows[0])
        for i, y in enumerate(rows):
            if i < RowFit.GAP_WINDOW or i >= len(rows) - RowFit.GAP_WINDOW:
                continue
            above = float(np.median([runs[rows[j]] for j in range(i - RowFit.GAP_WINDOW, i)]))
            below = float(np.median([runs[rows[j]] for j in range(i + 1, i + 1 + RowFit.GAP_WINDOW)]))
            flank = max(above, below)
            if flank < RowFit.GAP_MIN_FLANK:
                continue
            score = runs[y] / flank
            if score < best.depth:
                best = Gap(depth=score, row=y)
        return best

    @staticmethod
    def _band_cut(segments: list[Segment], shape: Mark, runs: dict[int, int]) -> list[Segment]:
        """The underline's band of rows, cut into its own segment so the
        strip can classify and remove it."""
        ys, xs = shape.pix
        width = float(xs.max() - xs.min() + 1)
        band = [y for y in shape.rows() if runs[y] >= Mark.BAND_RUN * width]
        if len(band) < 2:
            return segments
        lo, hi = band[0], band[-1]
        out: list[Segment] = []
        for segment in segments:
            if segment.y1 < lo or segment.y0 > hi:
                out.append(segment)
                continue
            if segment.y0 < lo:
                out.append(Segment(segment.line, segment.y0, lo - 1))
            out.append(Segment(segment.line, lo, hi))
            if segment.y1 > hi:
                out.append(Segment(segment.line, hi + 1, segment.y1))
        return out


def _longest_interval(cols: list[int]) -> Span:
    """The longest continuous column run on one row: the band's own span."""
    ordered = sorted(cols)
    best, start, prev = Span(ordered[0], ordered[0]), ordered[0], ordered[0]
    for x in ordered[1:]:
        if x == prev + 1:
            prev = x
        else:
            if prev - start > best.end - best.start:
                best = Span(start, prev)
            start, prev = x, x
    if prev - start > best.end - best.start:
        best = Span(start, prev)
    return best


def is_waist(per_row: dict[int, list[int]], runs: dict[int, int], top: int, bottom: int) -> bool:
    """A cut between rows `top` and `bottom` is real unless it runs through a
    word's body: BOTH cut rows carry long runs AND those longest runs overlap
    each other column-wise — one continuous band of ink the fit sliced
    mid-body. A word boundary breaks at least one side: a short run, or two
    long runs that do not overlap. (User rulings 2026-09-13: the bug through
    widening ink; the eight one-word pins; the Pupil block.)"""
    if min(runs[top], runs[bottom]) < RowFit.WAIST_RUN:
        return True
    top_iv = _longest_interval(per_row[top])
    bot_iv = _longest_interval(per_row[bottom])
    overlap = max(0, min(top_iv.end, bot_iv.end) - max(top_iv.start, bot_iv.start) + 1)
    return overlap < RowFit.WAIST_OVERLAP * min(top_iv.end - top_iv.start + 1, bot_iv.end - bot_iv.start + 1)
