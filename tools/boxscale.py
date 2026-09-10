"""The page's writing scale — measured from the ink, never assumed.

A scanned page gives one quantity directly: the height of its writing (the
median height of its ink shapes). Everything the box detector measures in
absolute terms is a multiple of it, and those multiples are typography:

- a line's baselines vary by at most about the writing's height — that is what
  the writing's height means — so clustering at ~0.7 × height separates lines;
- lines sit about 1.5-1.7 × the writing's height apart in handwriting;
- a word gap is a fraction of the writing's height; a column break is many.

Estimating a page-wide "line pitch" instead was tried and abandoned: on the
first real letter five estimators disagreed wildly (autocorrelation 70px,
baseline differences 34px, ink row bands 260px, row peaks 53px, model selection
25px) against a true spacing of ~63px — because the writing's height approaches
the line spacing there, nothing in the ink separates "another word on this
line" from "the next line". The writing's height does not need that question
answered; it is read straight off the ink.

The line spacing: writing height × a ratio. The ratio comes from the reviewer's
traces when they have drawn enough of them — a trace is a statement about where
a line is — and otherwise from handwriting's typographic default.
"""

from __future__ import annotations

import statistics as st

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
        b - a for a, b in zip(ordered, ordered[1:], strict=False) if TRACE_GAP_BOUNDS[0] < b - a < TRACE_GAP_BOUNDS[1]
    ]


def traced_pitch(traced_baselines: list[float]) -> float | None:
    """The typical spacing between traced lines, or None if too few to tell."""
    if len(traced_baselines) < MIN_TRACED_LINES:
        return None
    spacings = traced_spacings(traced_baselines)
    return st.median(spacings) if spacings else None


def line_ratio(traced_pitch_px: float | None, unit: float) -> float:
    """Line spacing ÷ writing height: measured from the traces when possible."""
    if traced_pitch_px and unit > 0:
        ratio = traced_pitch_px / unit
        if LINE_RATIO_BOUNDS[0] <= ratio <= LINE_RATIO_BOUNDS[1]:
            return ratio
    return LINE_RATIO_DEFAULT


def line_spacing(heights: list[float], traced_baselines: list[float] | None = None) -> float:
    """The page's line spacing in page pixels — the one scale the detector needs."""
    unit = writing_scale(heights)
    return unit * line_ratio(traced_pitch(traced_baselines or []), unit)
