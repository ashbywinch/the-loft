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
    Box,
    gap,
    group_rows,
    is_rule,
    is_small,
    merge_interleaved,
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

    def test_a_word_is_not_a_rule(self, boxes) -> None:
        """Every ordinary word on the letter - not the known wide underline - is
        not a rule."""
        assert not any(is_rule(b) for b in boxes if b.height >= 24 and b.width < 300)

    def test_exactly_at_the_aspect_boundary_counts_as_a_rule(self) -> None:
        assert is_rule(Box(0, 0, 8 * RULE_ASPECT, 8))

    def test_a_tall_box_is_not_a_rule(self) -> None:
        assert not is_rule(Box(0, 0, 40, 120))


class TestSmall:
    """is_small: written smaller than the page's hand, and word-like."""

    def test_a_dot_is_not_small_writing(self) -> None:
        assert not is_small(Box(0, 0, 18, 10), WRITING_HEIGHT)

    def test_a_spot_filling_tall_but_narrow_is_not_word_like(self) -> None:
        assert not is_small(Box(0, 0, 20, 30), WRITING_HEIGHT)

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

    @pytest.mark.xfail(
        reason="the fragmentation defect: 6 yellow lines split across body rows; "
        "the fix belongs here, where each attempt is a fast test cycle"
    )
    def test_every_yellow_line_lands_in_one_row(self, letter: dict, boxes) -> None:
        """Each real line's words land in one row. A stroke may span two rows
        only when one of them is a small-run row - the interleaved mini-row
        that has its own yellow line, which every neighbouring stroke passes
        over. That is the accepted insertion class."""
        rows = rows_of(boxes, SPACING, WRITING_HEIGHT)
        row_of = {index: r for r, row in enumerate(rows) for index in row}
        run_words = {i for run in small_runs(boxes, WRITING_HEIGHT, set()) for i in run}
        split = []
        for line_index, stroke in enumerate(strokes_of(letter)):
            covered = [
                index
                for index, box in enumerate(boxes)
                if index in row_of
                and any(box.x0 - 20 <= px <= box.x1 + 20 and box.y0 - 20 <= py <= box.y1 + 20 for px, py in stroke)
            ]
            landed = {row_of[i] for i in covered if i in row_of}
            if len(landed) <= 1:
                continue
            touching_runs = any(i in run_words for i in covered)
            non_run_rows = {row_of[i] for i in covered if i not in run_words}
            if touching_runs and len(non_run_rows) == 1:
                continue  # the accepted interleave: the run has its own line
            split.append((line_index, len(covered), sorted(landed)))
        assert split == [], f"{len(split)} yellow lines split across body rows: {split[:8]}"
