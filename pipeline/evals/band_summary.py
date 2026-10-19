"""One band height measured: the bands it made, and how much of them was read.

The measurement behind the band sizing: each height is tried once through the
production render and prompt, and the numbers the model read back are counted —
the tallest height whose bands come back fully read is the limit the renderer
sizes bands by. ``numbers_missed`` is the numbers drawn but never named, which
is the failure the height is rejected for.

Its wire is the eval's ``report.json``: a list of these summaries, one per
height tried, in the order they were tried — ``to_dict`` writes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BandSummary:
    """One height's pass: the bands it made, the numbers read and missed, and
    what the whole pass took."""

    max_height: int
    bands: int
    band_height: int
    band_width: int
    rows: int
    numbers_read: int
    numbers_missed: list[int]
    bands_with_no_number: int
    seconds: float

    def to_dict(self) -> dict[str, Any]:
        """The summary as the report.json entry — one per height tried."""
        return {
            "max_height": self.max_height,
            "bands": self.bands,
            "band_height": self.band_height,
            "band_width": self.band_width,
            "rows": self.rows,
            "numbers_read": self.numbers_read,
            "numbers_missed": self.numbers_missed,
            "bands_with_no_number": self.bands_with_no_number,
            "seconds": self.seconds,
        }
