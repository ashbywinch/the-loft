"""Cutting a writing's marks into words — the reader's cut step.

The marks are built row by row, so each boundary the cut judges is the
test's own construction: a mark whose ink moves to another line is two
words, and a word split across two components is joined rather than boxed
apart. `tests/pipeline/test_reader.py` pins the same object on page-01's
real ink; this suite pins the rules it applies.
"""

from __future__ import annotations

import numpy as np

from pipeline.detect.line import Line
from pipeline.detect.mark import Mark
from pipeline.detect.ruler import Ruler
from pipeline.detect.segment import Segment
from pipeline.detect.word_cut import WordCut


def _mark(rows: list[tuple[int, int, int]], mark_id: str) -> Mark:
    """A mark from (y, x0, x1) row spans — every column of each span inked."""
    ys: list[int] = []
    xs: list[int] = []
    for y, x0, x1 in rows:
        for x in range(x0, x1 + 1):
            ys.append(y)
            xs.append(x)
    pix = (np.asarray(ys, dtype=np.int64), np.asarray(xs, dtype=np.int64))
    return Mark(
        x0=float(min(xs)),
        y0=float(min(ys)),
        x1=float(max(xs)),
        y1=float(max(ys)),
        baseline=float(max(ys)),
        waistline=float(min(ys)),
        area=float(len(ys)),
        cx=(float(min(xs)) + float(max(xs))) / 2,
        pix=pix,
        line=0,
        id=mark_id,
    )


def _block(y0: int, y1: int, x0: int, x1: int) -> list[tuple[int, int, int]]:
    return [(y, x0, x1) for y in range(y0, y1 + 1)]


LINES = [Line(a=0.0, b=100.0), Line(a=0.0, b=140.0)]
SCALE = Ruler(unit=40.0, pitch=64.0)


# -- the cut ----------------------------------------------------------------


def test_a_mark_spanning_two_lines_is_two_words() -> None:
    """One word on the upper line, one on the next, welded into one mark: the
    fit's cut is a word boundary, and both pieces are word-shaped."""
    shape = _mark(_block(80, 120, 0, 45) + _block(121, 140, 60, 105), "w")
    words = WordCut([shape], LINES, SCALE).words()
    assert [(word.y0, word.y1, word.line) for word in words] == [(80.0, 120.0, 0), (121.0, 140.0, 1)]


def test_a_word_on_one_line_is_one_word() -> None:
    words = WordCut([_mark(_block(80, 99, 0, 45), "one")], [Line(a=0.0, b=100.0)], SCALE).words()
    assert [(word.y0, word.y1) for word in words] == [(80.0, 99.0)]


def test_the_cut_holds_the_marks_it_was_made_with() -> None:
    """The cut is a reading of the marks as they stood: the caller's lists
    are copied, so a later re-fit cannot change what a boundary was judged
    on."""
    marks = [_mark(_block(80, 120, 0, 45) + _block(121, 140, 60, 105), "w")]
    lines = list(LINES)
    cut = WordCut(marks, lines, SCALE)
    marks.clear()
    lines.clear()
    assert len(cut.words()) == 2


# -- the continuation: a word split across two components --------------------


def _split_shape() -> Mark:
    """A word whose lower half is a narrow flat piece — not a word on its
    own, so the cut looks for the mark beneath that continues it."""
    return _mark(_block(80, 99, 0, 45) + _block(140, 150, 60, 69), "w")


def _one_line_split_shape() -> Mark:
    """The same narrow bottom piece, on the upper line: the boundary's own
    line is line 0."""
    return _mark(_block(80, 99, 0, 45) + _block(100, 110, 60, 69), "w")


def _below() -> Segment:
    return Segment(line=1, y0=140, y1=150)


def test_a_continuation_must_start_exactly_at_the_shapes_bottom_edge() -> None:
    """The rule is the docstring's: a mark one row lower is a different
    component, not the same word's rest."""
    shape = _split_shape()
    at_edge = _mark(_block(150, 160, 60, 105), "cont")
    one_lower = _mark(_block(151, 161, 60, 105), "cont")
    assert WordCut([shape, at_edge], LINES, SCALE)._continuation(shape, _below()) is at_edge
    assert WordCut([shape, one_lower], LINES, SCALE)._continuation(shape, _below()) is None


def test_a_full_word_beneath_is_a_different_word_not_a_continuation() -> None:
    """A word-shaped mark under the shape is its own word: absorbing it would
    swallow a neighbour."""
    shape = _split_shape()
    full_word = _mark(_block(150, 175, 60, 105), "other")
    assert full_word.is_word_shaped(SCALE.unit)
    assert WordCut([shape, full_word], LINES, SCALE)._continuation(shape, _below()) is None


def test_a_continuation_must_sit_on_the_boundarys_own_line() -> None:
    """The same word's rest is on the line the boundary is on; ink at the edge
    that has moved to the next line is a different row's word."""
    shape = _one_line_split_shape()
    below = Segment(line=0, y0=100, y1=110)
    same_line = _mark(_block(110, 118, 60, 105), "cont")
    wrong_line = _mark(_block(110, 124, 60, 105), "cont")
    assert not same_line.is_word_shaped(SCALE.unit) and not wrong_line.is_word_shaped(SCALE.unit)
    assert WordCut([shape, same_line], LINES, SCALE)._continuation(shape, below) is same_line
    assert WordCut([shape, wrong_line], LINES, SCALE)._continuation(shape, below) is None


def test_the_split_words_rest_is_joined_to_its_piece_and_not_boxed_apart() -> None:
    """The narrow lower piece is not word-shaped; the continuation beneath
    makes the joined piece a word, and the continuation leaves the marks."""
    shape = _split_shape()
    continuation = _mark(_block(150, 160, 60, 105), "cont")
    words = WordCut([shape, continuation], LINES, SCALE).words()
    assert [word.id for word in words] == ["w_80", "w_140"]
    assert words[1].y1 == 160.0  # the continuation's ink is inside the lower word
