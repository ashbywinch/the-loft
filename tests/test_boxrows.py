"""Tests for the box-input row grouping (tools/boxrows.py).

Each rule is tested on its own with real boxes measured from the letter
(the fixture holds word boundaries, which carry no PII), and the whole
grouping is validated against the yellow lines the reviewer drew - the
reality check. No image, no strokes in the grouping's input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.boxrows import (
    RULE_ASPECT,
    WRITING_FLOOR,
    Box,
    gap,
    group_rows,
    is_rule,
    is_small,
    is_vertical,
    merge_interleaved,
    row_boxes,
    rows_of,
    small_runs,
)

FIXTURE = Path(__file__).parent / "fixtures" / "page01.json"
WRITING_HEIGHT = 42.0  # page px: the letter's words
SPACING = 67.6  # page px between its lines


@pytest.fixture(scope="module")
def letter() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def boxes(letter: dict) -> list[Box]:
    return [Box(w["x0"], w["y0"], w["x1"], w["y1"]) for w in letter["words"]]


def strokes_of(letter: dict) -> list[list[tuple[float, float]]]:
    width, height = letter["page"]["width"], letter["page"]["height"]
    return [[(x * width, y * height) for x, y in s] for s in letter["strokes"]]


class TestRule:
    """is_rule: far wider than tall means an underline, not a word."""

    def test_the_letters_own_underline_is_a_rule(self, boxes) -> None:
        underline = min(boxes, key=lambda b: b.cy if b.width > 600 and b.cy < 2300 else 1e9)
        assert underline.width > 600
        assert is_rule(underline)

    def test_an_ordinary_wide_word_is_not_a_rule(self, boxes) -> None:
        """Every word-shaped component (wide for its height) is not a rule."""
        assert not any(is_rule(b) for b in boxes if b.height >= 24 and 0.6 * b.height <= b.width < 300)

    def test_exactly_at_the_aspect_boundary_counts_as_a_rule(self) -> None:
        assert is_rule(Box(0, 0, 8 * RULE_ASPECT, 8))

    def test_a_tall_box_is_not_a_rule(self) -> None:
        assert not is_rule(Box(0, 0, 40, 120))


class TestVertical:
    """is_vertical: taller than the line spacing - not a word on one horizontal line."""

    def test_an_ordinary_wide_word_is_not_vertical(self, boxes) -> None:
        assert not any(
            is_vertical(b, SPACING, WRITING_HEIGHT) for b in boxes if b.height <= 60 and b.width >= 0.8 * b.height
        )

    def test_a_component_taller_than_the_spacing_is_vertical(self) -> None:
        assert is_vertical(Box(0, 0, 60, 90), SPACING, WRITING_HEIGHT)

    def test_a_component_shorter_than_the_spacing_is_not_vertical(self) -> None:
        assert not is_vertical(Box(0, 0, 60, 60), SPACING, WRITING_HEIGHT)

    def test_exactly_the_spacing_is_not_vertical(self) -> None:
        assert not is_vertical(Box(0, 0, 60, SPACING), SPACING, WRITING_HEIGHT)

    def test_a_tall_narrow_component_is_vertical_ink(self) -> None:
        """34x52, aspect 0.65: the member that stretched row 24's box into
        the next row's words - a vertical mark, not a word on a horizontal
        line."""
        assert is_vertical(Box(0, 0, 34, 52), SPACING, WRITING_HEIGHT)

    def test_a_wide_enough_component_is_not_tall_narrow(self) -> None:
        assert not is_vertical(Box(0, 0, 60, 52), SPACING, WRITING_HEIGHT)


class TestSmall:
    """is_small: written smaller than the page's hand, and word-like."""

    def test_a_dot_is_not_small_writing(self) -> None:
        assert not is_small(Box(0, 0, 18, 10), WRITING_HEIGHT)

    def test_a_narrow_small_word_is_still_small_writing(self) -> None:
        """A small word like 'to' is 20x26 - narrower than tall; the aspect
        guard wrongly broke run chains on exactly these words (line 5's small
        text never formed its own line). Size is the test, not aspect."""
        assert is_small(Box(0, 0, 20, 26), WRITING_HEIGHT)

    def test_a_comma_is_not_small_writing(self) -> None:
        """Small in both directions: a comma (10x20) is a mark of the same
        hand, not another hand's writing."""
        assert not is_small(Box(0, 0, 10, 20), WRITING_HEIGHT)
        assert not is_small(Box(0, 0, 8, 10), WRITING_HEIGHT)

    def test_a_full_height_word_is_not_small(self) -> None:
        assert not is_small(Box(0, 0, 46, 44), WRITING_HEIGHT)

    def test_smaller_word_like_writing_is_small(self) -> None:
        assert is_small(Box(0, 0, 94, 36), WRITING_HEIGHT)


