"""Drawing pages for the box-detection experiments.

Everything is composed left to right: measure the words' geometry, resolve
what is drawn (measurement or the reviewer's override), draw it - a
PagePainter over the page and its strokes - in PAGE coordinates only, then
crop and scale for a strip. One coordinate system in the drawing - the
page's - so a strip can never offset its lines; the audit runs in the same
space with an explicit origin. Colours are the Colour record; page windows
are Rectangles, a crop window plus its read scale a Crop.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import groupby
from typing import NamedTuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from document.colour import Colour
from document.rectangle import Rectangle
from pipeline.detect.mark import Ink, WordGeometry
from pipeline.rows.render import RenderStyle

# the drawing style, consistent across every experiment page
BOX_FILL = Colour(red=0, green=200, blue=255, alpha=25)  # word boxes: faint cyan fill with a thin edge
BOX_EDGE = Colour(red=0, green=200, blue=255, alpha=160)
WAISTLINE = Colour(red=0, green=255, blue=80, alpha=255)  # the top of the letter bodies: green
BASELINE = Colour(red=255, green=60, blue=60, alpha=255)  # the bottom contour: red
STROKE = Colour(red=255, green=230, blue=0, alpha=255)  # the reviewer's yellow lines


class _MissingOverride:
    """The 'no override given' marker - its own type so a union with the
    override collapses to the real domain values (pyrefly narrows on `is`)."""

    __slots__ = ()


_MISSING = _MissingOverride()  # distinguishes "not given" from an explicit refusal


# ---------------------------------------------------------------- measurement


def measure_words(ink: np.ndarray, boxes: Sequence[Sequence[float]], margin: int = 4) -> list[WordGeometry | None]:
    """Every box's measured lines, purely from the ink inside it. A box with
    almost no ink (a stray coordinate, a scan edge) measures to None - the
    drawing skips it rather than inventing lines for it."""
    out: list[WordGeometry | None] = []
    for x0, y0, x1, y1 in boxes:
        ix0 = int(round(x0 - margin))
        iy0 = int(round(y0 - margin))
        ix1 = int(round(x1 + margin))
        iy1 = int(round(y1 + margin))
        region = ink[max(iy0, 0) : iy1, max(ix0, 0) : ix1]
        ys, xs = np.nonzero(region)
        if len(ys) < 3:
            out.append(None)
            continue
        ny = (ys + max(iy0, 0)).astype(np.float32)
        nx = (xs + max(ix0, 0)).astype(np.float32)
        out.append(
            WordGeometry(
                baseline=float(Ink(ny, nx).baseline_row()),
                waistline=float(Ink(ny, nx).waistline_row()),
            )
        )
    return out


# ------------------------------------------------------------------ resolution


def resolve(
    measured: WordGeometry | None, override: WordGeometry | None | _MissingOverride = _MISSING
) -> WordGeometry | None:
    """What a word's lines are: the override when given (None refuses the
    word - no lines at all), else the measurement. Pure: no state, no order
    to remember - both voices speak WordGeometry with named fields."""
    if isinstance(override, _MissingOverride):
        return measured
    return override


def drawn_geometry(
    boxes: Sequence[Sequence[float]],
    measured: Sequence[WordGeometry | None],
    overrides: dict[int, WordGeometry | None] | None = None,
    indices: Sequence[int] | None = None,
) -> list[tuple[int, Sequence[float], WordGeometry | None]]:
    """Zip each box with the geometry that will be drawn: (page word index,
    box, lines-or-None). `indices` is the page index of each box - a strip's
    boxes are the page's words in the SAME order, so the overrides (keyed by
    page index) match; without it the boxes are their own page (0..n-1)."""
    order = indices if indices is not None else range(len(boxes))
    return [
        (page_index, box, resolve(m, overrides.get(page_index, _MISSING) if overrides else _MISSING))
        for page_index, (box, m) in zip(order, zip(boxes, measured, strict=False), strict=False)
    ]


# --------------------------------------------------------------------- drawing


def draw_word_lines(layer: ImageDraw.ImageDraw, box: Sequence[float], geometry: WordGeometry) -> None:
    """One word's lines in PAGE coordinates: green waistline, red baseline,
    the width of the box plus a hair. The ONE place line-drawing lives."""
    x0, _y0, x1, _y1 = box
    layer.line([x0 - 2, geometry.waistline, x1 + 2, geometry.waistline], fill=WAISTLINE, width=2)
    layer.line([x0 - 2, geometry.baseline, x1 + 2, geometry.baseline], fill=BASELINE, width=2)


@dataclass(frozen=True)
class FocusStrip:
    """One readable region of a page: the window, the page's words (addressed
    by their own indices), the margin of context around the window, what to
    highlight, and what to override."""

    region: Rectangle
    words: Sequence[dict]
    margin: float = 220
    highlight: Sequence[Rectangle] | None = None
    overrides: dict[int, WordGeometry | None] | None = None
    scale: int = 1


class PagePainter:
    """One experiment page's drawing: the page and its numbered strokes are
    the shared data; every paint stays in PAGE coordinates so a crop is the
    only thing that ever changes coordinates."""

    def __init__(
        self,
        page: Image.Image,
        strokes: Sequence[Sequence[tuple[float, float]]],
    ) -> None:
        self._page = page
        self._strokes = strokes

    def draw_page(
        self,
        boxes: Sequence[Sequence[float]],
        geometry: Sequence[tuple[int, Sequence[float], WordGeometry | None]],
        numbered: bool = True,
        draw_boxes: bool = True,
    ) -> Image.Image:
        """The full page: ink, the drawn lines per word, the numbered yellow
        strokes - all in page coordinates, so the crop is the only thing that
        ever changes coordinates."""
        page = self._page.convert("RGBA")
        overlay = Image.new("RGBA", page.size, (0, 0, 0, 0))
        layer = ImageDraw.Draw(overlay)
        if draw_boxes:
            for _index, box, _g in geometry:
                layer.rectangle(box, fill=BOX_FILL, outline=BOX_EDGE, width=2)
        for _index, box, g in geometry:
            if g is not None:
                draw_word_lines(layer, box, g)
        if self._strokes:
            font = ImageFont.load_default()
            known = [str(index + 1) for index, _ in enumerate(self._strokes)]
            label_w = max(font.getbbox(label)[2] for label in known) if known else 8
            content_left = min((b[0] for b in boxes), default=0.0)
            column = max(4.0, content_left - label_w - 46)
            for index, stroke in enumerate(self._strokes):
                band = sum(py for _, py in stroke) / len(stroke)
                layer.line(stroke, fill=STROKE, width=3, joint="curve")
                if numbered:
                    label = str(index + 1)
                    layer.rectangle([column, band - 8, column + label_w + 6, band + 8], fill=(0, 0, 0, 150))
                    layer.text((column + 3, band - 6), label, fill=(255, 255, 255, 255), font=font)
        return Image.alpha_composite(page, overlay).convert("RGB")

    def render_geometry(
        self,
        boxes: Sequence[Sequence[float]],
        draw_boxes: bool = True,
        overrides: dict[int, WordGeometry | None] | None = None,
    ) -> Image.Image:
        """Measure, resolve, draw: the whole page with its words' lines."""
        ink = np.asarray(self._page.convert("L")) < 170
        geometry = drawn_geometry(boxes, measure_words(ink, boxes), overrides)
        return self.draw_page(boxes, geometry, draw_boxes=draw_boxes)

    def render_focus(self, strip: FocusStrip) -> Image.Image:
        """One region of the page, readable. Rendered in page coordinates exactly
        like a full page, then CROPPED - no offset drawing, so a strip's lines
        are correct by construction. The words are the page's, addressed by their
        own indices (the first `words` word is index 0, the strip's boxes are a
        subset in the same order).
        """
        x0 = max(0.0, strip.region.x0 - strip.margin)
        y0 = max(0.0, strip.region.y0 - strip.margin)
        x1 = min(self._page.width, strip.region.x1 + strip.margin)
        y1 = min(self._page.height, strip.region.y1 + strip.margin)

        relevant = [
            (i, w)
            for i, w in enumerate(strip.words)
            if w["x1"] >= x0 - 4 and w["x0"] <= x1 + 4 and w["y1"] >= y0 - 4 and w["y0"] <= y1 + 4
        ]
        boxes = [Rectangle(w["x0"], w["y0"], w["x1"], w["y1"]) for _i, w in relevant]
        indices = [i for i, _w in relevant]
        ink = np.asarray(self._page.convert("L")) < 170
        geometry = drawn_geometry(boxes, measure_words(ink, boxes), strip.overrides, indices=indices)
        full = self.draw_page(boxes, geometry)

        overlay = Image.new("RGBA", full.size, (0, 0, 0, 0))
        layer = ImageDraw.Draw(overlay)
        for hx0, hy0, hx1, hy1 in strip.highlight or []:
            layer.rectangle([hx0, hy0, hx1, hy1], fill=(255, 0, 255, 30), outline=(255, 0, 255, 255), width=3)
        full = Image.alpha_composite(full.convert("RGBA"), overlay).convert("RGB")

        image = full.crop((int(x0), int(y0), int(x1), int(y1)))
        if strip.scale != 1:
            image = image.resize((image.width * strip.scale, image.height * strip.scale), Image.Resampling.LANCZOS)
        return image


