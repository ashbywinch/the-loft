"""Tests for the row-box renderer (tools/boxrows_render.py).

The renderer is a presentation function: the joins are the minimum band
between a row's words, the tint is faint, and the yellow lines come numbered.
"""

from __future__ import annotations

from PIL import Image

from tools.boxrows import Box
from tools.boxrows_render import join_band, render_rows


def test_join_band_height_is_the_shorter_word() -> None:
    band = join_band(Box(0, 10, 40, 40), Box(60, 30, 100, 50))
    assert band.x0 == 40
    assert band.x1 == 60
    assert band.height == 20  # min(30, 20)
    # centred on the words' vertical overlap (30-40): mid 35, so 25-45
    assert band.y0 == 25
    assert band.y1 == 45


def test_join_band_without_vertical_overlap_centres_on_the_midpoint() -> None:
    band = join_band(Box(0, 0, 40, 20), Box(60, 90, 100, 110))
    assert band.height == 20  # min(20, 20)
    assert band.y0 == 45
    assert band.y1 == 65


def test_render_rows_tints_words_and_joins_without_an_outline() -> None:
    """Two words sharing a row: the render is the page plus the two word
    tints and the join band; no outline colour besides the page's own."""
    page = Image.new("RGB", (120, 60), (250, 250, 245))
    boxes = [Box(10, 10, 40, 40), Box(60, 15, 100, 45)]
    rows = [[0, 1]]
    out = render_rows(page, boxes, rows)
    # the join band (x 40-60, centred on the overlap 15-40, height min(30,30))
    assert out.getpixel((50, 27)) != (250, 250, 245), "join band not tinted"
    # a word tint
    assert out.getpixel((20, 30)) != (250, 250, 245), "word not tinted"
    # outside the row: untouched paper
    assert out.getpixel((5, 30)) == (250, 250, 245)


def test_render_rows_numbers_the_yellow_lines() -> None:
    page = Image.new("RGB", (300, 100), (250, 250, 245))
    out = render_rows(page, [Box(10, 10, 40, 40)], [[0]], strokes=[[(50, 50), (200, 50)]])
    # the stroke's own yellow shows through near its end
    assert out.getpixel((150, 50)) != (250, 250, 245)
