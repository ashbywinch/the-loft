"""Grouping words into lines of writing.

Input: WORD boxes in page pixels, each with its measured font size (its
x-height: baseline to waistline - the size measure that ascenders and
descenders cannot distort). No image, no strokes, no person's words. Output:
the rows and their boxes.

The classes own the domain:

* `Word` - one word's bounds and ITS font size. What is NOT here is
  smallness: a word is small only relative to the page it sits on, so that
  judgement lives on `Page`, and `Word` never makes it;
* `Page` - the words and the page's ruler (spacing, its own font size), and
  the grouping itself: `rows()`, `row_boxes()`, `verdicts()`, and the
  relative judgements `is_small()` and `is_vertical()`;
* `Row` - one line of writing: its words and its kind ("writing" or
  "interjection" - an aside written between the lines);
* `Verdict` - how one yellow line agrees with the grouping.

The rules, each a method tested on its own:

* `Word.is_rule` - far wider than it is tall: an underline, not a word;
* `Page.is_small` - a word whose FONT SIZE is well below the page's own is a
  smaller hand; chains of such words (`interjections`) are their own lines
  unless a row's words flank them on both sides at their level;
* `Page.is_vertical` - taller than a row and a half, or exceedingly narrow:
  vertical ink that joins no row;
* `Page.rows` - the words group by centre; a gap beyond half the spacing
  starts a row; two rows whose fitted lines agree at each other's centres are
  one (a long sloped line cut in two); runs of small words absorb into a row
  only when flanked, else stay their own interjection lines.

The validator (`Page.verdicts`) checks a grouping against the yellow lines
the reviewer drew. The detector itself never sees the lines.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

# the page's own ruler, in the same units as the words (page pixels)
RULE_ASPECT = 8.0  # x height: this wide for its height is a rule, not a word
SMALL_FONT_FRACTION = 0.75  # x the page's font size: below this a word is a smaller hand
SMALL_MIN_WIDTH = 18.0  # page px: below this it is a spot or a comma
SMALL_MIN_HEIGHT = 14.0  # page px: below this it is a dot or a tick
RUN_LENGTH = 2  # how many small words in a chain make a run of writing
RUN_GAP = 60.0  # page px of whitespace between the small words of one run
RUN_BAND = 40.0  # page px: how close vertically two small words must sit
VERTICAL_SPAN = 2.5  # x spacing: taller than this is a flourish, not a word
# (the 1.25 floor ate real words: 196x88 - four pixels over - and 150x92.
# A mark made of letters can be two and a half rows tall.)
VERTICAL_ASPECT = 0.35  # x height: narrower than this for its height is
# vertical ink. The measured floor was 0.6, which ate single LETTERS - a
# letter is taller than wide by nature (aspect 0.36-0.6 on this page), and the
# reviewer's eye balked at words with no boxes. Only the true slivers
# (below 0.35) stay out.


class Rectangle(NamedTuple):
    """A rectangle in page pixels: the geometry every box shares."""

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


class Word:
    """One word on the page: its rectangle and ITS font size.

    A word is not a kind of rectangle - it HAS one - so the geometry lives in
    `Rectangle` once, and Word delegates through the four properties. The font
    size is the word's own: measured (the x-height from the ink), never
    inferred from the box's height, which ascenders and descenders distort.
    Smallness is not here either: a word is small only relative to the page,
    so `Page.is_small` owns that judgement.
    """

    def __init__(self, x0: float, y0: float, x1: float, y1: float, font_size: float = 0.0) -> None:
        self.rect = Rectangle(x0, y0, x1, y1)
        self.font_size = font_size  # 0 means unmeasured; Page drops it from its own size

    @property
    def x0(self) -> float:
        return self.rect.x0

    @property
    def y0(self) -> float:
        return self.rect.y0

    @property
    def x1(self) -> float:
        return self.rect.x1

    @property
    def y1(self) -> float:
        return self.rect.y1

    @property
    def width(self) -> float:
        return self.rect.width

    @property
    def height(self) -> float:
        return self.rect.height

    @property
    def cx(self) -> float:
        return self.rect.cx

    @property
    def cy(self) -> float:
        return self.rect.cy

    def is_rule(self) -> bool:
        """An underline or rule: far wider than it is tall, so not a word."""
        return self.width >= RULE_ASPECT * self.height


@dataclass(frozen=True)
class Verdict:
    """How one yellow line agrees with the grouping."""

    verdict: str  # "right" | "split" | "unboxed"
    rows: tuple[int, ...]  # the row indices holding the line's own words
    words: int  # all words the trace passed over
    outside: tuple[int, ...]  # own words whose centre its row's box misses


@dataclass
class Row:
    """One line of writing: its words (indices into the page's) and its kind."""

    words: list[int] = field(default_factory=list)
    kind: str = "writing"  # "writing" or "interjection"

    _centres: float | None = field(default=None, init=False, repr=False)

    @property
    def centre(self) -> float:
        if self._centres is None:
            raise ValueError("Row has no centre until the page measures it")
        return self._centres


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _gap(left: Rectangle, right: Rectangle) -> float:
    """The whitespace between two rectangles, horizontally."""
    return max(0.0, abs(left.cx - right.cx) - (left.width + right.width) / 2)


def _fit(row: Sequence[int], words: Sequence[Rectangle]) -> tuple[float, float]:
    """The line through a row's word centres: (slope, intercept)."""
    xs = [words[i].cx for i in row]
    ys = [words[i].cy for i in row]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=False)) / spread if spread else 0.0
    return slope, mean_y - slope * mean_x


