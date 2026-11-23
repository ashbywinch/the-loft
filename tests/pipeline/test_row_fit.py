"""A mark's rows read against the fitted lines — the cut's proposals.

The marks here are built row by row, so the geometry is the test's own: a
mark's rows are known, which line each row is nearest is known, and the
segment the fit proposes follows from them. The page-01 fixtures
(`tests/pipeline/test_reader.py`) pin the same object's output on real ink;
this suite pins the rules it applies.
"""

from __future__ import annotations

import numpy as np

from pipeline.detect.line import Line
from pipeline.detect.mark import Mark
from pipeline.detect.row_fit import RowFit, nearest_line
from pipeline.detect.segment import Segment


def _mark(rows: list[tuple[int, int, int]], mark_id: str = "m") -> Mark:
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
    """A solid block of rows — a word's ink at full width."""
    return [(y, x0, x1) for y in range(y0, y1 + 1)]


def _strokes(y0: int, y1: int, x0: int = 0, width: int = 10, gap: int = 10) -> list[tuple[int, int, int]]:
    """Two strokes per row — letter ink, not a band: no row's run spans most
    of the mark's width, so the underline rule leaves these rows alone."""
    first = [(y, x0, x0 + width - 1) for y in range(y0, y1 + 1)]
    second = [(y, x0 + width + gap, x0 + 2 * width + gap - 1) for y in range(y0, y1 + 1)]
    return first + second


TWO_LINES = [Line(a=0.0, b=100.0), Line(a=0.0, b=140.0)]


# -- which line a piece of ink belongs to -----------------------------------


def test_a_mark_sits_on_the_line_it_is_nearest() -> None:
    fit = RowFit(TWO_LINES)
    assert fit.line_of(_mark(_block(80, 99, 0, 45))) == 0
    assert fit.line_of(_mark(_block(140, 159, 0, 45))) == 1


def test_nearest_line_answers_in_the_index_space_of_the_list_it_was_given() -> None:
    """The index names a row of the list given, never of some wider fit."""
    mark = _mark(_block(140, 159, 0, 45))
    assert nearest_line(mark, [Line(a=0.0, b=140.0)]) == 0
    assert nearest_line(mark, TWO_LINES) == 1


def test_the_fit_holds_the_lines_it_was_made_with() -> None:
    """A fit is a reading of the lines as they stood: the caller's list is
    copied, so a later re-fit cannot move a cut's proposals under it."""
    lines = [Line(a=0.0, b=100.0)]
    fit = RowFit(lines)
    lines.append(Line(a=0.0, b=160.0))
    lines[0] = Line(a=0.0, b=0.0)
    assert isinstance(fit.lines, tuple)
    assert [line.b for line in fit.lines] == [100.0]


# -- the segmentation the rows propose --------------------------------------


def test_a_run_of_rows_on_one_line_is_one_segment() -> None:
    fit = RowFit([Line(a=0.0, b=100.0)])
    assert fit.segments(_mark(_block(80, 99, 0, 45))) == [Segment(line=0, y0=80, y1=99)]


def test_rows_within_the_merge_distance_belong_to_the_same_piece() -> None:
    """`ROW_MERGE` is the gap that still reads as one piece of ink: a 2-row
    break is one piece, a 4-row break is two (a stroke's tip, not a cut)."""
    fit = RowFit([Line(a=0.0, b=100.0)])
    merged = _mark(_strokes(80, 81) + _strokes(83, 84))
    apart = _mark(_strokes(80, 81) + _strokes(85, 86))
    assert fit.segments(merged) == [Segment(line=0, y0=80, y1=84)]
    assert fit.segments(apart) == [Segment(line=0, y0=80, y1=81), Segment(line=0, y0=85, y1=86)]


def test_the_fit_cuts_where_the_ink_moves_to_another_line() -> None:
    """A mark spanning two lines is two segments — its upper ink on one, its
    lower ink on the next, the cut between them."""
    fit = RowFit(TWO_LINES)
    shape = _mark(_block(80, 120, 0, 45) + _block(121, 140, 60, 105))
    assert fit.segments(shape) == [Segment(line=0, y0=80, y1=120), Segment(line=1, y0=121, y1=140)]


