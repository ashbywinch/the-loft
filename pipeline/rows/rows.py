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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from document.rectangle import Rectangle
from document.row import Row
from document.word import Word
from pipeline.rows.page_visuals import Crop, captioned_sheet, halo_text, review_image, scaled_crop
from pipeline.rows.render import Colour, tint_row

TOUCH_FRACTION = 0.38  # x the writing height: how far a line's stroke claims a word
SPACING_RATIO = 1.6  # x the writing height: where one row ends and the next begins
RULE_ASPECT = 8.0  # x a box's height: this wide for its height is a rule, not writing
BUTT_GAP_MIN = 4.0  # px floor for a butting adjacency — physical, never unit-dependent razor


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

    def __init__(self, words: list[Word], page_size: tuple[int, int]) -> None:
        self.words = list(words)
        self.page_size = page_size

    @classmethod
    def from_words(cls, words: list[Word], page_size: tuple[int, int]) -> Rows:
        """The page's grouping before any line is drawn: `words` (the
        detected words, each carrying its reading line) and the page's pixel
        dimensions. The words' own reading lines are the draft rows."""
        return cls(words, page_size)

    def rows(self) -> list[Row]:
        """The draft rows: the words' own reading lines, nothing drawn."""
        return self.adjust([])

    def adjust(self, row_adjustments: list[list[tuple[float, float]]]) -> list[Row]:
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
        return _Claims(self.words, row_adjustments, self.page_size).rows()

    @staticmethod
    def to_wire(rows: Sequence[Row]) -> dict[str, Any]:
        """The rows as the wire contract (`document.schemas.Rows`: id, kind,
        number, word_boxes, band, text, stage — plain x0..y1 records). This
        is the shape the review's correction persists and the app reads; the
        schema's strict loader is the check."""
        return {
            "rows": [
                {
                    "id": row.id,
                    "kind": row.kind,
                    "number": row.number,
                    "word_boxes": [_box_wire(box) for box in row.word_boxes],
                    "band": _box_wire(row.band),
                    "text": row.text,
                    "stage": row.stage,
                }
                for row in rows
            ]
        }

    @staticmethod
    def from_wire(data: Mapping[str, Any]) -> list[Row]:
        """The wire contract's rows as Row records (the inverse of
        ``to_wire``) — the app's persisted correction read back."""
        return [
            Row(
                id=str(record["id"]),
                kind=str(record["kind"]),
                number=int(record["number"]),
                word_boxes=[_word_from_wire(box) for box in record["word_boxes"]],
                band=_rect_from_wire(record["band"]),
                text=str(record.get("text", "")),
                stage=str(record.get("stage", "")),
            )
            for record in data["rows"]
        ]


class _Claims:
    """The page's words and the drawn lines claiming them.

    The measures, the two discount patterns and the apportionment all read
    the same words, so they live here once — `rows.adjust` is the
    library's face, this is the measurement behind it."""

    def __init__(
        self,
        words: list[Word],
        row_adjustments: list[list[tuple[float, float]]],
        page_size: tuple[int, int],
    ) -> None:
        width, height = page_size
        self.words = words
        # a page the reader found no writing on has no rows — there is no
        # writing height to measure, and every caller downstream (the reading,
        # the review) is about rows that exist
        self.unit = self._writing_height() if words else 0.0
        self.spacing = SPACING_RATIO * self.unit
        self.spans = _line_spans([[(x * width, y * height) for x, y in line] for line in row_adjustments])

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
        """Every word's drawn line, or None where no line claimed it."""
        owner_of: list[int | None] = [None] * len(self.words)
        for i, word in enumerate(self.words):
            if self._is_rule(word):
                continue
            candidates: list[tuple[float, int]] = []
            for line_index, (x_lo, x_hi, y_lo, y_hi, mean_y) in enumerate(self.spans):
                if x_lo <= word.cx <= x_hi and y_lo - self.unit <= word.cy <= y_hi + self.unit:
                    candidates.append((abs(mean_y - word.cy), line_index))
            if candidates:
                owner_of[i] = min(candidates)[1]
        self._discount_annotations(owner_of)
        for i in range(len(self.words)):
            if owner_of[i] is None:
                owner_of[i] = self._apportion(i, owner_of)
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
        drawn_bottom = [span[3] for span in self.spans]
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


def _box_wire(box: Word | Rectangle) -> dict[str, float]:
    """One box as the wire record (the four fields, and only those)."""
    return {"x0": box.x0, "y0": box.y0, "x1": box.x1, "y1": box.y1}


def _rect_from_wire(record: Mapping[str, Any]) -> Rectangle:
    return Rectangle(float(record["x0"]), float(record["y0"]), float(record["x1"]), float(record["y1"]))


def _word_from_wire(record: Mapping[str, Any]) -> Word:
    """A wire word box as a Word — the wire carries the box only."""
    return Word(float(record["x0"]), float(record["y0"]), float(record["x1"]), float(record["y1"]))


def _line_spans(lines: list[list[tuple[float, float]]]) -> list[tuple[float, float, float, float, float]]:
    """Each user line's span and drawn height: its x-extent, y-extent and
    mean y — the measures the assignment uses."""
    spans: list[tuple[float, float, float, float, float]] = []
    for line in lines:
        xs = [point[0] for point in line]
        ys = [point[1] for point in line]
        spans.append((min(xs), max(xs), min(ys), max(ys), sum(ys) / len(ys)))
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
    row_adjustments: list[list[tuple[float, float]]] | None = None
    page_size: tuple[int, int] | None = None


@dataclass(frozen=True)
class _MapStyle:
    """The map's look: the tint's alpha and the chip's shape, the same
    numbers the house row renderer uses."""

    tint: int = 55
    chip_radius: int = 6
    chip_font: int = 28

    def colour(self, index: int) -> Colour:
        palette = [
            Colour(200, 40, 40, self.tint),
            Colour(40, 160, 40, self.tint),
            Colour(40, 40, 200, self.tint),
            Colour(160, 40, 180, self.tint),
            Colour(40, 160, 160, self.tint),
            Colour(180, 140, 20, self.tint),
            Colour(90, 90, 200, self.tint),
            Colour(200, 100, 20, self.tint),
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
            halo_text(label_layer, (left + 2, top + 2), str(number), size=40)
    if row_adjustments and page_size:
        line_colour = (235, 185, 0)
        for line in row_adjustments:
            points = [
                (int((px * page_size[0] - window.x0) * scale), int((py * page_size[1] - window.y0) * scale))
                for px, py in line
            ]
            label_layer.line(points, fill=line_colour, width=4)
    sheet, _handle, _bar = captioned_sheet(crop, [f"{len(rows)} rows, tinted by their words' union"])
    path.write_bytes(review_image(sheet))
    return crop
