"""Rendering row boxes for the reviewer's eyes.

A row's box is drawn as the bounding boxes of its words joined by the
smallest possible band: between two adjacent words, a rectangle as tall as the
SHORTER of the two (never spanning the gap's full height), centred on their
overlap. Each row gets a faint background tint of its own colour - no outline,
so the page's ink stays the loudest thing. Yellow lines, when given, are drawn
numbered, so a reviewer can say "line 12 is wrong" precisely.

Rendering only: no judgement about what is or isn't a line lives here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image, ImageDraw

from tools.boxrows import Box, row_boxes


@dataclass(frozen=True)
class RenderStyle:
    """How much of the join band to draw, and how opaque the tint is."""

    tint: int = 55  # 0-255: the row colour's alpha over the paper

    def colour(self, index: int) -> tuple[int, int, int, int]:
        """A distinct hue per row, spaced by the golden ratio so neighbours
        never share one - alpha included."""
        import colorsys

        r, g, b = colorsys.hsv_to_rgb((index * 0.618) % 1.0, 0.62, 0.95)
        return int(r * 255), int(g * 255), int(b * 255), self.tint


DEFAULT_STYLE = RenderStyle()


def join_band(left: Box, right: Box) -> Box:
    """The band joining two adjacent words of one row: as tall as the shorter
    word, centred on the two words' vertical overlap (or their centres when
    they do not overlap)."""
    width = right.x0 - left.x1
    if width <= 0:
        return Box(left.x1, min(left.y1, right.y1), left.x1, min(left.y1, right.y1))
    top = max(left.y0, right.y0)
    bottom = min(left.y1, right.y1)
    if bottom <= top:  # no vertical overlap: centre on the gap midpoint
        centre = (left.y1 + right.y0) / 2
        top, bottom = centre, centre
    height = min(left.height, right.height)
    mid = (top + bottom) / 2
    return Box(left.x1, mid - height / 2, right.x0, mid + height / 2)


def tint_row(
    draw: ImageDraw.ImageDraw, boxes: Sequence[Box], row: Sequence[int], colour: tuple[int, int, int, int]
) -> None:  # noqa: E501
    """One row as tinted rectangles: each word's bounds, joined by the minimal
    bands. No outline: the ink stays the loudest thing on the page."""
    ordered = sorted(row, key=lambda i: boxes[i].x0)
    for first, second in zip(ordered, ordered[1:], strict=False):
        band = join_band(boxes[first], boxes[second])
        draw.rectangle([band.x0, band.y0, band.x1, band.y1], fill=colour)
    for index in ordered:
        box = boxes[index]
        draw.rectangle([box.x0, box.y0, box.x1, box.y1], fill=colour)


def render_rows(
    page: Image.Image,
    boxes: Sequence[Box],
    rows: Sequence[Sequence[int]],
    strokes: Sequence[Sequence[tuple[float, float]]] | None = None,
    style: RenderStyle = DEFAULT_STYLE,
) -> Image.Image:
    """The page with every row's box drawn as a faint tinted union of its
    words, and - when strokes are given - the yellow lines drawn numbered.
    Returns a copy; the input page is untouched."""
    canvas = page.convert("RGBA").copy()
    draw = ImageDraw.Draw(canvas)
    for row_index, row in enumerate(rows):
        colour = style.colour(row_index)
        tint_row(draw, boxes, row, colour)
    if strokes is not None:
        for number, stroke in enumerate(strokes):
            points = [(x, y) for x, y in stroke]
            draw.line(points, fill=(250, 210, 30, 255), width=6)
            if points:
                label = f"{number:02d}"
                draw.text((points[0][0] + 10, points[0][1] - 34), label, fill=(0, 0, 0))
    return canvas.convert("RGB")


def render_rows_with_line_boxes(
    page: Image.Image,
    boxes: Sequence[Box],
    rows: Sequence[Sequence[int]],
    spacing: float,
    strokes: Sequence[Sequence[tuple[float, float]]] | None = None,
    style: RenderStyle = DEFAULT_STYLE,
) -> Image.Image:
    """Like render_rows, but each row's box is also outlined - the review
    surface's comparison view, where the outline is the point."""
    canvas = render_rows(page, boxes, rows, strokes, style)
    draw = ImageDraw.Draw(canvas)
    for row_index, box in enumerate(row_boxes(rows, boxes, spacing)):
        draw.rectangle([box.x0, box.y0, box.x1, box.y1], outline=style.colour(row_index), width=3)
    return canvas
