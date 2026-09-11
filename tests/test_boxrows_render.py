"""Tests for the row-box renderer (tools/boxrows_render.py).

The renderer is a presentation function: the joins are the minimum band
between a row's words, the tint is faint, and the yellow lines come numbered.
"""

from __future__ import annotations

from PIL import Image

from tools.boxrows import Page, Rectangle, Row, Word
from tools.boxrows_render import join_band, render_rows

SPACING = 67.6


def test_join_band_height_is_the_shorter_word() -> None:
    band = join_band(Rectangle(0, 10, 40, 40), Rectangle(60, 30, 100, 50))
    assert band.x0 == 40
    assert band.x1 == 60
    assert band.height == 20  # min(30, 20)
    # centred on the words' vertical overlap (30-40): mid 35, so 25-45
    assert band.y0 == 25
    assert band.y1 == 45


def test_join_band_without_vertical_overlap_centres_on_the_midpoint() -> None:
    band = join_band(Rectangle(0, 0, 40, 20), Rectangle(60, 90, 100, 110))
    assert band.height == 20  # min(20, 20)
    assert band.y0 == 45
    assert band.y1 == 65


def test_render_rows_tints_words_and_joins_without_an_outline() -> None:
    """Two words sharing a row: the render is the page plus the two word
    tints and the join band; no outline colour besides the page's own."""
    page = Image.new("RGB", (120, 60), (250, 250, 245))
    page_model = Page([Word(10, 10, 40, 40), Word(60, 15, 100, 45)], SPACING)
    rows = [Row(words=[0, 1])]
    out = render_rows(page, page_model, rows)
    # the join band (x 40-60, centred on the overlap 15-40, height min(30,30))
    assert out.getpixel((50, 27)) != (250, 250, 245), "join band not tinted"
    # a word tint
    assert out.getpixel((20, 30)) != (250, 250, 245), "word not tinted"
    # outside the row: untouched paper
    assert out.getpixel((5, 30)) == (250, 250, 245)


def test_render_rows_numbers_the_yellow_lines() -> None:
    page = Image.new("RGB", (300, 100), (250, 250, 245))
    page_model = Page([Word(10, 10, 40, 40)], SPACING)
    out = render_rows(page, page_model, [Row(words=[0])], strokes=[[(50, 50), (200, 50)]])
    # the stroke's own yellow shows through near its end
    assert out.getpixel((150, 50)) != (250, 250, 245)


def test_numbers_sit_in_the_gutter_never_over_the_writing() -> None:
    """The line numbers must be readable as each line's own, without covering
    a single word: every disc ends before its line's leftmost words begin."""
    page = Image.new("RGB", (800, 200), (250, 250, 245))
    page_model = Page(
        [
            Word(300, 0, 350, 30),
            Word(400, 2, 470, 32),
            Word(300, 60, 340, 90),
            Word(380, 62, 440, 92),
        ],
        SPACING,
    )
    rows = [Row(words=[0, 1]), Row(words=[2, 3])]
    strokes = [[(320, 15), (700, 15)], [(330, 75), (700, 75)]]
    out = render_rows(page, page_model, rows, strokes)
    for row_index, (row, stroke) in enumerate(zip(rows, strokes, strict=False)):
        left = min(page_model.words[i].x0 for i in row.words)
        disc_left, disc_right = left - 96, left - 10
        assert disc_right < left, "the disc must not reach the line's words"
        mid = (min(py for _, py in stroke) + max(py for _, py in stroke)) / 2
        assert out.getpixel((int((disc_left + disc_right) / 2), int(mid))) != (250, 250, 245), (
            f"line {row_index}: no disc beside its words"
        )
