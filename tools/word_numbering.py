"""The numbered renderer for the VLM word-segmentation spike (milestone 1,
docs/plans/vlm-word-segmentation-spike.md).

Pure: a page image, a section, and the words in -> the numbered-boxes image
the VLM reads, plus the chip placements (the tested part). The spike's caller
chooses the scale (sections are rendered so small words survive the
provider's downscale).

Contract, from the plan and the user's checks:

- one hue per word, a designed palette — distinct in colour and grayscale
  (the model may downscale);
- the number on a transparent chip (a thin ring in the word's hue, the page
  showing through) at the box's top-left corner when free, else the first
  free direction (above, below, left, right, then further along the
  perimeter), hugging the box at CHIP_GAP;
- the chip's bounding box IS the number's text bbox plus the ring pad — a
  chip is never larger than its text needs, and never beyond MAX_CHIP on
  either side;
- collision-free: a chip never covers another word's box OR another chip — a
  word whose every position is taken is reported, never silently overlapped.

The render ids are the reading order: words sorted by their centre's y, then
their left edge — top-to-bottom, left-to-right. The chips show 1-based ids;
the VLM's word_ids use the same numbering; the caller maps back to page ids.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

Box = tuple[float, float, float, float]  # x0, y0, x1, y1, page px

# 12 hues: spread around the wheel, varied lightness so the greys differ too
PALETTE: tuple[tuple[int, int, int], ...] = (
    (214, 39, 40),  # red
    (31, 119, 180),  # blue
    (44, 160, 44),  # green
    (255, 127, 14),  # orange
    (148, 103, 189),  # purple
    (23, 190, 207),  # cyan
    (227, 119, 194),  # pink
    (188, 189, 34),  # olive
    (140, 86, 75),  # brown
    (127, 127, 127),  # grey
    (255, 152, 150),  # light red
    (152, 223, 138),  # light green
)

CHIP_GAP = 1.5  # section px between a chip and the word it labels
CHIP_PAD = 3.0  # section px: the ring's padding around the number on each side
EDGE_PAD = 1.0  # section px: a chip may not come this close to another box
FONT_FRACTION = 0.55  # x the word's height: the number's font size
MIN_FONT = 8.0  # section px: below this the number is unreadable
MAX_FONT = 20.0  # section px: a number never needs to be bigger
MAX_CHIP = 40.0  # section px: a chip's side never exceeds this
CHIP_SHRINK_STEPS = (1.0, 0.7, 0.5, 0.35)  # x the font size, tried in order
UNPLACED = "unplaced"  # the placement verdict when every position is taken


@lru_cache(maxsize=64)
def _font_at(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """The number font — `load_default(size=...)` needs Pillow >= 10.1, pinned at 12.3.0."""
    return ImageFont.load_default(size=size)


def _text_bbox(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> tuple[float, float, float, float]:
    """The number's bounds at a font — measured on a throwaway draw (Pillow's
    stubs only expose textbbox on a Draw)."""
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    return draw.textbbox((0, 0), text, font=font)


def chip_extent(text: str, font_size: float) -> tuple[float, float]:
    """The chip's (width, height) for a number: the text's bounding box at
    that font, plus the ring pad, capped at MAX_CHIP — the chip's bbox
    matches the font size, never larger than the cap."""
    font = _font_at(max(7, round(font_size)))
    tb = _text_bbox(text, font)
    width = float(tb[2] - tb[0] + 2 * CHIP_PAD)
    height = float(tb[3] - tb[1] + 2 * CHIP_PAD)
    if width <= MAX_CHIP and height <= MAX_CHIP:
        return (width, height)
    # the number is too wide for the cap: shrink the font so the TEXT fits
    # (the padding is not linear in the font size), then clamp the final
    # result so glyph rounding can never exceed the cap
    target = MAX_CHIP - 2 * CHIP_PAD
    text_width = width - 2 * CHIP_PAD
    text_height = height - 2 * CHIP_PAD
    font = _font_at(max(7, round(font_size * target / max(text_width, text_height))))
    tb = _text_bbox(text, font)
    return (
        min(float(tb[2] - tb[0] + 2 * CHIP_PAD), MAX_CHIP),
        min(float(tb[3] - tb[1] + 2 * CHIP_PAD), MAX_CHIP),
    )


def _base_font(box: Box) -> float:
    """The number's font size for a word: the word's height scaled, floored
    and capped."""
    return max(MIN_FONT, min((box[3] - box[1]) * FONT_FRACTION, MAX_FONT))


@dataclass(frozen=True)
class Chip:
    """A word's number chip: which render id it carries, its footprint and
    the font size its text is drawn at."""

    render_id: int  # 1-based, the number drawn on the chip
    rect: Box  # section px: the text bbox + CHIP_PAD, clamped to MAX_CHIP
    colour: tuple[int, int, int]
    verdict: str  # "corner" | "above" | "below" | "left" | "right" | perimeter | UNPLACED
    font_size: float  # section px: the size the number is drawn at


def numbered_order(words: list[Box]) -> list[int]:
    """The render ids' order: reading order — the centre's y, then the left edge.

    Words on the same writing line share a centre-y; a row is read left to
    right. Ties (identical boxes) keep their input order, so the mapping is
    stable and reversible.
    """
    return sorted(range(len(words)), key=lambda i: (words[i][1] + words[i][3]) / 2 + words[i][0] / 1e6)


def candidates(box: Box, width: float, height: float) -> list[tuple[str, Box]]:
    """A word's placement positions in order — the plan's "above, below,
    left, right, then further along the perimeter". The first position whose
    rect collides with no other word's box wins."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    gap = CHIP_GAP
    w, h = width, height
    box_w, box_h = x1 - x0, y1 - y0
    return [
        ("corner", (x0 - gap - w, y0 - gap - h, x0 - gap, y0 - gap)),
        ("above", (cx - w / 2, y0 - gap - h, cx + w / 2, y0 - gap)),
        ("below", (cx - w / 2, y1 + gap, cx + w / 2, y1 + gap + h)),
        ("left", (x0 - gap - w, cy - h / 2, x0 - gap, cy + h / 2)),
        ("right", (x1 + gap, cy - h / 2, x1 + gap + w, cy + h / 2)),
        ("top-right", (x1 + gap, y0 - gap - h, x1 + gap + w, y0 - gap)),
        ("bottom-left", (x0 - gap - w, y1 + gap, x0 - gap, y1 + gap + h)),
        ("bottom-right", (x1 + gap, y1 + gap, x1 + gap + w, y1 + gap + h)),
        ("above-left", (x0 + box_w / 3 - w / 2, y0 - gap - h, x0 + box_w / 3 + w / 2, y0 - gap)),
        ("above-right", (x0 + 2 * box_w / 3 - w / 2, y0 - gap - h, x0 + 2 * box_w / 3 + w / 2, y0 - gap)),
        ("below-left", (x0 + box_w / 3 - w / 2, y1 + gap, x0 + box_w / 3 + w / 2, y1 + gap + h)),
        ("below-right", (x0 + 2 * box_w / 3 - w / 2, y1 + gap, x0 + 2 * box_w / 3 + w / 2, y1 + gap + h)),
        ("left-top", (x0 - gap - w, y0 + box_h / 3 - h / 2, x0 - gap, y0 + box_h / 3 + h / 2)),
        ("left-bottom", (x0 - gap - w, y0 + 2 * box_h / 3 - h / 2, x0 - gap, y0 + 2 * box_h / 3 + h / 2)),
        ("right-top", (x1 + gap, y0 + box_h / 3 - h / 2, x1 + gap + w, y0 + box_h / 3 + h / 2)),
        ("right-bottom", (x1 + gap, y0 + 2 * box_h / 3 - h / 2, x1 + gap + w, y0 + 2 * box_h / 3 + h / 2)),
    ]


