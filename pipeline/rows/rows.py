"""The page's rows as the user's drawn line indications define them.

A row of writing is found on the page by the user, not by the detector:
the user draws a line along each row, and the row is the words that line
passes over, bounded by their exact union. `Rows.from_words` groups the
page's words; `rows.adjust` corrects those groups with the reviewer's
drawn lines.

The correction is an EDIT of the draft, never a rebuild — the rule that
lets a reviewer fix a mostly-right page by drawing a line or two
(`docs/PLAN/row-correction-rule.md`):

- a stroke that runs across a reading line and covers at least half of the
  words it reaches REPLACES that line's row (a correct row traced over
  comes out unchanged);
- otherwise it claims only the words it runs along — the box within the
  page's touch AND the centre within half a writing height — so a line
  drawn along one row cannot take a neighbour's writing;
- every word no stroke claimed keeps its reading line's row, whatever
  else was drawn, and a line that loses some of its words keeps the rest.

The vocabulary is the page's own: the user's *lines* are the drawn row
indications, a *word box* is one word from the page's detection, a *row*
is one line of writing with its words, and a row's *band* is the exact
union of its words' boxes — a render tints a row's band and nothing
else, so a band wider or taller than its words would paint over
neighbouring rows.

A second line passing over words a first line already owns is the
same row drawn twice, not a new row (a reviewer's double pass): its
words join the first row. Every row this builder makes is `body`: whether
a row is an *interjection* or marginalia is decided at the transcription
phase (the VLM reads the page and rules on its kinds and injection
points), never by the geometry that found the rows.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from document.page_size import PageSize
from document.point import Point
from document.rectangle import Rectangle, point_segment_distance
from document.row import Row
from document.row_adjustments import RowAdjustments
from document.traces import Traces
from document.word import Word
from pipeline.rows.page_visuals import CaptionSheet, Crop, PagePainter, halo_text, scaled_crop
from pipeline.rows.render import Colour, tint_row


class Rows:
    """The rows a page's words make: from the drawn lines where the
    reviewer drew them, from the words' own reading lines everywhere else.

    A drawn line claims each word its stroke passes over (the box within
    the page's touch of the drawn polyline) — and ONLY the words it passes
    over: a line drawn along one row never reaches a neighbour's writing,
    and no word changes row because a line was drawn near it. The nearest
    line wins where two cross one word, so a reviewer's double pass is the
    same row twice.

    A correction is an EDIT of the draft, never a rebuild: a word the
    stroke passed over leaves its reading line's row and joins the drawn
    row; every other word keeps the row it already had. A reading line
    that loses some of its words keeps the rest as its row (a partial
    correction of a single row leaves that row's other words in place);
    a line that loses all of them has no row left. The one exception is a
    reading line the stroke replaced but for a single word the stroke
    missed: that word is apportioned to its neighbours (`_apportion`), so
    a fully traced page has no one-word row. Rows come out numbered in
    reading order (topmost band first), all one type — a corrected row and
    a proposed row are the same Row.
    """

    def __init__(self, words: list[Word], page_size: PageSize) -> None:
        self.words = list(words)
        self.page_size = page_size

    @classmethod
    def from_words(cls, words: list[Word], page_size: PageSize) -> Rows:
        """The page's grouping before any line is drawn: `words` (the
        detected words, each carrying its reading line) and the page's pixel
        dimensions. The words' own reading lines are the draft rows."""
        return cls(words, page_size)

    def rows(self) -> list[Row]:
        """The draft rows: the words' own reading lines, nothing drawn."""
        return self.adjust(RowAdjustments([]))

    @classmethod
    def from_traces(cls, traces: Traces) -> Rows:
        """The page the traces describe — the correction's inputs as one value."""
        return cls(list(traces.words), traces.page_size)

    def adjust(self, adjustments: RowAdjustments) -> list[Row]:
        """The reviewer's drawn lines applied to this page: an edit of the
        draft rows, not a rebuild.

        Each drawn line claims the words its stroke passes over (within the
        page's touch of the polyline; the nearest line wins where two cross
        one word). A claimed word leaves its reading line and joins the
        drawn row. Every unclaimed word keeps its reading line's row — so
        drawing one line changes that one row and nothing else, and a
        reading line the line partly covers keeps its other words as a row
        of their own. A word that is its line's only leftover from a stroke
        is apportioned to its neighbours (`_apportion`), the fully traced
        page's case; so are the annotations the stroke discounted and the
        words that carry no reading line. Rows come out numbered in reading
        order (topmost band first), all one type — a corrected row and a
        proposed row are the same Row."""
        return _Claims(self.words, adjustments, self.page_size).rows()

    def validate(self, traces: Traces) -> list[str]:
        """The row invariants, over these traces — one line per violation.

        The acceptance check for the boxes lives here rather than in a script
        reading a saved trace. A row's band IS its words' union and each word
        belongs to exactly one row, so the box-against-line comparisons (A1,
        A2, A3, A7) cannot fail.
        What can still go wrong is the drawing and a word box's measurement:

        - a drawn line that claims no word (it missed the writing);
        - a drawn line running off the writing's slope (A5);
        - a row whose band leaves the page (A4) — a mis-measured word box.

        A6's leftover count stays out: the words no row shows are exactly the
        annotations the correction deliberately discounts (an asterisk above
        its line) and the rules it drops, and without the jig's separate
        surface measurement the two cannot be told apart from ink the trace
        missed — a count this check would have to guess at."""
        return _Claims(list(traces.words), traces.adjustments, traces.page_size).violations()

    @staticmethod
    def to_dict(rows: Sequence[Row]) -> dict[str, Any]:
        """The rows as the rows.json artefact — each row's own record (`Row.to_dict`:
        id, kind, number, word_boxes, band, text, stage). This is the shape the
        review's correction persists and the app reads."""
        return {"rows": [row.to_dict() for row in rows]}

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> list[Row]:
        """The artefact's rows as Row records (the inverse of ``to_dict``) — the
        app's persisted correction read back, each record read by `Row.from_dict`."""
        records = data.get("rows")
        if not isinstance(records, list):
            raise ValueError("not a Rows (no top-level 'rows' list)")
        return [Row.from_dict(record) for record in records]


class _Claims:
    """The page's words and the drawn lines claiming them.

    The measures, the two discount patterns and the apportionment all read
    the same words, so they live here once — `rows.adjust` is the
    library's face, this is the measurement behind it."""

    TOUCH_FRACTION = 0.38  # x the writing height: how far a line's stroke claims a word
    SPACING_RATIO = 1.6  # x the writing height: where one row ends and the next begins
    BUTT_GAP_MIN = 4.0  # px floor for a butting adjacency — physical, never unit-dependent razor
    MAX_LINE_SLOPE_DEG = 6.0  # a drawn line runs along the writing (the jig's A5: ~0–2.4° observed)

    def __init__(
        self,
        words: list[Word],
        adjustments: RowAdjustments,
        page_size: PageSize,
    ) -> None:
        self.words = words
        # a page the reader found no writing on has no rows — there is no
        # writing height to measure, and every caller downstream (the reading,
        # the review) is about rows that exist
        self.unit = self._writing_height() if words else 0.0
        self.spacing = _Claims.SPACING_RATIO * self.unit
        self.touch = _Claims.TOUCH_FRACTION * self.unit
        self.spans = _line_spans(adjustments, page_size)
        self.page_size = page_size
        self.discounted: set[int] = set()
        self._owner_of: list[int | None] | None = None

    def rows(self) -> list[Row]:
        """The rows the drawn lines and the words' own lines make.

        The draft is the base: an unclaimed word keeps its reading line's
        row. A claimed word joins its drawn row, and its reading line's row
        is whatever words of that line remain. Neither group is suppressed
        by the other — which is why drawing one line changes one row."""
        owner_of = self._claimed()
        groups: dict[tuple[str, int], list[int]] = {}
        for i, owner in enumerate(owner_of):
            if owner is not None:
                groups.setdefault(("drawn", owner), []).append(i)
                continue
            own_line = self.words[i].line
            if own_line is not None and i not in self.discounted:
                groups.setdefault(("draft", own_line), []).append(i)

        rows: list[Row] = []
        for key in sorted(groups, key=lambda k: min(self.words[i].cy for i in groups[k])):
            sortable = sorted((self.words[i] for i in groups[key]), key=lambda w: (w.y0, w.x0))
            rows.append(
                Row(
                    id=f"seg-{len(rows) + 1}",
                    kind="body",
                    number=len(rows) + 1,
                    word_boxes=sortable,
                    band=Rectangle(
                        min(word.x0 for word in sortable),
                        min(word.y0 for word in sortable),
                        max(word.x1 for word in sortable),
                        max(word.y1 for word in sortable),
                    ),
                )
            )
        return rows

    def _claimed(self) -> list[int | None]:
        """Every word's drawn line, or None where no line claimed it.

        A stroke's claim has two parts, both measured from the stroke to the
        page's own boxes:

        - **It replaces a row it covers.** A stroke that runs across a
          reading line (at least half its width) and covers at least half of
          the line's words inside that reach IS that line's row: every word
          of the line is claimed. A stroke traced along a row therefore
          leaves that row exactly as it was, and no word of it is stranded
          as a one-word remainder.
        - **Otherwise it claims the words it runs along.** Of the words its
          box touches (`Rectangle.distance_to_segment` ≤ the page's touch,
          the same 0.38 of the writing height the detector uses), it claims
          only those whose CENTRE is within half a writing height of the
          stroke — a word lying along the line, not one whose tall box merely
          clips it from the row above or below (the user's report, 2026-11-02:
          a line drawn on one row joined words from its neighbour).

        A stroke that replaces a row never claims another row's words; a
        stroke that replaces nothing is a partial edit and claims what it
        runs along. The nearest stroke wins where two claim one word.

        The marks that float clear of a stroke's row (`_discount_annotations`)
        are unclaimed whatever the two rules said, and get no row.

        Measured once per instance — `rows()` and `violations()` read the same
        map, and measuring it twice could only drift."""
        if self._owner_of is not None:
            return self._owner_of
        owner_of: list[int | None] = [None] * len(self.words)
        covered = [self._covered(span) for span in self.spans]
        under = [self._under(span) for span in self.spans]
        widths = self._line_widths()
        replacing = [
            self._replaced(span, self._counts(cov), self._counts(reach), widths)
            for span, cov, reach in zip(self.spans, covered, under, strict=True)
        ]
        for i, word in enumerate(self.words):
            if self._is_rule(word):
                continue
            candidates: list[tuple[float, int]] = []
            for index, span in enumerate(self.spans):
                if (
                    word.line is not None
                    and word.line in replacing[index]
                    or i in covered[index]
                    and (word.line is None or span.distance_to_point(word.cx, word.cy) <= self.unit / 2)
                ):
                    candidates.append((span.distance_to(word.rect), index))
            if candidates:
                owner_of[i] = min(candidates)[1]
        self._discount_annotations(owner_of)
        self._apportion_unrowed(owner_of)
        self._owner_of = owner_of
        return owner_of

    def _covered(self, span: _Span) -> set[int]:
        """The words whose box the stroke passes within the page's touch of."""
        return {
            i
            for i, word in enumerate(self.words)
            if not self._is_rule(word) and span.distance_to(word.rect) <= self.touch
        }

    def _under(self, span: _Span) -> set[int]:
        """The words whose centre lies within the stroke's horizontal reach —
        the words a stroke drawn over this stretch of the row could be the
        row of."""
        return {
            i
            for i, word in enumerate(self.words)
            if word.line is not None and span.x_lo - self.touch <= word.cx <= span.x_hi + self.touch
        }

    def _counts(self, words: set[int]) -> dict[int, int]:
        """How many of each reading line's words are in the given set."""
        counts: dict[int, int] = {}
        for i in words:
            line = self.words[i].line
            if line is not None:
                counts[line] = counts.get(line, 0) + 1
        return counts

    def _line_widths(self) -> dict[int, float]:
        """How wide each reading line's writing runs, x0 to x1."""
        extents: dict[int, tuple[float, float]] = {}
        for word in self.words:
            if word.line is None:
                continue
            low, high = extents.get(word.line, (word.x0, word.x1))
            extents[word.line] = (min(low, word.x0), max(high, word.x1))
        return {line: high - low for line, (low, high) in extents.items()}

    def _replaced(
        self, span: _Span, counts: dict[int, int], reach: dict[int, int], widths: dict[int, float]
    ) -> set[int]:
        """The reading lines a stroke replaces.

        Two measures must agree. The stroke must RUN ACROSS the row — its x
        extent at least half the line's own width — so a short stroke over
        part of a row is a partial edit, not a replacement. And it must cover
        at least half of the words it reaches (the line's words inside its x
        extent), so a stroke along a row that stops short of its last words
        still replaces it, while one that merely grazes a neighbour's word
        replaces nothing.

        A stroke that replaces a row never takes another row's words: that is
        what keeps one drawn line from moving its neighbour's writing."""
        across = span.x_hi - span.x_lo
        return {
            line
            for line, count in counts.items()
            # a line the stroke's reach never named (its words' centres lie
            # outside it) is measured by the words the stroke did cover: the
            # coverage is the evidence, and the denominator is not a missing key
            if across * 2 >= widths[line] and count * 2 >= reach.get(line, count)
        }

    def _apportion_unrowed(self, owner_of: list[int | None]) -> None:
        """The unclaimed words that no reading line's row can hold.

        A word with no reading line is apportioned by its neighbours
        (`_apportion`). A discounted mark joins the drawn row whose writing
        it lies in — a mark that sits within a row's words is that row's
        writing — and keeps no row when it only grazes one (it floats in the
        leading). Every other unclaimed word keeps its reading line's row: the
        untouched remainder of a row a stroke only partly covered (see
        `rows`)."""
        rows: dict[int, list[Word]] = {}
        for i, owner in enumerate(owner_of):
            if owner is not None:
                rows.setdefault(owner, []).append(self.words[i])
        for i, word in enumerate(self.words):
            if owner_of[i] is not None:
                continue
            if i in self.discounted:
                owner_of[i] = self._host_row(word, rows)
            elif word.line is None:
                owner_of[i] = self._apportion(i, owner_of)

    @staticmethod
    def _host_row(word: Word, rows: dict[int, list[Word]]) -> int | None:
        """The drawn row a mark lies IN: at least half the mark's height
        overlaps the row's own words in x. Anything less is a mark in the
        leading, which is not writing and has no row."""
        if not word.height:
            return None
        best = 0.0
        host: int | None = None
        for owner, words in rows.items():
            overlap = max(
                (
                    min(word.y1, other.y1) - max(word.y0, other.y0)
                    for other in words
                    if min(word.x1, other.x1) > max(word.x0, other.x0)
                ),
                default=0.0,
            )
            if overlap / word.height > best:
                best, host = overlap / word.height, owner
        return host if best >= 0.5 else None

    def _discount_annotations(self, owner_of: list[int | None]) -> None:
        """Unclaim the marks that float clear of the drawn line (user
        2026-09-19).

        A word is a mark, not writing, when all three hold: its box lies
        entirely above or entirely below the stroke that draws its row; it
        sits over (or under) a word of that row; and it is no taller than the
        page's writing. The stroke runs along the writing, so a small box
        clear of it is in the leading — an asterisk above its line, a mark in
        the space below. Taller boxes are writing whatever their position: a
        tall letter that rises into the leading, or a word inserted between
        the lines, is a word.

        A word need not have been claimed to be a mark: the asterisk the
        reader attached to a line is often too far from the stroke to claim,
        and it is still not a row of its own. So every word the stroke passes
        near is tested, against the stroke nearest it."""
        words = self.words
        for i, word in enumerate(words):
            if self._is_rule(word) or word.height > self.unit:
                continue
            near = [(span.distance_to(word.rect), index) for index, span in enumerate(self.spans)]
            near = [candidate for candidate in near if candidate[0] <= self.touch]
            if not near:
                continue
            stroke = min(near)[1]
            span = self.spans[stroke]
            over = any(
                words[j].line == word.line and min(word.x1, words[j].x1) > max(word.x0, words[j].x0)
                for j, o in enumerate(owner_of)
                if o == stroke and j != i
            )
            if over and (word.y1 <= span.y_lo or word.y0 >= span.y_hi):
                owner_of[i] = None
                self.discounted.add(i)

    def violations(self) -> list[str]:
        """The row invariants this page's traces break — one line each.

        The checks `Rows.validate` documents: a drawn line that caught no
        writing (and one whose merged reading lines make it say so), a line
        off the writing's slope, and a row that leaves the page."""
        owner_of = self._claimed()
        problems: list[str] = []
        claimed: dict[int, list[int]] = {}
        for index, owner in enumerate(owner_of):
            if owner is not None:
                claimed.setdefault(owner, []).append(index)
        for line_index, span in enumerate(self.spans):
            words = claimed.get(line_index, [])
            if not words:
                problems.append(f"line {line_index + 1} claims no word")
                continue
            reading_lines: set[int] = set()
            for index in words:
                line = self.words[index].line
                if line is not None:
                    reading_lines.add(line)
            if len(reading_lines) > 1:
                problems.append(f"line {line_index + 1} merges reading lines {sorted(reading_lines)} into one row")
            if abs(span.slope) > _Claims.MAX_LINE_SLOPE_DEG:
                problems.append(f"line {line_index + 1} runs at {span.slope:.1f}°")
        problems.extend(self._off_page())
        return problems

    def _off_page(self) -> list[str]:
        """Rows whose band leaves the page — a word box the reader measured
        off the image (A4: boxes stay on the letter surface)."""
        width, height = self.page_size.width, self.page_size.height
        return [
            f"row {row.number} leaves the page: {row.band.x0:.0f},{row.band.y0:.0f}–{row.band.x1:.0f},{row.band.y1:.0f}"
            for row in self.rows()
            if row.band.x0 < 0 or row.band.y0 < 0 or row.band.x1 > width or row.band.y1 > height
        ]

    def _writing_height(self) -> float:
        """The page's writing height: the median word box height."""
        heights = sorted(word.height for word in self.words)
        return heights[len(heights) // 2]

    def _is_rule(self, word: Word) -> bool:
        """Whether a word box is long-flat ink with no writing directly above it.

        A rule is not part of any row; an underline — which HAS writing
        directly above (the letters it underscores) — is. The box must be at
        least `Word.RULE_ASPECT` wider than tall, and no other word box (that is
        itself not rule-flat) may sit within one line-spacing above it,
        overlapping its width."""
        if word.height <= 0 or word.width < Word.RULE_ASPECT * word.height:
            return False
        for other in self.words:
            if other is word or other.width >= Word.RULE_ASPECT * other.height:
                continue
            if other.x1 > word.x0 and other.x0 < word.x1 and -self.spacing <= word.y0 - other.y1 <= self.spacing:
                return False  # writing sits directly above — an underline, part of the row
        return True

    def _apportion(self, index: int, owner_of: list[int | None]) -> int | None:
        """Where an unclaimed word belongs, per the user's ruling (2026-09-18):
        A — the line containing a word directly next to it above or below
        (its box butting this one); B — else the line of the nearest word
        left or right with roughly the same baseline (the same drawn line);
        C — else none, and the word is left without a row."""
        word = self.words[index]
        neighbours = [i for i in range(len(self.words)) if i != index and self._butts(index, i)]
        if neighbours:
            nearer = min(neighbours, key=lambda candidate: self._gap(index, candidate) or 0.0)
            return owner_of[nearer]
        same_band = [
            i for i in range(len(self.words)) if i != index and owner_of[i] is not None and self._same_line(index, i)
        ]
        if same_band:
            nearest = min(same_band, key=lambda i: abs(self.words[i].cx - word.cx))
            return owner_of[nearest]
        return None  # C: no row for this word

    def _gap(self, index: int, candidate: int) -> float | None:
        """The gap between two words when one is directly above or below the
        other: horizontal overlap and a vertical gap — the boxes BUTT UP
        against each other (a split word's pieces sit ~2px apart; a word
        merely passing overhead floats a real gap away)."""
        word = self.words[index]
        other = self.words[candidate]
        if min(word.x1, other.x1) <= max(word.x0, other.x0):
            return None  # no horizontal overlap: not "directly next to"
        if other.y1 <= word.y0:
            return word.y0 - other.y1
        if other.y0 >= word.y1:
            return other.y0 - word.y1
        return None  # vertically overlapping: it is a row-mate, not a neighbour

    def _butts(self, index: int, candidate: int) -> bool:
        gap = self._gap(index, candidate)
        # a floor: on a small-font page unit/8 can be only a couple of
        # pixels, too tight for a split piece's real gap — butting is a
        # physical adjacency, never smaller than a few px (PR review,
        # 2026-09-19).
        return gap is not None and gap <= max(self.unit / 8, _Claims.BUTT_GAP_MIN)

    def _same_line(self, index: int, candidate: int) -> bool:
        """Roughly the same baseline — the measured baseline when the words
        carry one (the same drawn line), else the box centres within a
        quarter of the writing height."""
        word = self.words[index]
        other = self.words[candidate]
        if word.baseline is not None and other.baseline is not None:
            return abs(other.baseline - word.baseline) <= self.unit / 4
        return abs(other.cy - word.cy) <= self.unit / 4


@dataclass(frozen=True)
class _Span:
    """One drawn line measured onto the page: the polyline itself, in page
    pixels, and the slope it was drawn at.

    A record rather than a tuple: the extent is the polyline's own (derived,
    never a second copy), the claim measures the distance from a word's box
    to that polyline, the annotation discount reads the drawn bottom, and the
    validation reads the slope."""

    points: tuple[tuple[float, float], ...]
    slope: float  # degrees from the line's first to its last point

    @property
    def x_lo(self) -> float:
        return min(x for x, _ in self.points)

    @property
    def x_hi(self) -> float:
        return max(x for x, _ in self.points)

    @property
    def y_lo(self) -> float:
        return min(y for _, y in self.points)

    @property
    def y_hi(self) -> float:
        return max(y for _, y in self.points)

    def distance_to(self, box: Rectangle) -> float:
        """How far the drawn line passes from a word's box (0 where it
        crosses). A one-point line - a tap, never a drawn row - measures from
        the point itself."""
        segments = list(zip(self.points, self.points[1:], strict=False))
        if not segments:
            return box.distance_to_point(*self.points[0])
        return min(box.distance_to_segment(start, end) for start, end in segments)

    def distance_to_point(self, x: float, y: float) -> float:
        """How far a point (a word's centre) lies from the drawn line."""
        segments = list(zip(self.points, self.points[1:], strict=False))
        if not segments:
            return math.hypot(x - self.points[0][0], y - self.points[0][1])
        return min(point_segment_distance(x, y, start, end) for start, end in segments)


def _line_spans(adjustments: RowAdjustments, page_size: PageSize) -> list[_Span]:
    """Each drawn line measured onto the page. The lines are normalised (0..1)
    where the reviewer drew them, so the page's size measures them."""
    spans: list[_Span] = []
    for line in adjustments.lines:
        points = tuple((point[0] * page_size.width, point[1] * page_size.height) for point in line)
        if not points:
            continue
        first, last = points[0], points[-1]
        spans.append(_Span(points=points, slope=math.degrees(math.atan2(last[1] - first[1], last[0] - first[0]))))
    return spans


@dataclass(frozen=True)
class MapView:
    """The view over the page a map renders: the region in the window,
    its upscale, and the optional overlays (the reading-order numbers of
    named word boxes, the reviewer's drawn lines, and the page's pixel
    size those lines are measured in)."""

    window: Rectangle
    scale: float = 1.0
    word_numbers: dict[tuple[float, float, float, float], int] | None = None
    row_adjustments: RowAdjustments | None = None
    page_size: PageSize | None = None


@dataclass(frozen=True)
class _MapStyle:
    """The map's look: the tint's alpha and the chip's shape, the same
    numbers the house row renderer uses."""

    tint: int = 55
    chip_radius: int = 6
    chip_font: int = 28

    def colour(self, index: int) -> Colour:
        palette = [
            Colour(red=200, green=40, blue=40, alpha=self.tint),
            Colour(red=40, green=160, blue=40, alpha=self.tint),
            Colour(red=40, green=40, blue=200, alpha=self.tint),
            Colour(red=160, green=40, blue=180, alpha=self.tint),
            Colour(red=40, green=160, blue=160, alpha=self.tint),
            Colour(red=180, green=140, blue=20, alpha=self.tint),
            Colour(red=90, green=90, blue=200, alpha=self.tint),
            Colour(red=200, green=100, blue=20, alpha=self.tint),
        ]
        return palette[index % len(palette)]


def render_map(page: Image.Image, rows: list[Row], path: Path, view: MapView) -> Image.Image:
    """The rows as tinted bands over the page's ink (the house `tint_row`:
    each row's words' boxes tinted — the ink stays the loudest thing), with
    one white chip per row carrying its number. `view.window` is the page
    region to show, `view.scale` the upscale. `word_numbers` overlays the
    reading-order numbers of named word boxes (the words a question
    concerns). The sheet is written to `path` and the crop returned."""
    window = view.window
    scale = view.scale
    word_numbers = view.word_numbers
    row_adjustments = view.row_adjustments
    page_size = view.page_size
    style = _MapStyle()
    canvas = page.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for index, row in enumerate(rows):
        # the house renderer's edge takes the RGBA tuple — the one place
        # the record crosses the seam, unpacked by name
        tint_row(draw, row, style.colour(index))
    rendered = Image.alpha_composite(canvas, overlay).convert("RGB")
    crop = scaled_crop(rendered, Crop(window.x0, window.y0, window.x1, window.y1, scale))
    label_layer = ImageDraw.Draw(crop)
    font = ImageFont.load_default(size=style.chip_font)
    for row in rows:
        cx = row.band.x0 - window.x0
        cy = (row.band.y0 + row.band.y1) / 2 - window.y0
        text = str(row.number)
        tb = label_layer.textbbox((0, 0), text, font=font)
        label_layer.rounded_rectangle(
            (cx * scale - 30 - (tb[2] - tb[0]), cy * scale - 14, cx * scale - 22, cy * scale + 14),
            radius=style.chip_radius,
            fill=(255, 255, 255),
            outline=(60, 60, 60),
            width=2,
        )
        label_layer.text((cx * scale - 26 - (tb[2] - tb[0]), cy * scale - 12), text, fill=(20, 20, 20), font=font)
    if word_numbers:
        for (bx0, by0, bx1, by1), number in word_numbers.items():
            left = (bx0 - window.x0) * scale
            top = (by0 - window.y0) * scale
            label_layer.rectangle(
                [left, top, (bx1 - window.x0) * scale, (by1 - window.y0) * scale],
                outline=(20, 20, 20),
                width=3,
            )
            halo_text(label_layer, Point(x=left + 2, y=top + 2), str(number), size=40)
    if row_adjustments and page_size:
        line_colour = (235, 185, 0)
        for line in row_adjustments.lines:
            points = [
                (int((px * page_size.width - window.x0) * scale), int((py * page_size.height - window.y0) * scale))
                for px, py in line
            ]
            label_layer.line(points, fill=line_colour, width=4)
    sheet = CaptionSheet.captioned_sheet(crop, [f"{len(rows)} rows, tinted by their words' union"])
    path.write_bytes(PagePainter.review_image(sheet.sheet))
    return crop