# ----------------------------------------------------------------------- audit


def _line_spans(arr: np.ndarray, colour: Colour) -> dict[int, tuple[int, int]]:
    """Row -> (min, max) column span of the given line colour: each line's
    drawn extent. A word's line spans its box's width, so the span identifies
    its owner where boxes sit cheek by jowl."""
    mask = (
        (abs(arr[:, :, 0] - colour.red) <= 60)
        & (abs(arr[:, :, 1] - colour.green) <= 60)
        & (abs(arr[:, :, 2] - colour.blue) <= 60)
    )
    ys, xs = np.nonzero(mask)
    spans: dict[int, list[int]] = {
        int(y): [int(x) for _, x in group] for y, group in groupby(zip(ys, xs, strict=False), key=lambda yx: int(yx[0]))
    }
    return {y: (min(cols), max(cols)) for y, cols in spans.items()}


# lucidlint: ignore unused a test seam: the drawing tests drive the audit directly (DI convention)
def audit_geometry(
    image: Image.Image,
    boxes: Sequence[Sequence[float]],
    origin: tuple[float, float] = (0.0, 0.0),
) -> list[WordGeometry | None]:
    """Where the render actually placed each word's lines, as WordGeometry in
    page rows. `origin` = the page coordinates of the image's top-left (a crop
    of the full page; a full-page render needs none). A line is owned by the
    box its drawn span matches - neighbours' lines never bleed into each
    other's reading. None: no lines at all (a refused word, an uncovered
    box). One coordinate space: image rows + origin y = page rows."""
    ox, oy = origin
    arr = np.asarray(image.convert("RGB")).astype(int)
    greens = _line_spans(arr, Colour(red=0, green=255, blue=80))
    reds = _line_spans(arr, Colour(red=255, green=60, blue=60))

    def owned(spans: dict[int, tuple[int, int]], box: Sequence[float]) -> int | None:
        """The row of the word's own drawn line: the span that CONTAINS the
        box's full extent (a word's line is drawn exactly box-width + 4px),
        STARTS at the box's own left edge (a stranger's line begins elsewhere
        even when it spans this box), and among such rows the one whose span
        is closest to the box's own width."""
        width = box[2] - box[0]
        best: tuple[int, float] | None = None
        for row, (s0, s1) in spans.items():
            if s0 + ox <= box[0] - 2 and s1 + ox >= box[2] + 2:
                closeness = abs((s1 - s0) - width)
                if best is None or closeness < best[1]:
                    best = (row, closeness)
        return best[0] if best else None

    out: list[WordGeometry | None] = []
    for box in boxes:
        waist_row = owned(greens, box)
        base_row = owned(reds, box)
        if waist_row is None and base_row is None:
            out.append(None)
            continue
        out.append(
            WordGeometry(
                waistline=(waist_row + oy) if waist_row is not None else 0.0,
                baseline=(base_row + oy) if base_row is not None else 0.0,
            )
        )
    return out


