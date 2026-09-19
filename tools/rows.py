"""The page's rows as the user's drawn line indications define them.

A row of writing is found on the page by the user, not by the detector:
the user draws a line along each row, the line is assigned the word
boxes whose centres fall within its span, and the row is that line's
words bounded by their exact union. `Rows.build` turns the page's word
boxes and the user's line indications into those rows.

The vocabulary is the page's own: the user's *lines* are the drawn row
indications, a *word box* is one word from the page's detection, a *row*
is one line of writing with its words, and a row's *band* is the exact
union of its words' boxes — a render tints a row's band and nothing
else, so a band wider or taller than its words would paint over
neighbouring rows.

A second line passing over words a first line already owns is the
same row drawn twice, not a new row (a reviewer's double pass): its
words join the first row. Whether a row is an *interjection* (the
page's small marginal writing) rather than a body row is an adjudicated
fact that lives in the page's row data, not something the geometry can
decide — `Rows.build` marks every row `body`, and the page's committed
rows carry the confirmed kinds and numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from tools.boxrows import Rectangle
from tools.boxrows_render import tint_row
from tools.page_visuals import captioned_sheet, halo_text, review_image, scaled_crop

TOUCH_FRACTION = 0.38  # x the writing height: how far a line's stroke claims a word
SPACING_RATIO = 1.6  # x the writing height: where one row ends and the next begins
RULE_ASPECT = 8.0  # x a box's height: this wide for its height is a rule, not writing


@dataclass(frozen=True)
class Box:
    """A rectangle on the page, in page pixels (left, top, right, bottom)."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def centre_x(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def centre_y(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def width(self) -> float:
        return self.x1 - self.x0


@dataclass(frozen=True)
class Row:
    """One row of writing: the words one user line claimed, and their union.

    The id carries its kind, so the file format never loses the type:
    `seg-6` is a body row, `int-41` an interjection row. The number is
    the user-facing line number. The words are their bounding boxes —
    never integer ids, which shift as the word set changes. The band is
    the words' exact union.
    """

    id: str
    kind: str  # "body" | "interjection"
    number: int
    word_boxes: list[Box]
    band: Box


