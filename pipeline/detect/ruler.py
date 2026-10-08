"""The page's own ruler: what one length means here, and how it is measured.

Every distance the detector compares is a multiple of the writing's height
(the median height of its ink marks) or of the line spacing that height
implies. A page at another resolution, in another hand, or in print needs no
edits - the multiples are typography, the height is measured.

The Ruler is made from the page's marks (`Ruler.from_marks`); where the CLI
still has the reviewer's traced baselines, their spacing refines the pitch,
and without them the default ratio stands.
"""

from __future__ import annotations

import statistics as st
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pipeline.detect.mark import Mark

SEED_FRACTION = 0.38  # × writing height: baselines this close start one line
REFIT_FRACTION = 0.86  # × writing height: how far a shape may sit from a line
JOIN_FRACTION = 1.78  # × line spacing: the x gap that ends a line-run
STROKE_FRACTION = 2.14  # × writing height: how far a mark's box may exceed its strokes
TOUCH_FRACTION = 0.38  # × writing height: how close a stroke must pass to cover a word

CLUSTER_RATIO = 0.70  # × writing height: a line's own baseline spread
LINE_RATIO_DEFAULT = 1.6  # × writing height: handwriting's line spacing
LINE_RATIO_PRINT = 1.35  # × writing height: print's tighter line spacing
LINE_RATIO_BOUNDS = (1.05, 2.5)  # outside this, a measured ratio is not a line spacing
MIN_TRACED_LINES = 3  # traced lines needed before their spacing means anything
TRACE_GAP_BOUNDS = (15.0, 220.0)  # px: two traced lines closer/further than this are not a pair


def writing_scale(heights: list[float]) -> float:
    """The page's unit: the median height of its ink shapes."""
    return st.median(heights) if heights else 40.0


def traced_spacings(traced_baselines: list[float]) -> list[float]:
    """The spacings between the reviewer's traced lines, nearest pairs only."""
    ordered = sorted(traced_baselines)
    return [
        b - a for a, b in zip(ordered, ordered[1:], strict=False) if TRACE_GAP_BOUNDS[0] <= b - a <= TRACE_GAP_BOUNDS[1]
    ]


def traced_pitch(traced_baselines: list[float]) -> float | None:
    """The typical spacing between traced lines, or None if too few to tell."""
    if len(traced_baselines) < MIN_TRACED_LINES:
        return None
    spacings = traced_spacings(traced_baselines)
    return st.median(spacings) if spacings else None


def line_ratio(traced_pitch_px: float | None, unit: float) -> float:
    """Line spacing ÷ writing height: measured from the traces when possible."""
    if traced_pitch_px is None or unit <= 0:
        return LINE_RATIO_DEFAULT
    ratio = traced_pitch_px / unit
    if not LINE_RATIO_BOUNDS[0] <= ratio <= LINE_RATIO_BOUNDS[1]:
        return LINE_RATIO_DEFAULT
    return ratio


@dataclass
class Ruler:
    """The page's own ruler: what one length means here.

    Every distance the detector compares is a multiple of the writing's height
    (the median height of its ink shapes) or of the line spacing that height
    implies. A page at another resolution, in another hand, or in print needs no
    edits - the multiples are typography, the height is measured.
    """

    unit: float  # the writing's height, in working pixels
    pitch: float  # the line spacing, in working pixels

    @classmethod
    def of(cls, heights: list[float], ratio: float) -> Ruler:
        unit = writing_scale(heights)
        return cls(unit=unit, pitch=unit * ratio)

    @classmethod
    def from_marks(cls, marks: Iterable[Mark], traced_baselines: Sequence[float] = ()) -> Ruler:
        """The page's ruler from its marks: the unit is their median height,
        the pitch the writing's own ratio — refined by the traced lines'
        spacing where the reviewer's indications are known."""
        heights = [mark.height for mark in marks]
        unit = writing_scale(heights)
        return cls(unit=unit, pitch=unit * line_ratio(traced_pitch(list(traced_baselines)), unit))

    @property
    def seed_gap(self) -> float:
        return SEED_FRACTION * self.unit

    @property
    def refit_tol(self) -> float:
        return REFIT_FRACTION * self.unit

    @property
    def join_gap(self) -> float:
        return JOIN_FRACTION * self.pitch

    @property
    def stroke_tol(self) -> float:
        return STROKE_FRACTION * self.unit

    @property
    def touch(self) -> float:
        return TOUCH_FRACTION * self.unit
