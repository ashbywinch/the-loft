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
from PIL import Image, ImageDraw

from document.numbered_rows import PILL_INSET as PILL_GAP
from document.numbered_rows import PILL_POINTER, NumberedRows
from document.rectangle import Rectangle, overlaps
from document.row import Row
from document.schemas import load_user_row_adjustments
from pipeline.rows.rows import Rows
from pipeline.transcribe.transcripts import words_from

FIXTURE = Path(__file__).parent.parent / "fixtures" / "page01-rows-gold"


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
    from document.word import Word

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
    strips = NumberedRows.render_strips(Image.new("RGB", (2544, 4642)), rows, max_band_height=800)
    spread = NumberedRows.numbers_extent(rows)
    ink = _ink(rows)
    for strip in strips:
        assert strip.image.width > 500, "a crop that width cannot hold a row"
        assert strip.numbers, "a band with no numbers is a wasted look"
    assert spread[0] < min(word.x0 for word in ink), "the numbers must reach left of all the writing"
    assert sum(len(strip.numbers) for strip in strips) >= len(rows)


def test_no_number_leaves_the_end_of_the_line_it_stands_beside() -> None:
    """A number level with the wrong row points at the wrong row: the user saw
    38 sitting beside 39. It is now level with the END of its own line that it
    stands beside — the leftmost word's centre for a number on the left, the
    rightmost word's for one on the right — because a line of handwriting rises
    and falls and the band's middle can be a word's height from the end the
    pointer touches."""
    rows = _page01_rows()
    boxes = NumberedRows._pill_boxes(rows)
    for row, box in zip(rows, boxes, strict=False):
        # "right" means the number's pointer faces right, i.e. the row is to the
        # RIGHT of it: the number stands beside the row's LEFT end
        stands_beside_left_end = NumberedRows.pointer_side(box, row) == "right"
        end = NumberedRows.end_centre(row, left_end=stands_beside_left_end)
        pill_centre = (box.y0 + box.y1) / 2
        assert abs(pill_centre - end) <= 2, (
            f"number {row.number} sits {pill_centre - end:.0f}px off the end of its line"
        )


def test_a_line_that_rises_and_falls_puts_its_number_at_the_end() -> None:
    """The whole point of standing level with the end: on a ragged line, the
    band's centre is between the two ends and belongs to neither, so a number
    there reads as the row above or below at the one place that matters."""
    ragged = Row(
        id="seg-1",
        kind="body",
        number=1,
        word_boxes=[_word(200, 100, 300, 140), _word(600, 260, 700, 300)],
        band=Rectangle(200, 100, 700, 300),
    )
    # a neighbour's writing fills the gap on the left, so the number must go right
    blocker = Row(
        id="seg-2",
        kind="body",
        number=2,
        word_boxes=[_word(100, 100, 190, 140)],
        band=Rectangle(100, 100, 190, 140),
    )
    boxes = NumberedRows._pill_boxes([ragged, blocker])
    chip = (boxes[0].y0 + boxes[0].y1) / 2
    right_end = NumberedRows.end_centre(ragged, left_end=False)
    middle = (ragged.band.y0 + ragged.band.y1) / 2
    assert abs(chip - right_end) <= 2, f"the number sits at {chip:.0f}, not at its line's right end {right_end:.0f}"
    assert abs(chip - middle) > 20, "the number is at the middle of the line, which is neither end"


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


def test_the_chip_paints_the_colour_its_rows_band_shows() -> None:
    """The number and its row have to read as ONE colour, and matching the hue
    is not enough: on the rendered sheet the bands sit at saturation 0.06-0.19 /
    value 0.90-0.98, and a chip at full saturation and half brightness is 4-10x
    away — "they don't actually match" (user). The paper here is cream, not
    white: a chip that recomputes the wash instead of sampling the band comes
    out ~20 units off on paper, and this is the check that catches it."""
    from pipeline.rows.render import render_rows

    paper = (247, 243, 232)
    rows = [
        Row(
            id="seg-1",
            kind="body",
            number=1,
            word_boxes=[_word(100, 100, 400, 140)],
            band=Rectangle(100, 100, 400, 140),
        )
    ]
    tinted = render_rows(Image.new("RGB", (600, 200), paper), rows)
    box = NumberedRows._pill_boxes(rows)[0]
    chip_xy = (int(box.y0) + 4, int(box.x0) + 4)
    band_px = np.asarray(tinted)[120, 250].astype(int)
    chip_px = np.asarray(NumberedRows.draw_numbers(tinted, rows).image)[chip_xy].astype(int)
    assert np.abs(band_px - chip_px).max() <= 4, (
        f"the number is painted {tuple(chip_px)} where its row's band is {tuple(band_px)} on paper {paper}"
    )


def test_no_part_of_a_number_is_painted_inside_a_word_box() -> None:
    """The chip, its pointer and its leader are one drawn thing, and none of it
    may land on the writing. The pointer reached a fixed 14px whatever the
    drawing was doing, so with the number beside the END of its line it painted
    8px past the 6px inset — onto the first letters of the row ("very slightly
    overlapping the writing sometimes", user).

    Pixels, not arithmetic: the words here carry ink of a colour no chip uses,
    so any chip-coloured pixel inside a word box is the chip's own."""
    paper = (247, 243, 232)
    rows = [
        Row(
            id="seg-1",
            kind="body",
            number=1,
            word_boxes=[_word(120, 100, 400, 140), _word(420, 100, 700, 140)],
            band=Rectangle(120, 100, 700, 140),
        )
    ]
    page = Image.new("RGB", (800, 240), paper)
    for word in rows[0].word_boxes:
        ImageDraw.Draw(page).rectangle((int(word.x0), int(word.y0), int(word.x1), int(word.y1)), fill=(60, 60, 60))
    drawn = np.asarray(NumberedRows.draw_numbers(page, rows).image).astype(int)
    for number_index in (0,):
        chip_ink = np.array(NumberedRows.digit_colour(number_index))
        hits = np.nonzero(np.abs(drawn - chip_ink).max(axis=2) <= 20)
        inside = [
            (int(y), int(x))
            for y, x in zip(*hits, strict=True)
            if any(w.x0 <= x <= w.x1 and w.y0 <= y <= w.y1 for w in rows[0].word_boxes)
        ]
        assert not inside, f"the number is painted on the writing at {inside[:5]}"


