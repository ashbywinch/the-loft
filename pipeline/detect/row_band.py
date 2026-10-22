"""A band of consecutive ink rows: the top and bottom row it spans.

Every band in the detector is this record: a projection run (the rows the
normalised ink shows writing on), a merged run (two runs a thin descender
touched), the broad band the baseline walk measures through. A start and an
end, inclusive, and nothing else — named, because a bare (start, end) pair
cannot say which end is which at the call site.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RowBand:
    """A band of consecutive ink rows, `top` and `bottom` inclusive."""

    top: int
    bottom: int

    @property
    def length(self) -> int:
        """How many rows the band spans."""
        return self.bottom - self.top + 1

    def extend_to(self, bottom: int) -> RowBand:
        """This band widened down to `bottom` — the merge of a run that
        touched it."""
        return RowBand(self.top, bottom)