def _intersects(chip: Box, box: Box) -> bool:
    """A chip collides when it reaches another word's box, padded."""
    c0, c1, c2, c3 = chip
    b0, b1, b2, b3 = box
    return not (c2 + EDGE_PAD <= b0 or c0 - EDGE_PAD >= b2 or c3 + EDGE_PAD <= b1 or c1 - EDGE_PAD >= b3)


def place_chips(boxes: list[Box], order: list[int]) -> list[Chip]:
    """Every word's chip, placed at the first collision-free position.

    The chip is sized by its number's text at a word-scaled font (capped at
    MAX_CHIP); the shrink pass steps the font down. A chip collides when it
    reaches another word's box OR an already-placed chip. A word whose every
    position is taken at every font size reports verdict UNPLACED (its rect
    is the corner position; the caller must not draw it silently — the spike
    reports unplaced words loudly).
    """
    occupied: list[Box] = [boxes[i] for i in range(len(boxes))]  # the other words' boxes
    chips: list[Chip] = []
    placed_rects: list[Box] = []
    for render_id, word_index in enumerate(order, start=1):
        box = boxes[word_index]
        text = str(render_id)
        chosen: tuple[str, Box, float] | None = None
        for fraction in CHIP_SHRINK_STEPS:
            font_size = max(MIN_FONT, _base_font(box) * fraction)
            width, height = chip_extent(text, font_size)
            for verdict, rect in candidates(box, width, height):
                blocked = any(_intersects(rect, other) for other in occupied if other is not box)
                blocked = blocked or any(_intersects(rect, other) for other in placed_rects)
                if not blocked:
                    chosen = (verdict, rect, font_size)
                    break
            if chosen is not None:
                break
        if chosen is None:
            width, height = chip_extent(text, _base_font(box))
            chosen = (UNPLACED, candidates(box, width, height)[0][1], _base_font(box))
        verdict, rect, font_size = chosen
        chips.append(
            Chip(
                render_id=render_id,
                rect=rect,
                colour=PALETTE[word_index % len(PALETTE)],
                verdict=verdict,
                font_size=font_size,
            )
        )
        if verdict != UNPLACED:
            placed_rects.append(rect)
    return chips