def test_a_mark_on_three_lines_is_cut_where_the_ink_moves_each_time() -> None:
    """Three blocks on three fitted lines: the cut is proposed at both
    changes, not only at the first — the row loop keeps iterating after a cut."""
    fit = RowFit([Line(a=0.0, b=100.0), Line(a=0.0, b=140.0), Line(a=0.0, b=180.0)])
    shape = _mark(_block(80, 90, 0, 45) + _block(130, 139, 60, 105) + _block(170, 179, 120, 165))
    assert fit.segments(shape) == [
        Segment(line=0, y0=80, y1=90),
        Segment(line=1, y0=130, y1=139),
        Segment(line=2, y0=170, y1=179),
    ]


def test_a_cut_through_one_continuous_band_of_ink_is_not_a_cut() -> None:
    """Both cut rows carry long runs that overlap column-wise: the fit sliced
    a band of ink mid-body, and the pieces stay one segment (the waist rule,
    user 2026-09-13: the bug through widening ink)."""
    fit = RowFit(TWO_LINES)
    shape = _mark(_strokes(80, 140))
    assert fit.segments(shape) == [Segment(line=0, y0=80, y1=140)]


# -- the underline's band ---------------------------------------------------


def test_a_band_of_full_width_rows_is_cut_into_its_own_segment() -> None:
    """Rows whose runs span most of the mark's width are a stroke's ink, not
    writing: the segment they fall inside is split around them so the strip
    can classify and remove the band (the underline welded under its words)."""
    fit = RowFit([Line(a=0.0, b=100.0)])
    shape = _mark(_block(80, 99, 0, 9) + _block(100, 105, 0, 45) + _block(106, 120, 0, 9))
    assert fit.segments(shape) == [
        Segment(line=0, y0=80, y1=99),
        Segment(line=0, y0=100, y1=105),
        Segment(line=0, y0=106, y1=120),
    ]


def test_one_wide_row_is_a_strokes_ink_not_a_band() -> None:
    """A single stray long row is a letter's stroke: a band is at least two
    rows, so the segment is left whole."""
    fit = RowFit([Line(a=0.0, b=100.0)])
    shape = _mark(_block(80, 99, 0, 9) + _block(100, 100, 0, 45) + _block(101, 120, 0, 9))
    assert fit.segments(shape) == [Segment(line=0, y0=80, y1=120)]


# -- the gap between stacked words ------------------------------------------


def _gapped(flank: int = 40, waist: int = 2) -> Mark:
    """A mark whose rows run wide, thin, wide again — a gap in the ink."""
    return _mark(_block(80, 99, 0, flank - 1) + _block(100, 117, 10, 10 + waist - 1) + _block(118, 144, 0, flank - 1))


def test_a_deep_gap_between_two_lines_is_the_boundary() -> None:
    """The deepest thin row is the boundary, and the two sides sit on
    different fitted lines."""
    fit = RowFit([Line(a=0.0, b=100.0), Line(a=0.0, b=130.0)])
    assert fit.gap(_gapped()) == 100  # the waist's first row


def test_a_gap_inside_one_line_is_a_words_letter_space() -> None:
    """The two sides must sit on different fitted lines: a gap within one
    line is the space between letters, never a cut."""
    fit = RowFit([Line(a=0.0, b=100.0)])
    assert fit.gap(_gapped()) is None


def test_a_shallow_gap_is_no_gap() -> None:
    """Strict: a row only a little thinner than its flanks is not a boundary."""
    fit = RowFit([Line(a=0.0, b=100.0), Line(a=0.0, b=130.0)])
    assert fit.gap(_gapped(waist=15)) is None


def test_a_gap_between_scraps_of_ink_cuts_nothing() -> None:
    """With no substantial flank the row is a thin mark's own waist, not a
    gap between two words."""
    fit = RowFit([Line(a=0.0, b=100.0), Line(a=0.0, b=130.0)])
    assert fit.gap(_gapped(flank=2, waist=1)) is None
