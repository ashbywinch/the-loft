"""One segment of a mark's ink: the fitted line it sits on, and its rows.

A mark holding more than one word is cut into segments — consecutive rows of its
ink that belong to one fitted line, `y0`..`y1` inclusive. The cut proposes them,
the boundary verdicts merge or keep them, and each surviving segment becomes a
piece (or is stripped as a line). The segment is a record with NO wire: it is the
reader's own measurement of the mark, never persisted.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    """One segment of a mark's ink: its fitted line's index, and its rows inclusive."""

    line: int
    y0: int
    y1: int