def render_numbered(
    page: Image.Image,
    section: Box,
    boxes: list[Box],
    scale: float,
) -> tuple[Image.Image, list[Chip]]:
    """The numbered image: the section cropped, every word's box outlined in
    its hue, every number on a transparent chip at the placed position.

    Returns (image, chips) — the chips' rects are in section pixels, so the
    caller can audit the placement (the collision tests use them).
    """
    x0, y0, x1, y1 = section
    width, height = round((x1 - x0) * scale), round((y1 - y0) * scale)
    image = (
        page.convert("RGB").crop((int(x0), int(y0), int(x1), int(y1))).resize((width, height), Image.Resampling.LANCZOS)
    )

    scaled = [(b[0] - x0, b[1] - y0, b[2] - x0, b[3] - y0) for b in boxes]
    scaled = [(a * scale, b * scale, c * scale, d * scale) for a, b, c, d in scaled]
    order = numbered_order(scaled)
    chips = place_chips(scaled, order)

    draw = ImageDraw.Draw(image)
    box_width = max(2, round(scale))
    for word_index in order:
        hue = PALETTE[word_index % len(PALETTE)]
        x0w, y0w, x1w, y1w = scaled[word_index]
        draw.rectangle((x0w, y0w, x1w, y1w), outline=hue, width=box_width)

    for chip in chips:
        if chip.verdict == UNPLACED:
            continue  # the caller reports the unplaced words; never draw a lie
        cx0, cy0, cx1, cy1 = chip.rect
        # transparent chip: a thin ring around the number's own footprint, the
        # page showing through
        draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, outline=chip.colour, width=1)
        text = str(chip.render_id)
        font = _font_at(round(chip.font_size))
        tb = draw.textbbox((0, 0), text, font=font)
        draw.text(
            ((cx0 + cx1) / 2 - (tb[2] - tb[0]) / 2, (cy0 + cy1) / 2 - (tb[3] - tb[1]) / 2),
            text,
            fill=(15, 15, 15),
            stroke_width=1,
            stroke_fill=(245, 245, 245),
            font=font,
        )
    return image, chips


def unplaced(chips: list[Chip]) -> list[int]:
    """The render ids that found no free position — the caller reports them."""
    return [chip.render_id for chip in chips if chip.verdict == UNPLACED]


def palette_luminances() -> np.ndarray:
    """The palette's grayscale values — distinct under the model's downscale."""
    return np.asarray([0.299 * r + 0.587 * g + 0.114 * b for r, g, b in PALETTE])
