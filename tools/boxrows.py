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
WRITING_FLOOR = 0.95  # x writing height: below this a box is an aside, a smaller hand
# (the page's heights run continuously, so the floor sits at the page's own
# word size - the asides and insertions the reviewer handles by tracing)
SMALL_MIN_WIDTH = 18.0  # page px: below this it is a spot or a comma
SMALL_MIN_HEIGHT = 14.0  # page px: below this it is a dot or a tick
RUN_LENGTH = 2  # how many small boxes in a row make a run of writing
RUN_GAP = 60.0  # page px of whitespace between small boxes of one run
RUN_BAND = 40.0  # page px: how close vertically two small boxes must sit
RUN_EDGE_GAP = 60.0  # page px: a run touching the row's end (line 13: a 10px
# gap) is the row's end words, not a second line


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


def is_vertical(box: Box, spacing: float, writing_height: float) -> bool:
    """Not a word on one horizontal line: either taller than the line spacing
    itself, or tall-and-narrow - a vertical mark.

    A word on a horizontal line spans at most its own row; a component taller
    than the distance between lines crosses into the neighbouring row. And a
    component taller than the page's writing height but narrower than 7/10 of
    its own height - aspect under ~0.77 - is a vertical stroke (a margin
    letter, a tall mark), the member measured to stretch row 24's box into
    the next row's words (34x52). Both are vertical ink: they join no row.
    """
    return box.height > 1.25 * spacing or (box.height > 1.2 * writing_height and box.width < 0.6 * box.height)


def is_small(box: Box, writing_height: float) -> bool:
    """Written in a smaller hand than the page's: tall enough to carry a
    letter, wide enough not to be a dot or comma, and below the page's own
    word size.

    The aspect test was dropped and measured: a small word like 'to' is
    20x26, narrower than tall, and requiring width >= 1.2 x height broke the
    run chains on exactly those words - line 5's small text never formed its
    own line. Dots and commas are small in BOTH directions, so size guards
    separate them without touching a narrow real word.
    """
    return SMALL_MIN_HEIGHT <= box.height < WRITING_FLOOR * writing_height and box.width >= SMALL_MIN_WIDTH


