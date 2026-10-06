"""The row numbers' placement: the rules that keep them readable.

Page-01 is the case that broke every earlier attempt: rows 20px apart whose
bands overlap, whose ink reaches into the gap on either side, and whose writing
is ragged at both edges. The rules below are what the render must hold whatever
the page does — they are the checks I should have written before claiming any of
them fixed.

The real fixture is used for the invariants (its geometry is the hard case);
small synthetic rows pin the placement order itself.
"""

from __future__ import annotations

import colorsys
from pathlib import Path

import numpy as np
from PIL import Image

from document.numbered_rows import PILL_INSET as PILL_GAP
from document.numbered_rows import PILL_POINTER, NumberedRows
from tools.eval_rows_transcript import words_from
from tools.rectangle import Rectangle, overlaps
from tools.row import Row
from tools.rows import Rows
from tools.schemas import load_user_row_adjustments

FIXTURE = Path(__file__).parent / "fixtures" / "page01-rows-gold"


def _page01_rows() -> list[Row]:
    """The rows the user's drawn lines make on page-01 — 41 rows, the case
    every placement has to survive."""
    page = Image.new("RGB", (2544, 4642))
    rows = Rows.from_words(words_from(FIXTURE / "words.json"), (page.width, page.height)).adjust(
        load_user_row_adjustments(FIXTURE / "user-row-adjustments.json")["lines"]
    )
    return rows


def _ink(rows: list[Row]) -> list[Rectangle]:
    return [w.rect for row in rows for w in row.word_boxes]


def test_no_number_covers_another_number() -> None:
    """Two numbers on top of each other are two numbers nobody can read: rows 6
    and 7 went unread for exactly that reason, in three separate renders."""
    rows = _page01_rows()
    boxes = NumberedRows._pill_boxes(rows)
    for index, box in enumerate(boxes):
        for other in boxes[index + 1 :]:
            assert not overlaps(box, other), f"numbers at {box} and {other} cover each other"


def test_no_number_covers_the_writing() -> None:
    """Ink under a label is ink the reader cannot see, and the repeats followed
    exactly that: ten of page-01's earlier numbers lay over a neighbouring
    line's writing."""
    rows = _page01_rows()
    boxes = NumberedRows._pill_boxes(rows)
    ink = _ink(rows)
    for box in boxes:
        for word in ink:
            assert not overlaps(box, word), f"number at {box} covers the word at {word}"


def test_every_row_is_numbered_once() -> None:
    """The answer is read against these numbers, so each row carries its own and
    only its own."""
    rows = _page01_rows()
    boxes = NumberedRows._pill_boxes(rows)
    assert len(boxes) == len(rows)
    drawn = NumberedRows.render(Image.new("RGB", (2544, 4642)), rows)
    assert sorted(drawn.numbers.values()) == sorted(range(1, len(rows) + 1))
    assert drawn.rows_drawn() == len(rows)


def test_a_number_sits_beside_its_row_where_there_is_room() -> None:
    """Directly left of its own row is where a number belongs (the review
    surface's own side); the right only when the left is taken."""
    rows = _page01_rows()
    boxes = NumberedRows._pill_boxes(rows)
    beside = 0
    for row, box in zip(rows, boxes, strict=False):
        width = box.width
        left_edge = min((w.rect.x0 for w in row.word_boxes), default=row.band.x0)
        right_edge = max((w.rect.x1 for w in row.word_boxes), default=row.band.x1)
        if abs(box.x0 - (left_edge - PILL_GAP - width)) < 1 or abs(box.x0 - (right_edge + PILL_GAP)) < 1:
            beside += 1
    assert beside >= len(rows) - 3, f"only {beside} of {len(rows)} numbers sit beside their own row"


def test_a_row_with_no_room_either_side_goes_to_the_margin() -> None:
    """A row with writing hard against both its sides: the number goes to the
    margin, which nothing can cover, rather than onto the ink."""
    words = [_word(80, 100, 240, 140), _word(400, 100, 560, 140)]
    rows = [Row(id="seg-1", kind="body", number=1, word_boxes=words, band=Rectangle(80, 100, 560, 140))]
    boxes = NumberedRows._pill_boxes(rows)
    assert len(boxes) == 1
    ink = [w.rect for w in words]
    assert not any(overlaps(boxes[0], word) for word in ink), "the number was left over the writing"


def _word(x0: float, y0: float, x1: float, y1: float):
    from tools.word import Word

    return Word(x0, y0, x1, y1)


def test_ten_rows_never_share_a_number() -> None:
    """Ten stacked rows within a few pixels — the shape that produced every
    failure: ten numbers, ten distinct positions, none overlapping."""
    rows = [
        Row(id=f"seg-{n}", kind="body", number=n, word_boxes=[], band=Rectangle(300, 100 + 8 * n, 900, 140 + 8 * n))
        for n in range(1, 11)
    ]
    boxes = NumberedRows._pill_boxes(rows)
    assert len(boxes) == 10
    for index, box in enumerate(boxes):
        for other in boxes[index + 1 :]:
            assert not overlaps(box, other)


