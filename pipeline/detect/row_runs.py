"""A mark's ink rows, and each row's longest run of ink.

The gap rule reads the runs: a row whose run is a deep local minimum against its
flanks is a boundary between stacked words or crossed-out rows. The rows and
their runs are measured together — the run of a row is meaningless without the
rows it belongs to — so they travel together.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RowRuns:
    """A mark's ink rows, ascending, and each row's longest run in columns."""

    rows: list[int]
    runs: dict[int, int]