class TestGroupRows:
    """group_rows: by centre, a gap beyond half the spacing starts a row."""

    def test_no_boxes_makes_no_rows(self) -> None:
        assert group_rows([], SPACING) == []

    def test_one_box_makes_one_row(self) -> None:
        assert group_rows([Box(0, 0, 40, 20)], SPACING) == [[0]]

    def test_boxes_within_half_the_spacing_share_a_row(self) -> None:
        boxes = [Box(0, 0, 40, 20), Box(100, 20, 140, 40)]
        assert group_rows(boxes, SPACING) == [[0, 1]]

    def test_a_gap_beyond_half_the_spacing_starts_a_new_row(self) -> None:
        boxes = [Box(0, 0, 40, 20), Box(100, 40, 140, 60)]
        assert len(group_rows(boxes, SPACING)) == 2

    def test_boxes_are_ordered_across_the_row(self) -> None:
        boxes = [Box(300, 0, 340, 20), Box(0, 5, 40, 25)]
        assert group_rows(boxes, SPACING) == [[1, 0]]


class TestMergeInterleaved:
    """merge_interleaved: two rows that interleave are one line."""

    def test_interleaving_rows_merge(self) -> None:
        boxes = [Box(0, 0, 40, 20), Box(200, 10, 240, 30)]
        rows = merge_interleaved([[0], [1]], boxes, SPACING)
        assert rows == [[0, 1]]

    def test_rows_a_full_spacing_apart_stay_separate(self) -> None:
        boxes = [Box(0, 0, 40, 20), Box(200, 68, 240, 88)]
        assert len(merge_interleaved([[0], [1]], boxes, SPACING)) == 2

    def test_disjoint_rows_never_see_each_other(self) -> None:
        boxes = [Box(0, 0, 40, 20), Box(200, 400, 240, 420)]
        assert len(merge_interleaved([[0], [1]], boxes, SPACING)) == 2


class TestSmallRuns:
    """small_runs: three or more small word-like boxes in a chain are a run."""

    def test_three_chained_small_boxes_are_a_run(self) -> None:
        boxes = [Box(0, 0, 50, 30), Box(60, 2, 110, 32), Box(120, 4, 170, 34)]
        assert small_runs(boxes, WRITING_HEIGHT, set()) == [[0, 1, 2]]

    def test_two_chained_small_boxes_are_not_a_run(self) -> None:
        boxes = [Box(0, 0, 50, 30), Box(60, 2, 110, 32)]
        assert small_runs(boxes, WRITING_HEIGHT, set()) == []

    def test_a_far_away_small_box_does_not_join_the_run(self) -> None:
        boxes = [Box(0, 0, 50, 30), Box(60, 2, 110, 32), Box(120, 4, 170, 34), Box(4000, 0, 4050, 30)]
        assert small_runs(boxes, WRITING_HEIGHT, set()) == [[0, 1, 2]]

    def test_a_dot_between_words_does_not_start_a_run(self) -> None:
        boxes = [Box(0, 0, 10, 8), Box(20, 0, 30, 8), Box(40, 0, 50, 8)]
        assert small_runs(boxes, WRITING_HEIGHT, set()) == []


