"""A mark's deepest gap: how deep it is, and the row it sits at.

`Writing._gap_row` cuts a single fused group at the row whose run is thinnest
against its flanks — the boundary between stacked words or crossed-out rows. The
depth is a ratio (the row's run ÷ the flanking ink), so 1.0 means "no gap at
all"; the row is the ink row the cut would run at.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Gap:
    """The deepest gap in a mark's ink: its `depth` (run ÷ flank) and its row."""

    depth: float
    row: int