class Rows:
    """The rows the user's line indications make on a page.

    Every row starts from a user line: each word box joins the line whose
    span covers its centre (enlarged by the touch) and whose drawn height
    is nearest the word — not the first line to cover it, so a word lying
    under two lines goes to the row it most plausibly belongs to (a
    reviewer's double pass is `the` same row twice, and its words all sit
    nearest that one line). Rows come out numbered in reading order
    (topmost band first).
    """

    @staticmethod
    def build(
        words: list[Box],
        row_adjustments: list[list[tuple[float, float]]],
        page_size: tuple[int, int],
        baselines: list[float] | None = None,
    ) -> list[Row]:
        """The page's rows from `words` (the detected word boxes),
        `row_adjustments` (the user's drawn row adjustments — the yellow
        lines — as normalised points), and `page_size` (the page's pixel dimensions). When the
        words carry measured baselines, pass them for the apportionment's
        rule B ("roughly the same baseline" means the same drawn line,
        not the neighbour's)."""
        width, height = page_size
        lines = [[(x * width, y * height) for x, y in line] for line in row_adjustments]
        unit = _writing_height(words)
        spacing = SPACING_RATIO * unit
        spans = _line_spans(lines)

        owner_of: list[int | None] = [None] * len(words)
        for i, box in enumerate(words):
            if _is_rule(box, words, spacing):
                continue
            candidates: list[tuple[float, int]] = []
            for line_index, (x_lo, x_hi, y_lo, y_hi, mean_y) in enumerate(spans):
                if x_lo <= box.centre_x <= x_hi and y_lo - unit <= box.centre_y <= y_hi + unit:
                    candidates.append((abs(mean_y - box.centre_y), line_index))
            if candidates:
                owner_of[i] = min(candidates)[1]

        # two discount patterns — a word matching either is an annotation,
        # not a line word: it is unclaimed here and the apportionment
        # decides its fate (user 2026-09-19).
        # (1) fully below its line's drawn bottom, hanging directly under
        #     a word of the line;
        # (2) poking above the top of every word of its line, directly
        #     over one of them (an asterisk floats above its line's
        #     x-height; a real word's box starts at its own ascenders).
        drawn_bottom = [span[3] for span in spans]
        for i, box in enumerate(words):
            owner = owner_of[i]
            if owner is None:
                continue
            siblings = [words[j] for j, o in enumerate(owner_of) if o == owner and j != i]
            over_siblings = [other for other in siblings if min(box.x1, other.x1) > max(box.x0, other.x0)]
            hangs_under = box.y0 >= drawn_bottom[owner] and any(other.y1 <= box.y0 for other in over_siblings)
            pokes_above = bool(over_siblings) and box.y0 < min(other.y0 for other in over_siblings)
            if hangs_under or pokes_above:
                owner_of[i] = None

        for i in range(len(words)):
            if owner_of[i] is not None:
                continue
            claimed = _apportion_target(i, words, owner_of, unit, baselines)
            if claimed is not None:
                owner_of[i] = claimed

        word_sets: dict[int, list[int]] = {}
        for i, owner in enumerate(owner_of):
            if owner is not None:
                word_sets.setdefault(owner, []).append(i)
        numbered: list[Row] = []
        for owner in sorted(word_sets, key=lambda o: min(words[i].centre_y for i in word_sets[o])):
            owned = word_sets[owner]
            sortable = sorted((words[i] for i in owned), key=lambda b: (b.y0, b.x0))
            numbered.append(
                Row(
                    id="",
                    kind="body",
                    number=0,
                    word_boxes=sortable,
                    band=Box(
                        min(box.x0 for box in sortable),
                        min(box.y0 for box in sortable),
                        max(box.x1 for box in sortable),
                        max(box.y1 for box in sortable),
                    ),
                )
            )
        for number, row in enumerate(numbered, start=1):
            numbered[number - 1] = Row(
                id=f"seg-{number}",
                kind=row.kind,
                number=number,
                word_boxes=row.word_boxes,
                band=row.band,
            )
        return numbered


def _apportion_target(
    index: int, words: list[Box], owner_of: list[int | None], unit: float, baselines: list[float] | None = None
) -> int | None:
    """Where an unclaimed word belongs, per the user's ruling (2026-09-18):
    A — the line containing a word directly next to it above or below
    (its box butting this one); B — else the line of the nearest word
    left or right with roughly the same baseline (the same drawn line);
    C — else none, and the word is left without a row."""
    box = words[index]

    def above_below(candidate: int) -> float | None:
        """The gap between this word and the candidate, when the candidate
        is directly above or below it: horizontal overlap and a vertical
        gap no larger than an eighth of the writing height — the boxes
        BUTT UP against each other (a split word's pieces sit ~2px apart;
        a word merely passing overhead floats a real gap away)."""
        other = words[candidate]
        if min(box.x1, other.x1) <= max(box.x0, other.x0):
            return None  # no horizontal overlap: not "directly next to"
        if other.y1 <= box.y0:
            return box.y0 - other.y1
        if other.y0 >= box.y1:
            return other.y0 - box.y1
        return None  # vertically overlapping: it is a row-mate, not a neighbour

    def butts(candidate: int) -> bool:
        gap = above_below(candidate)
        return gap is not None and gap <= unit / 8

    # A: a word directly above or below (its box butting this one),
    # whichever is nearer.
    neighbours = [i for i in range(len(words)) if i != index and butts(i)]
    if neighbours:
        gap_of = lambda candidate: above_below(candidate) or 0.0  # noqa: E731  # only butting neighbours reach here
        nearer = min(neighbours, key=gap_of)
        return owner_of[nearer]

    # B: the nearest word left or right on roughly the same baseline —
    # the measured baseline when given (the same drawn line), else the
    # box centres within a quarter of the writing height.
    def same_line(candidate: int) -> bool:
        if baselines is not None:
            return abs(baselines[candidate] - baselines[index]) <= unit / 4
        return abs(words[candidate].centre_y - box.centre_y) <= unit / 4

    same_band = [i for i in range(len(words)) if i != index and owner_of[i] is not None and same_line(i)]
    if same_band:
        nearest = min(same_band, key=lambda i: abs(words[i].centre_x - box.centre_x))
        return owner_of[nearest]

    return None  # C: no row for this word


