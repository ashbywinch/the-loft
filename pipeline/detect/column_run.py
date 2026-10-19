"""One mask row's run of ink: its columns, and the union-find node it holds.

`Components` walks the mask row by row; each row contributes the runs of ink
it shows, and every run is welded to the runs it overlaps in the row above.
The run is a record: the columns it spans (`start`..`end`, inclusive) and the
union-find node its piece is being built under.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnRun:
    """One mask row's run of ink: `start`..`end` columns, and its node."""

    start: int
    end: int
    id: int
