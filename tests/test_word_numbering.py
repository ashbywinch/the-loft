"""The numbered renderer's collision logic (tools/word_numbering.py).

The contract is the plan's: a chip never covers another word's box or another
chip, the placement order is corner → above → below → left → right → remaining
perimeter positions, and a word whose positions are all taken is reported,
not silently overlapped. The chip's footprint is its number's text bbox plus
the ring pad, never beyond MAX_CHIP.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from tools.word_numbering import (
    CHIP_GAP,
    EDGE_PAD,
    MAX_CHIP,
    PALETTE,
    UNPLACED,
    Chip,
    _base_font,
    candidates,
    chip_extent,
    numbered_order,
    palette_luminances,
    place_chips,
    unplaced,
)

A = (100.0, 100.0, 200.0, 200.0)  # a word the size of the tests' world


def _expected(box: tuple[float, float, float, float], text: str) -> tuple[float, float, float, float]:
    """The corner chip rect for a word: its text's footprint at the base
    font, placed at the top-left corner — the placement the test asserts."""
    width, height = chip_extent(text, _base_font(box))
    return (box[0] - CHIP_GAP - width, box[1] - CHIP_GAP - height, box[0] - CHIP_GAP, box[1] - CHIP_GAP)


def test_an_isolated_word_gets_the_top_left_corner() -> None:
    chips = place_chips([A], numbered_order([A]))
    assert len(chips) == 1
    chip = chips[0]
    assert chip.verdict == "corner"
    assert chip.rect == _expected(A, "1")
    assert chip.render_id == 1
    assert chip.colour == PALETTE[0]


def test_a_blocked_corner_moves_the_chip_above() -> None:
    # a word sitting where this word's corner chip would go forces the
    # chip to the first free direction: above
    neighbour = (40.0, 40.0, 90.0, 90.0)  # overlaps A's corner position
    boxes = [A, neighbour]
    chips = {chip.render_id: chip for chip in place_chips(boxes, numbered_order(boxes))}
    # reading order: the neighbour (centre-y 65) precedes A (centre-y 150)
    assert chips[2].verdict == "above"  # A: corner blocked -> above
    assert chips[1].verdict == "corner"  # the neighbour's own corner is free


def test_every_placed_chip_is_collision_free() -> None:
    """A dense cluster: no placed chip may reach another word's box OR
    another placed chip."""
    rng = np.random.default_rng(7)
    boxes = []
    for _ in range(40):
        x = float(rng.integers(0, 800))
        y = float(rng.integers(0, 600))
        boxes.append((x, y, x + float(rng.integers(20, 120)), y + float(rng.integers(14, 60))))
    order = numbered_order(boxes)
    chips = place_chips(boxes, order)
    placed = [chip for chip in chips if chip.verdict != UNPLACED]
    for i, chip in enumerate(placed):
        rect = chip.rect
        for other in boxes:
            if other is boxes[order[chip.render_id - 1]]:
                continue
            c0, c1, c2, c3 = rect
            b0, b1, b2, b3 = other
            assert c2 + EDGE_PAD <= b0 or c0 - EDGE_PAD >= b2 or c3 + EDGE_PAD <= b1 or c1 - EDGE_PAD >= b3, (
                f"chip {chip.render_id} ({rect}) covers a word box ({other})"
            )
        for j, peer in enumerate(placed):
            if j <= i:
                continue
            c0, c1, c2, c3 = rect
            p0, p1, p2, p3 = peer.rect
            assert c2 + EDGE_PAD <= p0 or c0 - EDGE_PAD >= p2 or c3 + EDGE_PAD <= p1 or c1 - EDGE_PAD >= p3, (
                f"chips {chip.render_id} ({rect}) and {peer.render_id} ({peer.rect}) overlap"
            )


def test_a_word_every_position_taken_is_reported_not_overlapped() -> None:
    """Each placement position at every font size blocked by a neighbour's
    box: the centre word must report UNPLACED and no placed chip may cover
    it."""
    centre = (300.0, 300.0, 340.0, 340.0)
    # the smallest chip (the minimum font's footprint) still leaves every
    # position taken, so a blocker on each min footprint blocks every larger
    # size too
    width, height = chip_extent("1", 8.0)  # the minimum footprint, any number
    blockers = [rect for _, rect in candidates(centre, width, height)]
    boxes = [centre] + blockers
    chips = place_chips(boxes, numbered_order(boxes))
    centre_chip = next(chip for chip in chips if chip.verdict == UNPLACED)
    assert centre_chip is not None
    for chip in chips:
        if chip.verdict == UNPLACED:
            continue
        rect = chip.rect
        c0, c1, c2, c3 = rect
        b0, b1, b2, b3 = centre
        assert c2 + EDGE_PAD <= b0 or c0 - EDGE_PAD >= b2 or c3 + EDGE_PAD <= b1 or c1 - EDGE_PAD >= b3, (
            f"chip {chip.render_id} ({rect}) covers the centre word"
        )


def test_a_chip_never_exceeds_the_max_size() -> None:
    """MAX_CHIP caps every chip side, however large the text or the font."""
    width, height = chip_extent("999", 500.0)
    assert width <= MAX_CHIP and height <= MAX_CHIP, f"chip {width:.0f}x{height:.0f} exceeds {MAX_CHIP}"
    chips = place_chips([A], numbered_order([A]))
    placed = chips[0]
    assert placed.rect[2] - placed.rect[0] <= MAX_CHIP and placed.rect[3] - placed.rect[1] <= MAX_CHIP


def test_a_chips_bbox_matches_its_text_footprint() -> None:
    """A placed chip's rect equals its number's bbox at its font size, plus
    the ring pad — the bounding box matches the font size (within rounding)."""
    rng = np.random.default_rng(3)
    boxes = []
    for _ in range(20):
        x = float(rng.integers(0, 600))
        y = float(rng.integers(0, 400))
        boxes.append((x, y, x + float(rng.integers(30, 150)), y + float(rng.integers(18, 70))))
    for chip in place_chips(boxes, numbered_order(boxes)):
        if chip.verdict == UNPLACED:
            continue
        width, height = chip_extent(str(chip.render_id), chip.font_size)
        assert abs((chip.rect[2] - chip.rect[0]) - width) <= 1.0, f"chip {chip.render_id} width mismatch"
        assert abs((chip.rect[3] - chip.rect[1]) - height) <= 1.0, f"chip {chip.render_id} height mismatch"


def test_numbering_order_is_reading_order() -> None:
    boxes = [
        (0.0, 100.0, 40.0, 130.0),  # second row, left
        (0.0, 0.0, 40.0, 30.0),  # first row, left
        (50.0, 0.0, 90.0, 30.0),  # first row, right
        (50.0, 100.0, 90.0, 130.0),  # second row, right
    ]
    order = numbered_order(boxes)
    # rows top-to-bottom, words left-to-right
    assert [boxes[i] for i in order] == [
        (0.0, 0.0, 40.0, 30.0),
        (50.0, 0.0, 90.0, 30.0),
        (0.0, 100.0, 40.0, 130.0),
        (50.0, 100.0, 90.0, 130.0),
    ]


def test_the_palette_is_distinct_in_colour_and_grayscale() -> None:
    assert len(set(PALETTE)) == len(PALETTE), "palette colours must be pairwise distinct"
    lum = palette_luminances()
    # at least ten distinct grey levels: an adjacent pair may coincide, a
    # row of neighbours must not
    distinct = len(np.unique(np.round(lum, 1)))
    assert distinct >= 10, f"only {distinct} distinct grey levels in the palette"


def test_unplaced_reports_the_ids() -> None:
    assert unplaced([]) == []
    chips = [Chip(render_id=3, rect=(0, 0, 1, 1), colour=(0, 0, 0), verdict=UNPLACED, font_size=8.0)]
    assert unplaced(chips) == [3]


def test_render_numbered_draws_without_error() -> None:
    from tools.word_numbering import render_numbered

    page = Image.new("RGB", (400, 300), (250, 250, 250))
    boxes = [(50.0, 50.0, 150.0, 100.0), (200.0, 180.0, 320.0, 240.0)]
    image, chips = render_numbered(page, (0.0, 0.0, 400.0, 300.0), boxes, scale=1.0)
    assert image.size == (400, 300)
    assert len(chips) == 2
    assert {chip.render_id for chip in chips} == {1, 2}