# ------------------------------------------------------- presentation sheets

CAPTION_LINE_H = 26  # sheet px per caption line
CAPTION_PAD = 12  # sheet px around the caption block
CUT_RED = Colour(red=255, green=0, blue=0, alpha=255)  # cut rows read as warnings, never as ink
DROP_FILL = Colour(red=255, green=0, blue=0, alpha=60)  # dropped ink: translucent red over the band


class Crop(NamedTuple):
    """A page window at its read scale: crop in page px, LANCZOS up."""

    x0: float
    y0: float
    x1: float
    y1: float
    scale: float


def scaled_crop(page: Image.Image, crop: Crop) -> Image.Image:
    """The page window as a readable image: crop in page px, LANCZOS up."""
    window = page.crop((int(crop.x0), int(crop.y0), int(crop.x1), int(crop.y1)))
    return window.resize((int(window.width * crop.scale), int(window.height * crop.scale)), Image.Resampling.LANCZOS)


@dataclass(frozen=True)
class CaptionSheet:
    """The crop under a white caption bar: the sheet, its draw handle and the
    bar height the crop starts at."""

    sheet: Image.Image
    draw: ImageDraw.ImageDraw
    bar_height: int


def captioned_sheet(crop: Image.Image, caption: Sequence[str], size: int = 22) -> CaptionSheet:
    """The crop under a white caption bar, one fact per line."""
    bar_h = CAPTION_PAD + CAPTION_LINE_H * len(caption)
    sheet = Image.new("RGB", (crop.width, crop.height + bar_h), (255, 255, 255))
    sheet.paste(crop, (0, bar_h))
    draw = ImageDraw.Draw(sheet, "RGBA")
    font = ImageFont.load_default(size=size)
    for i, line in enumerate(caption):
        draw.text((10, 6 + CAPTION_LINE_H * i), line, fill=(20, 20, 20), font=font)
    return CaptionSheet(sheet, draw, bar_h)


