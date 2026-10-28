"""The page's rows as the user's drawn line indications define them.

A row of writing is found on the page by the user, not by the detector:
the user draws a line along each row, the line is assigned the word
boxes whose centres fall within its span, and the row is that line's
words bounded by their exact union. `Rows.from_words` groups the page's
words; `rows.adjust` corrects them with the reviewer's drawn lines
boxes and the user's line indications into those rows.

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
from document.rectangle import Rectangle
from document.row import Row
from document.row_adjustments import RowAdjustments
from document.traces import Traces
from document.word import Word
from pipeline.rows.page_visuals import Crop, captioned_sheet, halo_text, review_image, scaled_crop
from pipeline.rows.render import Colour, tint_row

TOUCH_FRACTION = 0.38  # x the writing height: how far a line's stroke claims a word
SPACING_RATIO = 1.6  # x the writing height: where one row ends and the next begins
RULE_ASPECT = 8.0  # x a box's height: this wide for its height is a rule, not writing
BUTT_GAP_MIN = 4.0  # px floor for a butting adjacency — physical, never unit-dependent razor
MAX_LINE_SLOPE_DEG = 6.0  # a drawn line runs along the writing (the jig's A5: ~0–2.4° observed)


class Rows:
    """The rows a page's words make: from the drawn lines where the
    reviewer drew them, from the words' own reading lines everywhere else.

    A drawn line claims each word whose centre its stroke covers
    (enlarged by the touch) and whose drawn height is nearest the word —
    not the first line to cover it, so a word lying under two lines goes
    to the row it most plausibly belongs to (a reviewer's double pass is
    the same row twice, and its words all sit nearest that one line).
    An incomplete set of drawn lines MERGES with the draft rows: a
    reading line no drawn line claimed keeps its row untouched, so the
    reviewer never draws over a row that is already right. Rows come out
    numbered in reading order (topmost band first) and are all one type —
    a corrected row and a proposed row are the same Row.
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
        """The reviewer's drawn lines applied to this page: the rows are
        re-derived from them. A drawn line claims each word whose centre its
        stroke covers (enlarged by the touch) and whose drawn height is
        nearest the word — not the first line to cover it, so a word lying
        under two lines goes to the row it most plausibly belongs to (a
        reviewer's double pass is the same row twice, and its words all sit
        nearest that one line). An incomplete set of lines MERGES with the
        draft: a reading line no drawn line claimed keeps its row untouched,
        so the reviewer never draws over a row that is already right. Rows
        come out numbered in reading order (topmost band first), all one
        type — a corrected row and a proposed row are the same Row."""
        return _Claims(self.words, adjustments, self.page_size).rows()

    def validate(self, traces: Traces) -> list[str]:
        """The row invariants, over these traces — one line per violation.

        This is the acceptance check `boxjig` used to be, folded into the
        library (2026-10-28). The jig compared the detector's BOXES against
        the reviewer's yellow lines, the words and the page's surface; in the
        object model a row's band IS its words' union and each word belongs to
        exactly one row, so those comparisons (A1, A2, A3, A7) cannot fail.
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
        self.spacing = SPACING_RATIO * self.unit
        self.spans = _line_spans(adjustments, page_size)
        self.page_size = page_size
        self._owner_of: list[int | None] | None = None

    def rows(self) -> list[Row]:
        """The rows the drawn lines and the words' own lines make."""
        owner_of = self._claimed()
        corrected = {self.words[i].line for i, owner in enumerate(owner_of) if owner is not None}
        groups: dict[tuple[str, int], list[int]] = {}
        for i, owner in enumerate(owner_of):
            if owner is not None:
                groups.setdefault(("drawn", owner), []).append(i)
                continue
            own_line = self.words[i].line
            if own_line is not None and own_line not in corrected:
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

        Measured once per instance — `rows()` and `violations()` read the same
        map, and measuring it twice could only drift."""
        if self._owner_of is not None:
            return self._owner_of
        owner_of: list[int | None] = [None] * len(self.words)
        for i, word in enumerate(self.words):
            if self._is_rule(word):
                continue
            candidates: list[tuple[float, int]] = [
                (abs(span.mean_y - word.cy), line_index)
                for line_index, span in enumerate(self.spans)
                if span.x_lo <= word.cx <= span.x_hi and span.y_lo - self.unit <= word.cy <= span.y_hi + self.unit
            ]
            if candidates:
                owner_of[i] = min(candidates)[1]
        self._discount_annotations(owner_of)
        for i in range(len(self.words)):
            if owner_of[i] is None:
                owner_of[i] = self._apportion(i, owner_of)
        self._owner_of = owner_of
        return owner_of

    def _discount_annotations(self, owner_of: list[int | None]) -> None:
        """Unclaim the annotations (user 2026-09-19): a word matching either
        pattern is not a line word, and the apportionment decides its fate.

        (1) fully below its line's drawn bottom, hanging directly under a
            word of the line;
        (2) poking above the top of every word of its line, directly over
            one of them (an asterisk floats above its line's x-height; a
            real word's box starts at its own ascenders)."""
        words = self.words
        drawn_bottom = [span.y_hi for span in self.spans]
        for i, word in enumerate(words):
            owner = owner_of[i]
            if owner is None:
                continue
            siblings = [words[j] for j, o in enumerate(owner_of) if o == owner and j != i]
            over = [other for other in siblings if min(word.x1, other.x1) > max(word.x0, other.x0)]
            hangs_under = word.y0 >= drawn_bottom[owner] and any(other.y1 <= word.y0 for other in over)
            pokes_above = bool(over) and word.y0 < min(other.y0 for other in over)
            if hangs_under or pokes_above:
                owner_of[i] = None

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
            if abs(span.slope) > MAX_LINE_SLOPE_DEG:
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
        least `RULE_ASPECT` wider than tall, and no other word box (that is
        itself not rule-flat) may sit within one line-spacing above it,
        overlapping its width."""
        if word.height <= 0 or word.width < RULE_ASPECT * word.height:
            return False
        for other in self.words:
            if other is word or other.width >= RULE_ASPECT * other.height:
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
        return gap is not None and gap <= max(self.unit / 8, BUTT_GAP_MIN)

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
    """One drawn line measured onto the page: its x and y extents, its mean y
    (which line a word sits nearest), and the slope it was drawn at.

    A record rather than a five-tuple: the assignment, the annotation
    discount and the validation each read different fields of the same
    measure, and unpacking five anonymous numbers three times is how they get
    read in the wrong order."""

    x_lo: float
    x_hi: float
    y_lo: float
    y_hi: float
    mean_y: float
    slope: float  # degrees from the line's first to its last point


def _line_spans(adjustments: RowAdjustments, page_size: PageSize) -> list[_Span]:
    """Each drawn line measured onto the page. The lines are normalised (0..1)
    where the reviewer drew them, so the page's size measures them."""
    spans: list[_Span] = []
    for line in adjustments.lines:
        xs = [point[0] * page_size.width for point in line]
        ys = [point[1] * page_size.height for point in line]
        spans.append(
            _Span(
                x_lo=min(xs),
                x_hi=max(xs),
                y_lo=min(ys),
                y_hi=max(ys),
                mean_y=sum(ys) / len(ys),
                slope=math.degrees(math.atan2(ys[-1] - ys[0], xs[-1] - xs[0])),
            )
        )
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
        rects = [Rectangle(word.x0, word.y0, word.x1, word.y1) for word in row.word_boxes]
        colour = style.colour(index)
        # the house renderer's edge takes the RGBA tuple — the one place
        # the record crosses the seam, unpacked by name
        tint_row(draw, rects, list(range(len(rects))), colour)
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
    sheet = captioned_sheet(crop, [f"{len(rows)} rows, tinted by their words' union"])
    path.write_bytes(review_image(sheet.sheet))
    return crop
