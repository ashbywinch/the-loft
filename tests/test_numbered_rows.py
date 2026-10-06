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

from pathlib import Path

from PIL import Image

from document.numbered_rows import PILL_INSET as PILL_GAP
from document.numbered_rows import NumberedRows
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