def halo_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    fill: Colour | None = None,
    size: int = 24,
) -> None:
    """A label readable over ink: dark text with a white stroke halo."""
    draw.text(
        xy,
        text,
        fill=fill or Colour(red=15, green=15, blue=15),
        stroke_width=2,
        stroke_fill=(255, 255, 255),
        font=ImageFont.load_default(size=size),
    )


@dataclass(frozen=True)
class DashRule:
    """A dashed horizontal rule in sheet pixels: how a cut row reads."""

    x0: float
    x1: float
    y: float
    colour: Colour = CUT_RED
    dash: int = 8
    gap: int = 6
    width: int = 2


def dashed_hline(draw: ImageDraw.ImageDraw, rule: DashRule) -> None:
    """A dashed horizontal rule in sheet pixels: how a cut row reads."""
    x = rule.x0
    while x < rule.x1:
        draw.line([x, rule.y, min(x + rule.dash, rule.x1), rule.y], fill=rule.colour, width=rule.width)
        x += rule.dash + rule.gap


def contiguous_runs(values: Sequence[int]) -> list[list[int]]:
    """Sorted ints grouped into contiguous runs: dropped rows become bands."""
    ordered = sorted(values)
    runs: list[list[int]] = [
        [value for _, value in group] for _, group in groupby(enumerate(ordered), key=lambda iv: iv[1] - iv[0])
    ]
    return runs


@dataclass(frozen=True)
class LabeledBox:
    """A detected piece's outline with its halo label at the top-left corner:
    the colour carries the owner."""

    box: Rectangle
    outline: Colour
    label: str
    size: int = 24
    width: int = 3


def labeled_box(draw: ImageDraw.ImageDraw, spec: LabeledBox) -> None:
    """An outlined box with its halo label at the top-left corner: how a
    detected piece reads on a sheet. Both diagnose zooms and splitter case
    sheets label boxes this way."""
    draw.rectangle(spec.box, outline=spec.outline, width=spec.width)
    halo_text(draw, (spec.box.x0 + 3, spec.box.y0 + 2), spec.label, size=spec.size)


def stack_sheets(sheets: Sequence[Image.Image], gap: int = 24, max_width: int = 1000) -> Image.Image:
    """One review page from many sheets: stacked top to bottom on white,
    left-aligned, separated by `gap` px. Sheets wider than `max_width` are
    downscaled to it — a wider page fit to a phone screen scales thin ink
    below visibility, and the review arrives blank (2026-09-13: a 1580px
    contact sheet read as empty). Nothing is ever upscaled."""
    fitted = [
        s.resize((max_width, int(s.height * max_width / s.width)), Image.Resampling.LANCZOS)
        if s.width > max_width
        else s
        for s in sheets
    ]
    width = max(s.width for s in fitted)
    height = sum(s.height for s in fitted) + gap * (len(fitted) - 1)
    page = Image.new("RGB", (width, height), (255, 255, 255))
    y = 0
    for sheet in fitted:
        page.paste(sheet, (0, y))
        y += sheet.height + gap
    return page