def test_the_chip_ignores_ink_under_the_row() -> None:
    """The background is sampled where NO writing is, so what the row's own box
    contains cannot reach the chip.

    Sampling the row's box was the earlier rule and it did catch ink: on
    page-01, 31 of 41 rows have an ink-dark pixel at a sampled point, and row 11
    — one word box, its centre on a stroke — had its chip painted ink. This
    draws the writing SOLID BLACK and demands the same chip either way."""
    from pipeline.rows.render import render_rows

    paper = (247, 243, 232)
    boxes = [_word(100, 100, 400, 140)]
    quiet = Row(id="seg-1", kind="body", number=1, word_boxes=boxes, band=Rectangle(100, 100, 400, 140))
    inked_page = Image.new("RGB", (600, 200), paper)
    ImageDraw.Draw(inked_page).rectangle((100, 100, 400, 140), fill=(20, 18, 16))
    inked = Row(id="seg-1", kind="body", number=1, word_boxes=boxes, band=Rectangle(100, 100, 400, 140))
    plain_chip = np.asarray(
        NumberedRows.draw_numbers(render_rows(Image.new("RGB", (600, 200), paper), [quiet]), [quiet]).image
    )
    inked_chip = np.asarray(NumberedRows.draw_numbers(render_rows(inked_page, [inked]), [inked]).image)
    box = NumberedRows._pill_boxes([quiet])[0]
    xy = (int(box.y0) + 4, int(box.x0) + 4)
    assert (plain_chip[xy] == inked_chip[xy]).all(), (
        f"the chip changed with ink under the row: {tuple(plain_chip[xy])} quiet vs {tuple(inked_chip[xy])} inked"
    )


def test_a_number_lands_beside_its_row_inside_a_cut_band() -> None:
    """A band is a crop, so it has an x origin as well as a y one. Taking off
    only the y painted every number ~450px right of its row — over the middle
    of the writing, beside a neighbouring line — which is what made the model
    merge rows 6, 7 and 10 into their neighbours and refuse every band."""
    page = Image.new("RGB", (2544, 4642), (250, 250, 250))
    rows = _page01_rows()
    strips = NumberedRows.render_strips(page, rows, max_band_height=800)
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
    paper = (250, 250, 250)
    canvas = Image.new("RGB", (500, 200), paper)
    drawn = NumberedRows.draw_numbers(canvas, rows, offset_x=200)
    assert drawn.numbers == {"seg-28": 28}
    expected = NumberedRows.pill_colour(27, paper)
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


def test_a_page_of_two_rows_gets_one_band_holding_both() -> None:
    """A page has one fewer gap than it has rows, so the default three bands
    over a two-row page indexed past its cuts — an IndexError the read stage
    would meet on a postcard or a fragment. The bands are the gaps that exist,
    and every row is numbered exactly once."""
    rows = [
        Row(
            id="seg-1",
            kind="body",
            number=1,
            word_boxes=[_word(100, 100, 300, 140)],
            band=Rectangle(100, 100, 300, 140),
        ),
        Row(
            id="seg-2",
            kind="body",
            number=2,
            word_boxes=[_word(100, 400, 300, 440)],
            band=Rectangle(100, 400, 300, 440),
        ),
    ]
    strips = NumberedRows.render_strips(Image.new("RGB", (600, 600), (255, 255, 255)), rows)
    assert len(strips) == 1, f"a two-row page was cut into {len(strips)} bands"
    assert sorted(n for strip in strips for n in strip.numbers.values()) == [1, 2]


def test_the_band_count_follows_the_writings_height() -> None:
    """Bands are sized by the tallest band the model reads at full resolution,
    not by a fixed count: a postcard gets one band, a tall page as many as its
    writing needs. Measured — the whole writing on one image (2360px) lost the
    bottom eight row numbers; at the safe height every number was read."""
    page = Image.new("RGB", (600, 4000), (255, 255, 255))

    def rows_over(height: float, count: int) -> list[Row]:
        step = height / count
        return [
            Row(
                id=f"seg-{i}",
                kind="body",
                number=i,
                word_boxes=[_word(100, 100 + (i - 1) * step, 300, 140 + (i - 1) * step)],
                band=Rectangle(100, 100 + (i - 1) * step, 300, 140 + (i - 1) * step),
            )
            for i in range(1, count + 1)
        ]

    short = NumberedRows.render_strips(page, rows_over(500, 2), max_band_height=856)
    assert len(short) == 1, "a page shorter than one band was cut up anyway"

    # 3400px wants 4 bands by height, but 4 of them leave one at 1360px — cuts
    # can only fall in the rows' gaps — so the count climbs to 5, one per gap
    tall = NumberedRows.render_strips(page, rows_over(3400, 5), max_band_height=856)
    assert len(tall) == 5, f"the fewest bands that all fit is 5, got {len(tall)}"
    assert max(band.image.height for band in tall) <= 856 + 60, "a band came out taller than the readable height"