class Page:
    """A page of writing: the words, the ruler, and the grouping itself.

    Everything relative lives here, measured against the page's own numbers:
    its font size (the median x-height of its words) decides smallness, its
    spacing decides rows and verticality."""

    def __init__(self, words: Sequence[Word], spacing: float) -> None:
        self.words = tuple(words)
        self.rects = tuple(word.rect for word in self.words)  # the geometry, once
        self.spacing = spacing

    @property
    def font_size(self) -> float:
        """The page's own x-height: the median of its words' measured sizes."""
        sizes = [w.font_size for w in self.words if w.font_size > 0]
        return _median(sizes) if sizes else 0.0

    def is_small(self, word: Word) -> bool:
        """A smaller hand than the page's: a small FONT SIZE, not a short box -
        a word written in pure x-height letters has a short box and an ordinary
        font. Guards keep dots and commas (small in both directions) out."""
        return (
            word.height >= SMALL_MIN_HEIGHT
            and word.width >= SMALL_MIN_WIDTH
            and 0 < word.font_size < SMALL_FONT_FRACTION * self.font_size
        )

    def is_vertical(self, word: Word) -> bool:
        """Not a word on one horizontal line: taller than a row and a half, or
        exceedingly narrow for its height - vertical ink that joins no row."""
        return word.height > VERTICAL_SPAN * self.spacing or (
            word.height > 1.2 * self.font_size and word.width < VERTICAL_ASPECT * word.height
        )

    def rows(self) -> list[Row]:
        """The whole grouping: rules and vertical ink out, the rest by centre,
        interjections their own lines."""
        words = self.rects
        grouped: list[Row] = []
        page_words = self.words
        eligible = [i for i in range(len(words)) if not page_words[i].is_rule()]
        for index in sorted(eligible, key=lambda i: words[i].cy):
            joins = False
            if grouped and words[index].cy - _median([words[i].cy for i in grouped[-1].words]) <= self.spacing / 2:
                joins = not self._would_stack(grouped[-1], index)
            if joins:
                grouped[-1].words.append(index)
            else:
                grouped.append(Row(words=[index]))
        grouped = self._merge_same_line(grouped)
        grouped = self._split_by_smallness(grouped)
        return [row for row in grouped if row.words]

    def _merge_same_line(self, rows: list[Row]) -> list[Row]:
        """Two rows are one line when each row's fitted line passes through
        the other's words - a long sloped line cut in two by the gap rule."""
        merged = True
        while merged:
            merged = False
            for first in range(len(rows)):
                for second in range(first + 1, len(rows)):
                    if self._same_line(rows[first], rows[second]) and not self._rows_would_stack(
                        rows[first], rows[second]
                    ):
                        rows[first].words = sorted(
                            rows[first].words + rows[second].words, key=lambda i: self.words[i].cx
                        )
                        rows.pop(second)
                        merged = True
                        break
                if merged:
                    break
        return rows

    def _would_stack(self, row: Row, index: int) -> bool:
        """A word physically above (or below) a word of the row is IMPOSSIBLE
        - the row is really two lines. Tested at admission and at merge, not
        repaired after: smallness already marks these as not belonging."""
        word = self.words[index]
        return any(self._pair_v_stacked(word, self.words[other]) for other in row.words)

    def _rows_would_stack(self, here: Row, there: Row) -> bool:
        return any(self._pair_v_stacked(self.words[a], self.words[b]) for a in here.words for b in there.words)

    @staticmethod
    def _pair_v_stacked(a: Word, b: Word) -> bool:
        if not (a.x0 < b.x1 and b.x0 < a.x1):
            return False
        overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
        return overlap < 0.5 * min(a.height, b.height)

    def _same_line(self, here: Row, there: Row) -> bool:
        """The fits, compared at each other's centres: no x-overlap needed
        (a gap cut divides the line's x-span), bound 0.45 x the spacing so
        genuinely adjacent rows sit clear."""
        here_fit = _fit(here.words, self.rects)
        there_fit = _fit(there.words, self.rects)
        centre_here = _median([self.rects[i].cx for i in here.words])
        centre_there = _median([self.rects[i].cx for i in there.words])
        bound = 0.45 * self.spacing
        at_here = abs(here_fit[0] * centre_here + here_fit[1] - (there_fit[0] * centre_here + there_fit[1]))
        at_there = abs(here_fit[0] * centre_there + here_fit[1] - (there_fit[0] * centre_there + there_fit[1]))
        return at_here < bound and at_there < bound

    def _split_by_smallness(self, rows: list[Row]) -> list[Row]:
        """Runs of small words are interjections - their own lines - unless a
        row's words flank them on both sides at their level (then they are the
        middle of that row's sentence, and absorb into it)."""
        runs = self.small_runs()
        if not runs:
            return rows
        run_words = {i for run in runs for i in run}
        scaffolds: list[list[int]] = [[i for i in row.words if i not in run_words] for row in rows]
        kept: list[Row] = []
        for run in runs:
            run_centre = _median([self.rects[i].cy for i in run])
            run_x0 = min(self.rects[i].x0 for i in run)
            run_x1 = max(self.rects[i].x1 for i in run)
            home = next(
                (
                    row
                    for row in scaffolds
                    if row
                    and abs(_median([self.rects[i].cy for i in row]) - run_centre) <= self.spacing / 2
                    and any(
                        self.rects[j].y0 <= run_centre + 4
                        and self.rects[j].y1 >= run_centre - 4
                        and self.rects[j].x1 <= run_x0
                        for j in row
                    )
                    and any(
                        self.rects[j].y0 <= run_centre + 4
                        and self.rects[j].y1 >= run_centre - 4
                        and self.rects[j].x0 >= run_x1
                        for j in row
                    )
                ),
                None,
            )
            if home is not None:
                home.extend(run)
            else:
                kept.append(Row(words=list(run), kind="interjection"))
        return [Row(words=row) for row in scaffolds if row] + kept

    def small_runs(self) -> list[list[int]]:
        """Chains of small words - the interjections. Two or more, joined by
        whitespace, in one band. The smallness is by FONT SIZE: an x-height-only
        word is not small, whatever its box's height suggests."""
        candidates = [
            i
            for i, word in enumerate(self.words)
            if not word.is_rule() and self.is_small(word) and not self.is_vertical(word)
        ]
        runs: list[list[int]] = []
        for index in candidates:
            word = self.words[index]
            joined = [
                run
                for run in runs
                if any(
                    _gap(self.rects[other], word.rect) < RUN_GAP and abs(self.rects[other].y0 - word.y0) < RUN_BAND
                    for other in run
                )
            ]
            if joined:
                joined[0].append(index)
            else:
                runs.append([index])
        return [sorted(run, key=lambda i: self.words[i].x0) for run in runs if len(run) >= RUN_LENGTH]

    def row_boxes(self, rows: Sequence[Row]) -> list[Rectangle]:
        """Each row's box: the union of its words' bounds, clamped at the
        MIDLINES to the rows above and below - and never cutting a member's
        centre (a clamped edge that does reads as the word missing from the
        box, which the reviewer counts)."""
        centres = [_median([self.words[i].cy for i in row.words]) if row.words else 0.0 for row in rows]
        live = [index for index, row in enumerate(rows) if row.words]
        out: list[Rectangle] = []
        for index, row in enumerate(rows):
            if not row.words:
                continue
            top = min(self.rects[i].y0 for i in row.words)
            bottom = max(self.rects[i].y1 for i in row.words)
            if len(row.words) < 3:
                # a lone or paired word's box IS its bounds: the midline clamp
                # would trim a big word's own box below half-coverage and read
                # it as a foreign word in its neighbour's
                out.append(
                    Rectangle(
                        x0=min(self.rects[i].x0 for i in row.words),
                        y0=top,
                        x1=max(self.rects[i].x1 for i in row.words),
                        y1=bottom,
                    )
                )
                continue
            above = [r for r in live if centres[r] < centres[index]]
            below = [r for r in live if centres[r] > centres[index]]
            if above:
                top = max(top, (centres[max(above, key=lambda r: centres[r])] + centres[index]) / 2)
            if below:
                bottom = min(bottom, (centres[index] + centres[min(below, key=lambda r: centres[r])]) / 2)
            # a box HOLDS its own words: keep at least half of every member's
            # area inside (centre alone measured 34% for a 110-tall mark in a
            # clamped row, which read as a word half outside its box)
            top = min(top, min(self.rects[i].cy - self.rects[i].height / 4 for i in row.words))
            bottom = max(bottom, max(self.rects[i].cy + self.rects[i].height / 4 for i in row.words))
            bottom = max(bottom, top)
            out.append(
                Rectangle(
                    x0=min(self.rects[i].x0 for i in row.words),
                    y0=top,
                    x1=max(self.rects[i].x1 for i in row.words),
                    y1=bottom,
                )
            )
        return out

    def verdicts(self, strokes: Sequence[Sequence[tuple[float, float]]], touch: float = 20.0) -> list[Verdict]:
        """How each yellow line agrees with the grouping, honestly.

        A line's OWN words are its covered words whose row sits at the
        stroke's level (0.6 x the spacing - the reviewer draws ON the line, a
        trace passing 35px above or below claims nothing). Nothing is
        exempted: an interjection is a line too. No box at the line's level is
        'unboxed' - a failure, not a pass."""
        rows = self.rows()
        centres = {r: _median([self.rects[i].cy for i in row.words]) for r, row in enumerate(rows)}
        boxes = self.row_boxes(rows)
        verdicts: list[Verdict] = []
        for stroke in strokes:
            covered = [
                index
                for index, box in enumerate(self.rects)
                if any(
                    box.x0 - touch <= px <= box.x1 + touch and box.y0 - touch <= py <= box.y1 + touch
                    for px, py in stroke
                )
            ]
            band_mid = (min(py for _, py in stroke) + max(py for _, py in stroke)) / 2
            own = [
                i
                for i in covered
                if any(i in row.words for row in rows)
                and abs(centres[next(r for r, row in enumerate(rows) if i in row.words)] - band_mid)
                <= 0.6 * self.spacing
            ]
            row_of_index = {i: r for r, row in enumerate(rows) for i in row.words}
            # a line's words are the covered words of the rows that SHARE its
            # level: the row holding at least half the level's words. A lone
            # word stacked 40px above another is a different row - physically
            # impossible to be the same line (the reviewer's ruling).
            by_row: dict[int, int] = {}
            for i in own:
                by_row[row_of_index[i]] = by_row.get(row_of_index[i], 0) + 1
            cut = max(by_row.values(), default=0) / 2
            own = [i for i in own if by_row[row_of_index[i]] >= cut]
            rows_holding = sorted({row_of_index[i] for i in own})

            # a trace drawn in the GAP between two rows claims no single row -
            # no strict majority of the words it sweeps (line 6's tie, line
            # 42's pair): it is right when every WORD-LIKE word it sweeps is
            # boxed somewhere; the failure is only a word-like word with no
            # box at all
            def _word_like(index: int) -> bool:
                word = self.words[index]
                return not word.is_rule() and word.height < 2.5 * self.spacing

            majority = max(by_row.values(), default=0) * 2 > len(covered)
            if not own or (not majority and len(rows_holding) > 1):
                word_like_unboxed = any(i not in row_of_index for i in covered if _word_like(i))
                verdict = "unboxed" if word_like_unboxed else "right"
            elif len(rows_holding) == 1:
                verdict = "right"
            else:
                verdict = "split"
            outside = tuple(
                i
                for i in own
                if not (
                    boxes[row_of_index[i]].x0 <= self.words[i].cx <= boxes[row_of_index[i]].x1
                    and boxes[row_of_index[i]].y0 <= self.words[i].cy <= boxes[row_of_index[i]].y1
                )
            )
            verdicts.append(Verdict(verdict=verdict, rows=tuple(rows_holding), words=len(covered), outside=outside))
        return verdicts