REVIEW_WIDTH = 900  # sheet px: a review copy fits a phone screen at full width
REVIEW_QUALITY = 68  # JPEG quality: ink edges stay crisp, paper noise drops out


def review_image(sheet: Image.Image, width: int = REVIEW_WIDTH, quality: int = REVIEW_QUALITY) -> bytes:
    """The sheet as a review-size JPEG: downscaled to `width` (never up),
    saved at `quality`. Handwriting scans are paper-coloured noise around dark
    ink — JPEG at this quality keeps the ink and drops ~90% of the PNG bytes,
    so a six-sheet review page loads over LAN in seconds, not tens of
    seconds."""
    if sheet.width > width:
        sheet = sheet.resize((width, int(sheet.height * width / sheet.width)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


@dataclass(frozen=True)
class SplitCase:
    """One splitter case as a captioned sheet: the scan crop with the RAW
    component outline (black), every PIECE in its colour with its label,
    every CUT row (red dashed with its per-row profile in the caption), and
    any DROPPED bands (translucent red + label). All geometry is page px;
    the caller computed it from the splitter's own output — the drawing here
    only paints. Colours default to the house row palette in order."""

    page: Image.Image
    raw_box: Rectangle
    pieces: Sequence[tuple[Rectangle, str]]
    cuts: Sequence[tuple[float, Sequence[str]]]
    drops: Sequence[tuple[float, float]]
    drop_label: str
    title: str
    summary: str
    crop: Crop
    colours: Sequence[Colour] | None = None


def split_sheet(case: SplitCase) -> Image.Image:
    """One splitter case as a captioned sheet: the scan crop with the RAW
    component outline (black), every PIECE in its colour with its label,
    every CUT row (red dashed with its per-row profile in the caption), and
    any DROPPED bands (translucent red + label). All geometry is page px;
    the caller computed it from the splitter's own output — this function
    only draws. Colours default to the house row palette in order."""
    x0, y0, x1, y1, scale = case.crop
    crop_img = scaled_crop(case.page, case.crop)
    caption = [case.title, case.summary, *(f"cut y{cy:.0f} -> [{prof}]" for cy, prof in case.cuts)]
    caption_sheet = captioned_sheet(crop_img, caption)
    sheet, draw, bar_h = caption_sheet.sheet, caption_sheet.draw, caption_sheet.bar_height

    def px(v: float) -> float:
        return (v - x0) * scale

    def py(v: float) -> float:
        return (v - y0) * scale + bar_h

    style = RenderStyle() if case.colours is None else None
    draw.rectangle(
        [px(case.raw_box.x0), py(case.raw_box.y0), px(case.raw_box.x1), py(case.raw_box.y1)],
        outline=(0, 0, 0, 255),
        width=2,
    )
    for i, (box, label) in enumerate(case.pieces):
        colour = (
            Colour(*style.colour(i)[:3])
            if style is not None
            else case.colours[i]
            if case.colours is not None
            else Colour(red=200, green=0, blue=0)
        )
        labeled_box(draw, LabeledBox(Rectangle(px(box.x0), py(box.y0), px(box.x1), py(box.y1)), colour, label))
    for cy, _prof in case.cuts:
        if y0 < cy < y1:
            left, right = px(max(x0, case.raw_box.x0)), px(min(x1, case.raw_box.x1))
            dashed_hline(draw, DashRule(left, right, py(cy)))
            halo_text(draw, (right - 150, py(cy) - 28), f"cut y{cy:.0f}", fill=Colour(red=200, green=0, blue=0))
    for lo, hi in case.drops:
        draw.rectangle([px(case.raw_box.x0), py(lo), px(case.raw_box.x1), py(hi)], fill=DROP_FILL)
    if case.drops:
        biggest = max(case.drops, key=lambda run: run[1] - run[0])
        label_y = max(biggest[1], max(box.y1 for box, _label in case.pieces) + 2)
        halo_text(
            draw, (px(case.raw_box.x0) + 4, py(label_y) + 2), case.drop_label, fill=Colour(red=200, green=0, blue=0)
        )
    return sheet
