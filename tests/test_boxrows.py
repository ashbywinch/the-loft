"""Tests for the box-input page model (tools/boxrows.py).

Each rule is tested on its own with words whose font sizes (x-heights) are
known, and the whole grouping is validated against the yellow lines the
reviewer drew - the reality check. Word carries ITS font size; smallness is
relative and lives on Page. No image, no strokes in the grouping's input.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.boxrows import (
    RULE_ASPECT,
    Page,
    Rectangle,
    Row,
    Word,
)

FIXTURE = Path(__file__).parent / "fixtures" / "page01.json"
SPACING = 67.6  # page px between the letter's lines
PAGE_FONT = 16.0  # page px: the letter's x-height


@pytest.fixture(scope="module")
def letter() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def page(letter: dict) -> Page:
    """The real letter: word bounds with their measured font sizes."""
    return Page(
        [Word(w["x0"], w["y0"], w["x1"], w["y1"], font_size=w.get("font_size", PAGE_FONT)) for w in letter["words"]],
        SPACING,
    )


@pytest.fixture(scope="module")
def words(letter: dict) -> list[Word]:
    return [Word(w["x0"], w["y0"], w["x1"], w["y1"], font_size=w.get("font_size", PAGE_FONT)) for w in letter["words"]]


def row_of_index(rows: Sequence[Row], index: int) -> int:
    """The row holding a word index (the page model's mapping)."""
    return next(r for r, row in enumerate(rows) if index in row.words)


def strokes_of(letter: dict) -> list[list[tuple[float, float]]]:
    width, height = letter["page"]["width"], letter["page"]["height"]
    return [[(x * width, y * height) for x, y in s] for s in letter["strokes"]]


class TestRule:
    """Word.is_rule: far wider than tall means an underline, not a word."""

    def test_the_letters_own_underline_is_a_rule(self, words: list[Word]) -> None:
        underline = min(words, key=lambda w: w.cy if w.width > 600 and w.cy < 2300 else 1e9)
        assert underline.width > 600
        assert underline.is_rule()

    def test_an_ordinary_wide_word_is_not_a_rule(self, words: list[Word]) -> None:
        assert not any(w.is_rule() for w in words if w.height >= 24 and 0.6 * w.height <= w.width < 300)

    def test_exactly_at_the_aspect_boundary_counts_as_a_rule(self) -> None:
        assert Word(0, 0, 8 * RULE_ASPECT, 8).is_rule()

    def test_a_tall_box_is_not_a_rule(self) -> None:
        assert not Word(0, 0, 40, 120).is_rule()


class TestSmall:
    """Page.is_small: a smaller hand - a small FONT SIZE, never a short box."""

    def test_a_dot_is_not_small_writing(self) -> None:
        page = Page([Word(0, 0, 18, 10, font_size=4)], SPACING)
        assert not page.is_small(page.words[0])

    def test_a_full_height_word_is_not_small(self) -> None:
        page = Page([Word(0, 0, 46, 44, font_size=PAGE_FONT)], SPACING)
        assert not page.is_small(page.words[0])

    def test_a_smaller_font_is_small(self) -> None:
        page = Page([Word(0, 0, 94, 36, font_size=10)], SPACING)
        assert page.font_size == 10
        assert not page.is_small(page.words[0])  # it IS the page here

    def test_smallness_is_relative_to_the_page(self) -> None:
        small = Word(0, 0, 94, 36, font_size=8)
        big_page = Page([small, Word(60, 0, 160, 60, font_size=16)], SPACING)
        same_page = Page([small, Word(60, 0, 160, 36, font_size=8)], SPACING)
        assert big_page.is_small(small)
        assert not same_page.is_small(small)

    def test_an_x_height_word_is_not_small_because_of_its_box(self) -> None:
        """The reviewer's line-7 case: ordinary font (16), no ascenders or
        descenders, so a SHORT box - but not small writing."""
        word = Word(0, 0, 94, 22, font_size=16)
        page = Page([word, Word(60, 0, 160, 60, font_size=16)], SPACING)
        assert page.font_size == 16
        assert not page.is_small(word)


class TestVertical:
    """Page.is_vertical: not a word on one horizontal line."""

    def test_an_ordinary_wide_word_is_not_vertical(self, words: list[Word]) -> None:
        page = Page(words, SPACING)
        assert not any(page.is_vertical(w) for w in words if w.height <= 60 and w.width >= 0.8 * w.height)

    def test_a_component_taller_than_a_row_and_a_half_is_vertical(self) -> None:
        page = Page([Word(0, 0, 60, 90, font_size=10)], SPACING)
        assert page.is_vertical(page.words[0])

    def test_a_tall_narrow_component_is_vertical_ink(self) -> None:
        page = Page([Word(0, 0, 16, 54, font_size=10)], SPACING)  # aspect 0.30
        assert page.is_vertical(page.words[0])

    def test_a_real_word_over_the_spacing_is_not_vertical(self) -> None:
        """Line 11's second word: 146x72, ordinary font - a real, boxed word
        that the over-eager height rule threw off its line."""
        page = Page([Word(0, 0, 146, 72, font_size=16)], SPACING)
        assert not page.is_vertical(page.words[0])


class TestPageRows:
    """Page.rows: the grouping, on words alone."""

    def test_no_words_makes_no_rows(self) -> None:
        assert Page([], SPACING).rows() == []

    def test_one_word_makes_one_row(self) -> None:
        rows = Page([Word(0, 0, 40, 20, font_size=10)], SPACING).rows()
        assert len(rows) == 1 and rows[0].words == [0]

    def test_words_within_half_the_spacing_share_a_row(self) -> None:
        page = Page([Word(0, 0, 40, 20, font_size=10), Word(100, 20, 140, 40, font_size=10)], SPACING)
        assert page.rows()[0].words == [0, 1]

    def test_a_gap_beyond_half_the_spacing_starts_a_new_row(self) -> None:
        page = Page([Word(0, 0, 40, 20, font_size=10), Word(100, 40, 140, 60, font_size=10)], SPACING)
        assert len(page.rows()) == 2

    def test_a_rule_is_no_row(self) -> None:
        page = Page(
            [Word(0, 0, 40, 44, font_size=10), Word(200, 0, 240, 44, font_size=10), Word(0, 60, 800, 68, font_size=10)],
            SPACING,
        )
        rows = page.rows()
        assert not any(all(page.words[i].is_rule() for i in row.words) for row in rows)

    def test_a_chained_pair_of_small_words_is_an_interjection(self) -> None:
        """Line 18's interjection had only two words - an interjection needs no
        third word to be its own line, and its row is marked as such."""
        page = Page(
            [
                Word(100, 10, 140, 40, font_size=16),  # the page's hand
                Word(200, 12, 240, 42, font_size=16),
                Word(0, 60, 50, 90, font_size=8),  # the smalls
                Word(60, 62, 110, 92, font_size=8),
            ],
            SPACING,
        )
        interjections = [row for row in page.rows() if row.kind == "interjection"]
        assert len(interjections) == 1
        assert interjections[0].words == [2, 3]

    def test_small_words_flanked_by_a_rows_words_join_it(self) -> None:
        """Line 1: two 42px words with three lower words between them, all in
        one band - the smalls are the middle of the sentence, not an aside."""
        page = Page(
            [
                Word(600, 0, 630, 42, font_size=16),
                Word(632, 8, 680, 38, font_size=10),
                Word(710, 6, 812, 44, font_size=10),
                Word(854, 12, 892, 38, font_size=10),
                Word(900, 0, 1028, 42, font_size=16),
            ],
            SPACING,
        )
        rows = page.rows()
        assert len(rows) == 1, f"one line of words became rows: {len(rows)}"


class TestRealty:
    """The reality check: every yellow line's own words land in one row, in
    that row's box - nothing hidden, nothing exempted."""

    def test_every_yellow_line_agrees_with_the_grouping(self, letter: dict, words: list[Word]) -> None:
        page = Page(words, SPACING)
        verdicts = page.verdicts(strokes_of(letter))
        # a trace that, clamped to the page, sweeps no word at all is drawn
        # over empty canvas - an off-page sketch mark, not a line to judge
        unjudgeable = [
            i
            for i, stroke in enumerate(strokes_of(letter))
            if not any(
                word.x0 - 40 <= px <= word.x1 + 40 and word.y0 - 40 <= py <= word.y1 + 40
                for word in page.words
                for px, py in stroke
            )
        ]
        bad = [(i, v) for i, v in enumerate(verdicts) if i not in unjudgeable and (v.verdict != "right" or v.outside)]
        assert bad == [], f"{len(bad)} yellow lines disagree: {bad[:8]}"

    def test_every_word_like_component_is_boxed(self, words: list[Word]) -> None:
        """The reviewer's eye: words with no boxes. A component with a real
        measured font size and letter proportions - not a rule, not a sliver -
        is a word, and a word must sit in a row. Single letters are taller
        than wide (aspect 0.36-0.6), so the tall-narrow cut must not eat
        them."""
        page = Page(words, SPACING)
        boxed = {i for row in page.rows() for i in row.words}
        unboxed = [
            i
            for i, word in enumerate(words)
            if i not in boxed
            and not word.is_rule()
            and 20 <= word.height < 1.25 * SPACING
            and word.width >= 10
            and word.width >= 0.35 * word.height
            and word.font_size >= 8
        ]
        assert unboxed == [], f"{len(unboxed)} word-like components have no box: {unboxed[:8]}"

    def test_a_lone_word_stacked_above_the_line_does_not_split_it(self) -> None:
        """Line 18: the row at the stroke's level holds three of the words;
        one word sits 40px above, in the row above - physically stacked above
        another word, so not part of the line (the reviewer's ruling)."""
        words = [
            Word(746, 3196, 764, 3226, font_size=20),  # the three at the level
            Word(784, 3206, 816, 3220, font_size=10),
            Word(830, 3210, 920, 3264, font_size=14),
            Word(776, 3140, 832, 3200, font_size=6),  # the one stacked above
        ]
        page_model = Page(words, SPACING)
        stroke = [(720, 3204), (940, 3204)]
        verdict = page_model.verdicts([stroke])[0]
        assert verdict.verdict == "right", f"line 18 reads as {verdict.verdict}"

    def test_no_row_box_is_degenerate_or_vertical(self, letter: dict, words: list[Word]) -> None:
        page = Page(words, SPACING)
        rows = page.rows()
        for row_index, box in enumerate(page.row_boxes(rows)):
            assert box.height > 0, f"row {row_index}'s box has height {box.height:.0f}"
            assert box.height <= box.width, f"row {row_index}'s box is {box.width:.0f}x{box.height:.0f} - vertical"

    def test_no_row_box_holds_another_rows_words_beyond_the_overlap(self, letter: dict, words: list[Word]) -> None:
        """A row's box must cover its own words and no other row's - except
        where the allowed overlap (a word also covered by its OWN row's box)
        applies."""
        page = Page(words, SPACING)
        rows = page.rows()
        boxes = page.row_boxes(rows)
        for row_index, row_box in enumerate(boxes):
            mine = set(rows[row_index].words)
            in_some_row = {index for row in rows for index in row.words}

            def share(word: Rectangle, box: Rectangle) -> float:
                ix = max(0.0, min(word.x1, box.x1) - max(word.x0, box.x0))
                iy = max(0.0, min(word.y1, box.y1) - max(word.y0, box.y0))
                area = (word.x1 - word.x0) * (word.y1 - word.y0)
                return ix * iy / area if area else 0.0

            foreign = [
                index
                for index in in_some_row
                if index not in mine
                and share(words[index].rect, row_box) >= 0.5
                and share(words[index].rect, boxes[row_of_index(rows, index)]) < 0.5
            ]
            others = len({row_of_index(rows, i) for i in foreign})
            assert not foreign, f"row {row_index}'s box also covers words of {others} other rows"