class TestRowsOf:
    """rows_of: the whole grouping, end to end, on boxes alone."""

    def test_no_row_box_holds_another_rows_words(self, boxes) -> None:
        """The invariant the eye caught on the page: a row's box must cover its
        own words and no other row's - the box the reviewer sees is one line.

        (A row's union is legitimately about a spacing plus a word's height
        tall - that is what a line of writing measures - so the test is not the
        box's height but whose words its area contains.)
        """
        rows = rows_of(boxes, SPACING, WRITING_HEIGHT)
        row_boxes_output = row_boxes(rows, boxes, SPACING)
        for row_index, row_box in enumerate(row_boxes_output):
            mine = set(rows[row_index])
            in_some_row = {index for row in rows for index in row}

            # a box HOLDS a foreign word when half its area is inside: at the
            # edge, where a tall member of one row reaches toward the next, the
            # overlap is the allowed class; half the word inside is a claim
            def share(word: Box, box: Box) -> float:
                ix = max(0.0, min(word.x1, box.x1) - max(word.x0, box.x0))
                iy = max(0.0, min(word.y1, box.y1) - max(word.y0, box.y0))
                area = (word.x1 - word.x0) * (word.y1 - word.y0)
                return ix * iy / area if area else 0.0

            # the accepted interleave, both ways: small writing (asides, the
            # P.S. block) sits between the body rows and has its own lines;
            # small words may sit inside any box, and a small-run row's box may
            # reach a neighbour's word - the dense block interleaves, and that
            # is the design, not a stack (its own yellow line resolves it)
            run_row = all(is_small(boxes[i], WRITING_HEIGHT) for i in rows[row_index])
            foreign = [
                index
                for index in in_some_row
                if index not in mine
                and boxes[index].height >= WRITING_FLOOR * WRITING_HEIGHT
                and not run_row
                and share(boxes[index], row_box) >= 0.5
            ]
            assert not foreign, (
                f"row {row_index}'s box also covers words of {len(foreign)} other row(s): {sorted(foreign)[:6]}"
            )

    def test_a_rule_is_no_row(self) -> None:
        boxes = [Box(0, 0, 40, 44), Box(200, 0, 240, 44), Box(0, 60, 800, 68)]
        rows = rows_of(boxes, SPACING, WRITING_HEIGHT)
        assert [2] not in rows

    def test_a_small_run_is_its_own_row(self) -> None:
        boxes = [
            Box(0, 0, 46, 44),
            Box(60, 0, 106, 44),
            Box(0, 67, 50, 97),
            Box(60, 69, 110, 101),
            Box(120, 71, 170, 105),
        ]
        rows = rows_of(boxes, SPACING, WRITING_HEIGHT)
        assert rows[-1] == [2, 3, 4]

    def test_gap_measures_whitespace_not_centres(self) -> None:
        assert gap(Box(0, 0, 40, 20), Box(50, 0, 90, 20)) == pytest.approx(10.0)
        assert gap(Box(0, 0, 40, 20), Box(30, 0, 70, 20)) == 0.0


class TestReality:
    """The reality check: the reviewer drew one yellow line per real line of
    writing. A row grouping is right when each line's words land in one row."""

    def test_a_yellow_line_never_scatters_to_distant_rows(self, letter: dict, boxes) -> None:
        """A real line's words land in consecutive rows: slope-cut fragments sit
        adjacent, never scattered across the page. (Reuniting the adjacent
        pairs is the slope grouping - a separate, recorded defect; scattering
        to distant rows would be a grouping bug and is pinned here.)"""
        rows = rows_of(boxes, SPACING, WRITING_HEIGHT)
        row_of = {index: r for r, row in enumerate(rows) for index in row}
        run_words = {i for run in small_runs(boxes, WRITING_HEIGHT, set()) for i in run}
        scattered = []
        for line_index, stroke in enumerate(strokes_of(letter)):
            covered = [
                index
                for index, box in enumerate(boxes)
                if index in row_of
                and any(box.x0 - 20 <= px <= box.x1 + 20 and box.y0 - 20 <= py <= box.y1 + 20 for px, py in stroke)
            ]
            # the runs are interleaved asides with their own lines: a stroke may
            # pass over them, so only the body words measure the scatter
            landed = sorted({row_of[i] for i in covered if i not in run_words})
            if landed and landed != list(range(landed[0], landed[-1] + 1)):
                scattered.append((line_index, landed))
        assert scattered == [], f"lines scattered to non-consecutive rows: {scattered[:6]}"
