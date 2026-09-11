"""Grouping word boxes into lines of writing.

Input: word boxes in page pixels - the word finder's output. No image, no
strokes, nothing that could carry a person's handwriting or words. Output: the
rows (each a list of indices into the input) and each row's box (the union of
its words' bounds).

Each rule is its own small function, tested on its own:

* `is_rule` - a box far wider than it is tall is an underline or a rule, not a
  word on a line;
* `is_small` - a box below the page's writing height is written in a smaller
  hand; when such boxes form a run (`small_runs`) they are their own line, an
  aside, rather than riders inside a full-height row;
* `group_rows` - the rest group by their centres, and a gap wider than half the
  line spacing starts a new row;
* `merge_interleaved` - two rows whose boxes interleave within half the spacing
  are one row (a long sloped line cut in two by the gap rule).

The validator (`validate_against_lines`) checks a grouping against the yellow
lines the reviewer drew: each line's words should land in one row. That is the
reality check; the detector itself never sees the lines.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

# the page's own ruler, in the same units as the boxes (page pixels)
RULE_ASPECT = 8.0  # x height: this wide for its height is a rule, not a word
WRITING_FLOOR = 0.9  # x writing height: below this a box is a smaller hand
SMALL_ASPECT = 1.2  # x height: smaller and the box is spot-like, not word-like
SMALL_MIN_HEIGHT = 14.0  # page px: below this it is a dot or a tick
RUN_LENGTH = 3  # how many small boxes in a row make a run of writing
RUN_GAP = 60.0  # page px of whitespace between small boxes of one run
RUN_BAND = 40.0  # page px: how close vertically two small boxes must sit


class Box(NamedTuple):
    """One word's bounding box, page pixels."""

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


def gap(left: Box, right: Box) -> float:
    """The whitespace between two boxes, horizontally."""
    return max(0.0, abs(left.cx - right.cx) - (left.width + right.width) / 2)


def is_rule(box: Box) -> bool:
    """An underline or a rule: much wider than it is tall, so not a word."""
    return box.width >= RULE_ASPECT * box.height


def is_small(box: Box, writing_height: float) -> bool:
    """Written in a smaller hand than the page's, and word-like rather than a
    spot: not a dot (too small in both directions) and wider than it is tall."""
    return SMALL_MIN_HEIGHT <= box.height < WRITING_FLOOR * writing_height and box.width >= SMALL_ASPECT * box.height


def group_rows(boxes: Sequence[Box], spacing: float, slope: float = 0.0) -> list[list[int]]:
    """Rows of word indices: each box's level is its centre with the page's
    slope removed, and a gap wider than half the spacing starts a new row."""
    level = [box.cy - slope * box.cx for box in boxes]
    rows: list[list[int]] = []
    for index in sorted(range(len(boxes)), key=lambda i: level[i]):
        if not rows or level[index] - level[rows[-1][-1]] > spacing / 2:
            rows.append([index])
        else:
            rows[-1].append(index)
    return [sorted(row, key=lambda i: boxes[i].x0) for row in rows]


def fit_row(row: Sequence[int], boxes: Sequence[Box]) -> tuple[float, float]:
    """The line through a row's centres: (slope, intercept)."""
    xs = [boxes[i].cx for i in row]
    ys = [boxes[i].cy for i in row]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=False)) / spread if spread else 0.0
    return slope, mean_y - slope * mean_x


def same_line(here: Sequence[int], there: Sequence[int], boxes: Sequence[Box], spacing: float) -> bool:
    """Two rows are one line when each row's fitted line passes through the
    other's words: the fits, compared at the OTHER row's centre.

    The fits, not the row means: a long line cut in two gives two rows whose
    means differ by the cut, while their fits describe the same line. Their
    x-ranges need not overlap - a gap cut divides the line's x-span - so the
    comparison is at each row's own centre, and the bound is 0.45x the spacing
    rather than half, keeping genuinely adjacent rows (a full spacing apart)
    clear of the bound with room to spare.
    """
    here_fit, there_fit = fit_row(here, boxes), fit_row(there, boxes)
    centre_there = sum(boxes[j].cx for j in there) / len(there)
    centre_here = sum(boxes[i].cx for i in here) / len(here)
    bound = 0.45 * spacing
    at_here = abs(here_fit[0] * centre_here + here_fit[1] - (there_fit[0] * centre_here + there_fit[1]))
    at_there = abs(here_fit[0] * centre_there + here_fit[1] - (there_fit[0] * centre_there + there_fit[1]))
    return at_here < bound and at_there < bound


def merge_interleaved(rows: list[list[int]], boxes: Sequence[Box], spacing: float) -> list[list[int]]:
    """One row wherever two rows are the same line (see `same_line`)."""
    merged = True
    while merged:
        merged = False
        for first in range(len(rows)):
            for second in range(first + 1, len(rows)):
                if same_line(rows[first], rows[second], boxes, spacing):
                    rows[first] = sorted(rows[first] + rows[second], key=lambda i: boxes[i].x0)
                    rows.pop(second)
                    merged = True
                    break
            if merged:
                break
    return rows


def small_runs(boxes: Sequence[Box], writing_height: float, rule_boxes: set[int]) -> list[list[int]]:
    """Runs of small word-like boxes: three or more, chained by whitespace, in
    one band. Each run is an aside written in a smaller hand - its own line."""
    candidates = [i for i, box in enumerate(boxes) if i not in rule_boxes and is_small(box, writing_height)]
    runs: list[list[int]] = []
    for index in candidates:
        box = boxes[index]
        joined = [
            run
            for run in runs
            if any(gap(boxes[other], box) < RUN_GAP and abs(boxes[other].y0 - box.y0) < RUN_BAND for other in run)
        ]
        if joined:
            joined[0].append(index)
        else:
            runs.append([index])
    return [[i for i in sorted(run, key=lambda i: boxes[i].x0)] for run in runs if len(run) >= RUN_LENGTH]


def row_boxes(rows: Sequence[Sequence[int]], boxes: Sequence[Box]) -> list[Box]:
    """Each row's box: the union of its words' bounds."""
    return [
        Box(
            x0=min(boxes[i].x0 for i in row),
            y0=min(boxes[i].y0 for i in row),
            x1=max(boxes[i].x1 for i in row),
            y1=max(boxes[i].y1 for i in row),
        )
        for row in rows
        if row
    ]


def rows_of(boxes: Sequence[Box], spacing: float, writing_height: float) -> list[list[int]]:
    """The whole grouping: rules out, small runs out, the rest by centre."""
    rule_boxes = {i for i, box in enumerate(boxes) if is_rule(box)}
    words = [i for i in range(len(boxes)) if i not in rule_boxes]
    word_boxes = [boxes[i] for i in words]
    rows = merge_interleaved(group_rows(word_boxes, spacing), word_boxes, spacing)
    rows = [[words[i] for i in row] for row in rows]
    runs = small_runs(boxes, writing_height, rule_boxes)
    if runs:
        run_indices = {i for run in runs for i in run}
        rows = [[i for i in row if i not in run_indices] for row in rows]
    return [row for row in rows if row] + runs