def test_the_bands_hold_every_number_and_all_the_writing() -> None:
    """The strips are cropped to the numbers and the writing: a number outside
    the crop is a number the model never sees, which is how thirteen of them
    went missing."""
    rows = _page01_rows()
    strips = NumberedRows.render_strips(Image.new("RGB", (2544, 4642)), rows, strips=3)
    spread = NumberedRows.numbers_extent(rows)
    ink = _ink(rows)
    for strip in strips:
        assert strip.image.width > 500, "a crop that width cannot hold a row"
        assert strip.numbers, "a band with no numbers is a wasted look"
    assert spread[0] < min(word.x0 for word in ink), "the numbers must reach left of all the writing"
    assert sum(len(strip.numbers) for strip in strips) >= len(rows)


def test_no_number_leaves_its_own_rows_height() -> None:
    """A number level with the wrong row points at the wrong row: the user saw
    38 sitting beside 39. A number that cannot fit beside its row steps OUT
    into the margin, never up or down."""
    rows = _page01_rows()
    boxes = NumberedRows._pill_boxes(rows)
    for row, box in zip(rows, boxes, strict=False):
        centre = (row.band.y0 + row.band.y1) / 2
        pill_centre = (box.y0 + box.y1) / 2
        assert abs(pill_centre - centre) <= 20, (
            f"number {row.number} sits {pill_centre - centre:.0f}px off its row's height"
        )


def test_the_number_points_at_its_own_row() -> None:
    """The pointer is what says which row a number belongs to, so it is drawn on
    the edge the row lies beyond — pointing left at a row on the right is a
    number pointing at nothing."""
    rows = _page01_rows()
    boxes = NumberedRows._pill_boxes(rows)
    for row, box in zip(rows, boxes, strict=False):
        row_centre = (row.band.x0 + row.band.x1) / 2
        pill_centre = (box.x0 + box.x1) / 2
        expected = "right" if pill_centre < row_centre else "left"
        assert NumberedRows.pointer_side(box, row) == expected, (
            f"number {row.number} at x{pill_centre:.0f} points the wrong way at its row (x{row_centre:.0f})"
        )


def test_a_number_carries_its_own_rows_hue() -> None:
    """The pill and the band are the same colour so the pairing can be read by
    colour alone. Darkening by clamping channels shifts the hue and the pair
    stops matching; the hue must survive."""
    rows = _page01_rows()
    for index, row in enumerate(rows):
        band_hue = NumberedRows.hue_of(index)
        red, green, blue = NumberedRows.pill_colour(index)
        pill_hue = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)[0]
        turn = abs(((band_hue - pill_hue) + 0.5) % 1.0 - 0.5)
        assert turn < 0.02, f"row {row.number}: the number's hue is {turn:.3f} of a turn from its band's"


def test_a_number_lands_beside_its_row_inside_a_cut_band() -> None:
    """A band is a crop, so it has an x origin as well as a y one. Taking off
    only the y painted every number ~450px right of its row — over the middle
    of the writing, beside a neighbouring line — which is what made the model
    merge rows 6, 7 and 10 into their neighbours and refuse every band."""
    page = Image.new("RGB", (2544, 4642), (250, 250, 250))
    rows = _page01_rows()
    strips = NumberedRows.render_strips(page, rows, strips=3)
    assert strips, "no strips were rendered"
    seen: set[int] = set()
    for strip in strips:
        for row in rows:
            number = strip.numbers.get(row.id)
            if number is None:
                continue
            seen.add(number)
            assert number == row.number, f"{row.id} is numbered {number}, not {row.number}"
    assert seen == {row.number for row in rows}, "a row is missing from every strip"


def test_a_number_is_painted_at_the_crops_origin_in_its_own_colour() -> None:
    """Two ways to get a number wrong in a band, in one check: painted in page
    coordinates on a cropped canvas (it lands beside another row), and coloured
    by its place in the image rather than its own number (the band it matches
    is the wrong one). Row 28 is wanted because it is neither the first row nor
    in the first band."""
    rows = [
        Row(
            id="seg-28",
            kind="body",
            number=28,
            word_boxes=[_word(600, 100, 900, 140)],
            band=Rectangle(600, 100, 900, 140),
        )
    ]
    canvas = Image.new("RGB", (500, 200), (250, 250, 250))
    drawn = NumberedRows.draw_numbers(canvas, rows, offset_x=200)
    assert drawn.numbers == {"seg-28": 28}
    expected = NumberedRows.pill_colour(27)
    painted = np.nonzero(np.all(np.asarray(canvas) == expected, axis=2))[1]
    assert len(painted), "the number was not painted in its own row's colour"
    box = NumberedRows._pill_boxes(rows)[0]
    gutter_x, pill_right = box.x0 - 200, box.x1 - 200
    assert abs(int(painted.min()) - gutter_x) <= 2, (
        f"the pill starts at x{painted.min()}; its row's gutter in the crop is x{gutter_x}"
    )
    # the pointer reaches PILL_POINTER px further out, toward its row
    assert int(painted.max()) <= pill_right + PILL_POINTER + 2, (
        f"the number reaches x{painted.max()}, past its row's pill at x{pill_right}"
    )
