"""Cutting a writing's marks into words — the reader's cut step.

A mark is one connected piece of ink, and the writing is cut where that ink
stops being one word. Every judgement here belongs to the page, not to the
strip: the candidate boundaries come from the rows' fit to the fitted lines
(`RowFit`), and each boundary is settled by the writing's own geometry — the
word-shape test, the line classification, a continuation in the mark beneath,
and the gap a shape's rows show. A cut's pieces are the words, and a streak the
cut frees is not writing: it leaves the marks and joins the strip.
"""

from __future__ import annotations

from pipeline.detect.cut_verdict import CutVerdict
from pipeline.detect.line import Line
from pipeline.detect.mark import Components, Ink, Mark
from pipeline.detect.row_fit import RowFit
from pipeline.detect.ruler import Ruler
from pipeline.detect.segment import Segment
from pipeline.detect.word_groups import WordGroups


def piece_between(shape: Mark, segment: Segment) -> Mark:
    """The piece a segment (line, y0, y1) would become."""
    return shape.piece(_rows_ink(shape, segment.y0, segment.y1), segment.line, segment.y0)


class WordCut:
    """One writing's marks, cut where its geometry says a mark is two words.

    The words are every boundary a mark may hold, and the tests that judge it:
    whether a strip of ink is one word, two words or a line is answered by the
    page's own rows, ruler and other marks, never by the strip alone. The gap
    cut uses the word test with its two waived bars named at the call site."""

    def __init__(self, marks: list[Mark], lines: list[Line], scale: Ruler) -> None:
        self.marks = marks
        self.lines = lines
        self.scale = scale
        self.fit = RowFit(lines)

    def words(self) -> list[Mark]:
        """The marks, cut where the writing's geometry says each holds more
        than one word. A continuation's mark is absorbed, not boxed apart."""
        out: list[Mark] = []
        absorbed: set[str] = set()
        for shape in self.marks:
            if shape.id in absorbed:
                continue
            word_groups = self._word_groups(shape)
            absorbed.update(continuation.id.split("_")[0] for continuation in word_groups.continuations.values())
            out.extend(self._word_pieces(shape, word_groups.segments, word_groups.continuations))
        return out

    @staticmethod
    def _word_pieces(shape: Mark, groups: list[Segment], continuations: dict[int, Mark]) -> list[Mark]:
        """The pieces the groups become, each continuation's ink joined to its
        group and the line pieces left for the strip."""
        pieces: list[Mark] = []
        for index, segment in enumerate(groups):
            ink = _rows_ink(shape, segment.y0, segment.y1)
            continuation = continuations.get(index)
            if continuation is not None:
                ink = ink.joined_with(Ink.of_shape(continuation))
            if ink.size < Components.SHAPE_MIN_AREA // 2:
                continue
            piece = shape.piece(ink, segment.line, segment.y0)
            if piece.is_streak:
                continue
            pieces.append(piece)
        return pieces

    def _word_groups(self, shape: Mark) -> WordGroups:
        """The shape's row groups after every boundary verdict — the fit's
        cuts, the lines' ceding, the continuation split at the shape's bottom.
        A single fused group is split at its deep gap when the pieces are
        words' worths of ink."""
        segments = self.fit.segments(shape)
        groups: list[Segment] = []
        continuations: dict[int, Mark] = {}
        for segment in segments:
            if not groups:
                groups.append(segment)
                continue
            verdict = self._is_a_cut(shape, groups[-1], segment)
            if not verdict.cut:
                groups[-1] = Segment(groups[-1].line, groups[-1].y0, segment.y1)
                continue
            if verdict.continuation is not None:
                continuations[len(groups)] = verdict.continuation
            groups.append(segment)
        if len(groups) == 1:
            split_y = self.fit.gap(shape)
            if split_y is not None and self._gap_pieces_are_words(shape, groups[0], split_y):
                groups = [
                    Segment(groups[0].line, groups[0].y0, split_y),
                    Segment(groups[0].line, split_y + 1, groups[0].y1),
                ]
        return WordGroups(segments=groups, continuations=continuations)

    def _gap_pieces_are_words(self, shape: Mark, group: Segment, split_y: int) -> bool:
        """The two pieces a gap split makes must be tall enough to hold
        letters and joined up — the gap proves the pieces are separate, but
        it does not make a sliver or a pair of ascenders into a word (user:
        never 'just two ascenders'). The
        thin and flat checks are waived: they exist to spot fragments at
        fit-proposed cuts, and a gap needs no such guess — it admits narrow
        words like 'of' and flat crossed-out rows."""
        upper = shape.piece(_rows_ink(shape, group.y0, split_y), group.line, group.y0)
        lower = shape.piece(_rows_ink(shape, split_y + 1, group.y1), group.line, split_y + 1)
        return upper.is_word_shaped(self.scale.unit, waive_band=True, waive_width=True) and lower.is_word_shaped(
            self.scale.unit, waive_band=True, waive_width=True
        )

    def _is_a_cut(self, shape: Mark, above: Segment, below: Segment) -> CutVerdict:
        """Whether the boundary between two of the shape's segments is a real
        cut: both sides word-shaped, or one side a rule/underline that cedes.
        Fragments refuse the cut — except at the shape's bottom edge, where
        the word's ink continues in the mark beneath it (a word split across
        two components by a crossing line). Such a continuation legitimizes
        the cut and is returned so its mark can be absorbed into the piece
        (user 2026-09-18: box 334, 'two words with a gap and a bridge')."""
        upper = piece_between(shape, above)
        lower = piece_between(shape, below)
        if upper.classify_line([lower], [upper, lower], self.scale.unit) or lower.classify_line(
            [upper], [upper, lower], self.scale.unit
        ):
            return CutVerdict(cut=True, continuation=None)
        if upper.is_word_shaped(self.scale.unit) and lower.is_word_shaped(self.scale.unit):
            return CutVerdict(cut=True, continuation=None)
        if below.y1 == shape.y1:
            continuation = self._continuation(shape, below)
            if continuation is not None:
                ink = _rows_ink(shape, below.y0, below.y1).joined_with(Ink.of_shape(continuation))
                if shape.piece(ink, below.line, below.y0).is_word_shaped(self.scale.unit):
                    return CutVerdict(cut=True, continuation=continuation)
        return CutVerdict(cut=False, continuation=None)

    def _continuation(self, shape: Mark, below: Segment) -> Mark | None:
        """The mark directly beneath the shape whose ink is the same word's
        rest: its ink starts exactly at the shape's bottom edge, it sits on
        the boundary's own fitted line, and it is NOT a word on its own (a
        full word below is a different word and must not be absorbed). The
        word leans, so no column overlap."""
        candidates = [
            other
            for other in self.marks
            if other is not shape
            and other.y0 == shape.y1
            and other.y1 > shape.y1
            and self.fit.line_of(other) == below.line
            and not other.is_word_shaped(self.scale.unit)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda mark: mark.y0)


def _rows_ink(shape: Mark, y0: int, y1: int) -> Ink:
    """The shape's ink on rows y0..y1 inclusive."""
    ys, xs = shape.pix
    keep = (ys >= y0) & (ys <= y1)
    return Ink(ys[keep], xs[keep])
