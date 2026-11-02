"""Rendering writing rows for the reviewer's eyes.

A row's box is drawn as the bounding boxes of its words joined by the
smallest possible band: between two adjacent words, a rectangle as tall as the
SHORTER of the two (never spanning the gap's full height), centred on their
overlap. Each row gets a faint background tint of its own colour - no outline,
so the page's ink stays the loudest thing. Yellow lines, when given, are drawn
numbered, so a reviewer can say "line 12 is wrong" precisely.

Rendering only: no judgement about what is or isn't a line lives here.
"""

from __future__ import annotations

import colorsys
from collections.abc import Sequence
from dataclasses import dataclass

import PIL
from PIL import Image, ImageDraw, ImageFont

from document.colour import Colour
from document.row import Row
from document.row_tint import RowTint

# Pillow 9.2 added the size argument to ImageFont.load_default - earlier
# Pillows take no size. A version capability, checked once - never an
# exception-based fallback (the try/except was an invisible swallow).
_PILLOW_HAS_SIZEABLE_DEFAULT_FONT = tuple(int(part) for part in PIL.__version__.split(".")) >= (9, 2)


@dataclass(frozen=True)
class RenderStyle:
    """How much of the join band to draw, and how opaque the tint is."""

    tint: int = 55  # 0-255: the row colour's alpha over the paper

    def colour(self, index: int) -> Colour:
        """A distinct hue per row, spaced by the golden ratio so neighbours
        never share one - alpha included."""
        r, g, b = colorsys.hsv_to_rgb((index * 0.618) % 1.0, 0.62, 0.95)
        return Colour(int(r * 255), int(g * 255), int(b * 255), self.tint)


DEFAULT_STYLE = RenderStyle()


def _stroke_font() -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """The stroke numbers' font: the size-capable default when the Pillow
    in use has one (9.2+), else the plain unscaled default."""
    if _PILLOW_HAS_SIZEABLE_DEFAULT_FONT:
        return ImageFont.load_default(size=52)
    return ImageFont.load_default()


def tint_row(draw: ImageDraw.ImageDraw, row: Row, colour: Colour) -> None:
    """One row as tinted rectangles: each word's bounds, joined by the minimal
    bands (`Row.tint_rects`, the same rectangles the review screen draws). No
    outline: the ink stays the loudest thing on the page."""
    tint = RowTint.of(row, colour)
    for rect in tint.rects:
        draw.rectangle([rect.x0, rect.y0, rect.x1, rect.y1], fill=tint.colour)


def render_rows(
    page: Image.Image,
    rows: Sequence[Row],
    strokes: Sequence[Sequence[tuple[float, float]]] | None = None,
    style: RenderStyle = DEFAULT_STYLE,
) -> Image.Image:
    """The page with every row's box drawn as a faint tinted union of its
    words, and - when strokes are given - the yellow lines drawn numbered.
    Returns a copy; the input page is untouched.

    The tint is a translucent overlay COMMITTED ONLY BY COMPOSITION: a plain
    convert("RGB") after drawing discards alpha, and the colour would land on
    the page at full opacity - covering the very ink it is meant to tint.
    """
    page_rgba = page.convert("RGBA")
    overlay = Image.new("RGBA", page_rgba.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for row_index, row in enumerate(rows):
        tint_row(draw, row, style.colour(row_index))
    canvas = Image.alpha_composite(page_rgba, overlay)
    if strokes is not None:
        draw = ImageDraw.Draw(canvas)
        font = _stroke_font()
        for number, stroke in enumerate(strokes):
            points = [(x, y) for x, y in stroke]
            draw.line(points, fill=(250, 210, 30), width=7)
            if points:
                # the number sits in the gutter IMMEDIATELY LEFT of the line's
                # own words, centred on the line's band: far enough to never
                # touch the ink, close enough that the eye assigns it instantly
                left = min(px for px, _ in points)
                band = min(py for _, py in points), max(py for _, py in points)
                mid = (band[0] + band[1]) / 2
                draw.ellipse([left - 96, mid - 36, left - 10, mid + 36], fill=(255, 255, 255))
                draw.text((left - 88, mid - 27), f"{number:02d}", fill=(0, 0, 0), font=font)
    return canvas.convert("RGB")