def _line_spans(lines: list[list[tuple[float, float]]]) -> list[tuple[float, float, float, float, float]]:
    """Each user line's span and drawn height: its x-extent, y-extent and
    mean y — the measures the assignment uses."""
    spans: list[tuple[float, float, float, float, float]] = []
    for line in lines:
        xs = [point[0] for point in line]
        ys = [point[1] for point in line]
        spans.append((min(xs), max(xs), min(ys), max(ys), sum(ys) / len(ys)))
    return spans


def _writing_height(words: list[Box]) -> float:
    """The page's writing height: the median word box height."""
    heights = sorted(box.height for box in words)
    return heights[len(heights) // 2]


def _is_rule(box: Box, words: list[Box], spacing: float) -> bool:
    """Whether a word box is long-flat ink with no writing directly above it.

    A rule is not part of any row; an underline — which HAS writing
    directly above (the letters it underscores) — is. The box must be at
    least `RULE_ASPECT` wider than tall, and no other word box (that is
    itself not rule-flat) may sit within one line-spacing above it,
    overlapping its width.
    """
    if box.height <= 0 or box.width < RULE_ASPECT * box.height:
        return False
    for other in words:
        if other is box or other.width >= RULE_ASPECT * other.height:
            continue
        if other.x1 > box.x0 and other.x0 < box.x1 and -spacing <= box.y0 - other.y1 <= spacing:
            return False  # writing sits directly above — an underline, part of the row
    return True


@dataclass(frozen=True)
class _MapStyle:
    """The map's look: the tint's alpha and the chip's shape, the same
    numbers the house row renderer uses."""

    tint: int = 55
    chip_radius: int = 6
    chip_font: int = 28

    def colour(self, index: int) -> tuple[int, int, int, int]:
        palette = [
            (200, 40, 40),
            (40, 160, 40),
            (40, 40, 200),
            (160, 40, 180),
            (40, 160, 160),
            (180, 140, 20),
            (90, 90, 200),
            (200, 100, 20),
        ]
        base = palette[index % len(palette)]
        return (*base, self.tint)


def render_map(
    page: Image.Image,
    rows: list[Row],
    path: Path,
    window: Box,
    scale: float = 1.0,
    word_numbers: dict[tuple[float, float, float, float], int] | None = None,
    row_adjustments: list[list[tuple[float, float]]] | None = None,
    page_size: tuple[int, int] | None = None,
) -> Image.Image:
    """The rows as tinted bands over the page's ink (the house `tint_row`:
    each row's words' boxes tinted — the ink stays the loudest thing), with
    one white chip per row carrying its number. `window` is the page region
    to show, `scale` the upscale. `word_numbers` overlays the reading-order
    numbers of named word boxes (the words a question concerns). The sheet
    is written to `path` and the crop returned."""
    style = _MapStyle()
    canvas = page.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for index, row in enumerate(rows):
        rects = [Rectangle(box.x0, box.y0, box.x1, box.y1) for box in row.word_boxes]
        tint_row(draw, rects, list(range(len(rects))), style.colour(index))
    rendered = Image.alpha_composite(canvas, overlay).convert("RGB")
    crop = scaled_crop(rendered, window.x0, window.y0, window.x1, window.y1, scale)
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