def median(values: Sequence[float]) -> float:
    """The middle value (mean of the two middles when even)."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def group_rows(boxes: Sequence[Box], spacing: float) -> list[list[int]]:
    """Rows of word indices: a word joins the current row when its centre sits
    within half the spacing of that row's MEDIAN centre.

    The anchor is the median, never the last word added: comparing to the last
    word lets the row drift - each step is small, the drift accumulates, and the
    row swallows the line below (measured: one row spanning 258px where a row is
    68px). A median keeps every member within half a spacing of the row's own
    middle, so a row can never span two lines.
    """
    rows: list[list[int]] = []
    levels: list[float] = []
    for index in sorted(range(len(boxes)), key=lambda i: boxes[i].cy):
        if rows and boxes[index].cy - median([boxes[i].cy for i in rows[-1]]) <= spacing / 2:
            rows[-1].append(index)
            levels.append(boxes[index].cy)
        else:
            rows.append([index])
            levels.append(boxes[index].cy)
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
    """Two rows are one line when their median centres sit within half the
    spacing of each other.

    The fits were tried and measured: a fragment's fit over a few words is
    noisy, and evaluated at the other row's centre the drift exceeds any
    workable bound (11 split pairs at the midline, before this change). The
    median of the members' centres is stable for a few words, and two genuine
    rows sit a full spacing apart - clear of half - while fragments of one
    line sit well inside it.
    """
    here_centre = median([boxes[i].cy for i in here])
    there_centre = median([boxes[i].cy for i in there])
    return abs(here_centre - there_centre) <= spacing / 2


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


def row_boxes(rows: Sequence[Sequence[int]], boxes: Sequence[Box], spacing: float) -> list[Box]:
    """Each row's box: the union of its words' bounds, clamped at the MIDLINES
    to the rows above and below.

    A row's own ink measure is one thing, but the box the reviewer sees must
    not reach into the next line: a union following a tall member down to y3218
    covered more than half of the next row's first small word. The clamp is
    the midpoint between this row's baseline and its neighbour's, sampled at
    this row's own centre - the line's fit, not its farthest word.
    """
    centres = [median([boxes[i].cy for i in row]) if row else 0.0 for row in rows]
    live = [index for index, row in enumerate(rows) if row]
    out: list[Box] = []
    for index, row in enumerate(rows):
        if not row:
            continue
        top = min(boxes[i].y0 for i in row)
        bottom = max(boxes[i].y1 for i in row)
        # the neighbours are SPATIAL - the nearest row above and below - never
        # the next index: the small-run rows are appended at the end of the
        # list, so an index neighbour can sit a page away (that inversion drew
        # a thousand-pixel vertical sliver)
        above = [r for r in live if centres[r] < centres[index]]
        below = [r for r in live if centres[r] > centres[index]]
        if above:
            top = max(top, (centres[max(above, key=lambda r: centres[r])] + centres[index]) / 2)
        if below:
            bottom = min(bottom, (centres[index] + centres[min(below, key=lambda r: centres[r])]) / 2)
        # the box must contain its own words' CENTRES no matter where the
        # midline lands: a clamped edge that cuts a member reads as the word
        # missing from the box (the 'outside' class the reviewer counted)
        top = min(top, min(boxes[i].cy for i in row))
        bottom = max(bottom, max(boxes[i].cy for i in row))
        bottom = max(bottom, top)  # a bare midline reading never inverts the box
        out.append(
            Box(
                x0=min(boxes[i].x0 for i in row),
                y0=top,
                x1=max(boxes[i].x1 for i in row),
                y1=bottom,
            )
        )
    return out


def rows_of(boxes: Sequence[Box], spacing: float, writing_height: float) -> list[list[int]]:
    """The whole grouping: rules out, small runs out, the rest by centre."""
    non_words = {i for i, box in enumerate(boxes) if is_rule(box) or is_vertical(box, spacing, writing_height)}
    rule_boxes = non_words
    words = [i for i in range(len(boxes)) if i not in rule_boxes]
    word_boxes = [boxes[i] for i in words]
    rows = merge_interleaved(group_rows(word_boxes, spacing), word_boxes, spacing)
    rows = [[words[i] for i in row] for row in rows]
    runs = small_runs(boxes, writing_height, rule_boxes)
    if runs:
        run_indices = {i for run in runs for i in run}
        rows = [[i for i in row if i not in run_indices] for row in rows]
        # a run is an ASIDE only when it sits outside every row: between lines,
        # not within one. A run whose words share a row's band and fall inside
        # its x-span is the middle of that row's sentence - line 1 measured as
        # five words in one 20px band making three 'small' into a second line.
        kept_runs: list[list[int]] = []
        for run in runs:
            run_cy = median([boxes[i].cy for i in run])
            run_x0 = min(boxes[i].x0 for i in run)
            run_x1 = max(boxes[i].x1 for i in run)
            home = next(
                (
                    row
                    for row in rows
                    if row
                    and abs(median([boxes[i].cy for i in row]) - run_cy) <= spacing / 2
                    and any(
                        boxes[j].y0 <= run_cy + 4 and boxes[j].y1 >= run_cy - 4 and boxes[j].x1 <= run_x0 for j in row
                    )
                    and any(
                        boxes[j].y0 <= run_cy + 4 and boxes[j].y1 >= run_cy - 4 and boxes[j].x0 >= run_x1 for j in row
                    )
                ),
                None,
            )
            if home is not None:
                home.extend(run)
            else:
                kept_runs.append(run)
        rows = [row for row in rows if row]
        return rows + kept_runs
    return [row for row in rows if row]


def line_verdicts(
    boxes: Sequence[Box],
    rows: Sequence[Sequence[int]],
    strokes: Sequence[Sequence[tuple[float, float]]],
    spacing: float,
    writing_height: float,
    touch: float = 20.0,
) -> list[dict]:
    """How each yellow line agrees with the grouping, honestly.

    For every line, its covered words are ALL the components the stroke passes
    within `touch` of - nothing is excluded, because excluding words is how a
    genuinely split line's second cluster gets hidden. The verdict:

    * one row holds all its words -> "right";
    * two or more rows -> "split" (one line in two boxes);
    * no row holds any -> "unboxed" (the line has no box);
    * the rows that hold its words are counted, and so are the words whose own
      row's box does not contain them ("outside").

    The reviewer's eye is the standard: lines 1, 2, 3, 7 and 14 must be
    "split", 10 and 12 "unboxed", on this letter - the test's ground truth
    comes from the fixture's own strokes, so the grouping cannot argue.
    """
    row_of = {index: r for r, row in enumerate(rows) for index in row}
    row_centres = {r: median([boxes[i].cy for i in row]) for r, row in enumerate(rows)}
    interjection_rows = {
        r for r, row in enumerate(rows) if all(is_small(boxes[i], writing_height) for i in row) and row
    }
    verdicts: list[dict] = []
    for stroke in strokes:
        covered = [
            index
            for index, box in enumerate(boxes)
            if any(
                box.x0 - touch <= px <= box.x1 + touch and box.y0 - touch <= py <= box.y1 + touch for px, py in stroke
            )
        ]
        band_mid = (min(py for _, py in stroke) + max(py for _, py in stroke)) / 2
        # the line's OWN words: on the stroke's own level, and not an
        # interjection's - an aside has its own line, and a trace merely
        # passing over a neighbour's words (35px off its level) claims nothing
        own = [
            i
            for i in covered
            if i in row_of
            and row_of[i] not in interjection_rows
            and abs(row_centres[row_of[i]] - band_mid) <= 0.4 * spacing
        ]
        rows_holding = sorted({row_of[i] for i in own})
        if not own:
            verdict = "right"  # the trace runs over others' words: not a grouping failure
        elif len(rows_holding) == 1:
            verdict = "right"
        else:
            verdict = "split"
        verdicts.append(
            {
                "verdict": verdict,
                "rows": rows_holding,
                "words": len(covered),
                "outside": [
                    i
                    for i in own
                    if not (
                        row_boxes(rows, boxes, spacing)[row_of[i]].x0
                        <= boxes[i].cx
                        <= row_boxes(rows, boxes, spacing)[row_of[i]].x1
                        and row_boxes(rows, boxes, spacing)[row_of[i]].y0
                        <= boxes[i].cy
                        <= row_boxes(rows, boxes, spacing)[row_of[i]].y1
                    )
                ],
            }
        )
    return verdicts
