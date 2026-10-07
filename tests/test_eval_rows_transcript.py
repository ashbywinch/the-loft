"""The eval-side reading machinery: the alone-crop must isolate one row, and
the reviewer's drawn lines must reach the render."""

from __future__ import annotations

from PIL import Image

from tools.eval_rows_transcript import alone_crop, draw_user_rows
from tools.rectangle import Rectangle
from tools.row import Row
from tools.word import Word

PAGE = (2544, 4642)


def _row(number: int, words: list[tuple[float, float, float, float]]) -> Row:
    boxes = [Word(x0, y0, x1, y1) for x0, y0, x1, y1 in words]
    band = Rectangle(
        min(w.x0 for w in boxes),
        min(w.y0 for w in boxes),
        max(w.x1 for w in boxes),
        max(w.y1 for w in boxes),
    )
    return Row(id=f"seg-{number}", kind="body", number=number, word_boxes=boxes, band=band)


def test_the_alone_crop_stops_at_the_neighbours_mid_gap() -> None:
    """The tight stacks are why rows went unread twice: a ±24px margin from one
    row's words reaches the neighbour's line in a 40px stack, so both crops
    show the same writing and the model returns the same text for both rows
    (page-01's 26 and 27, both "year we performed the Mahler 8th"). The crop's
    vertical margin stops where the gap to the neighbour halves — and where the
    bands OVERLAP, the margin is zero, so the crop is the row's own words and
    nothing below them."""
    above = _row(25, [(660, 3560, 760, 3596), (980, 3566, 1042, 3696)])  # band ends 3696
    row = _row(26, [(566, 3632, 624, 3672), (648, 3632, 784, 3712)])  # band 3632-3712, overlaps both neighbours
    below = _row(27, [(552, 3704, 644, 3764), (1036, 3704, 1096, 3742)])
    left, top, right, bottom = alone_crop(row, [above, row, below], PAGE)
    assert left == 566 - 24 and right == 784 + 24, "the horizontal margin is unchanged"
    assert top == 3632, f"the crop starts at {top}, a margin away from its own words"
    assert bottom == 3712, f"the crop reaches {bottom}, into the row below's band"


def test_the_alone_crop_between_well_separated_rows_keeps_the_margin() -> None:
    above = _row(1, [(100, 100, 200, 140)])
    row = _row(2, [(100, 400, 200, 440)])
    below = _row(3, [(100, 800, 200, 840)])
    left, top, right, bottom = alone_crop(row, [above, row, below], PAGE)
    assert top == 400 - 24, f"expected the full 24px margin above, got top={top}"
    assert bottom == 440 + 24, f"expected the full 24px margin below, got bottom={bottom}"
    assert left == 100 - 24 and right == 200 + 24


def test_the_drawn_rows_reach_the_canvas() -> None:
    """The fixture's lines are normalised 0..1 (the form `Rows.adjust`
    consumes), and drawn raw they collapsed to specks in the corner: strip 1
    showed 5 yellow marks where the reviewer drew 44. The lines must land at
    their scaled positions across the page."""
    canvas = Image.new("RGB", (400, 200), (247, 243, 232))
    draw_user_rows(canvas, [[(0.1, 0.3), (0.5, 0.3)], [(0.2, 0.7), (0.45, 0.7)]])
    pixels = canvas.convert("RGB")
    assert any(pixels.getpixel((x, 60)) == (250, 210, 30) for x in range(40, 201)), "the first line missed its y"
    assert any(pixels.getpixel((x, 140)) == (250, 210, 30) for x in range(80, 181)), "the second line missed its y"
    assert pixels.getpixel((30, 60)) != (250, 210, 30), "a line was drawn left of where the stroke was"
