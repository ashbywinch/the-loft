"""What one band's call could see of that band: its size, its numbers, its read.

The eval draws a band's row numbers itself, so a band's numbers are known
exactly: ``rows`` is what was drawn on the image and ``read`` which of them the
model's answer named. A band the model cannot read at all is a band too tall —
that is the whole measurement.

A record with no wire: the eval's ``report.json`` holds the per-height
summaries (``BandSummary``), and a band's own answer is written beside its
render; this pair of lists is what the summary is counted from, in hand.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BandReading:
    """One band's call: the band's pixel size, the numbers on it, the numbers
    the answer named, and what the call took."""

    height: int
    width: int
    rows: list[int]
    read: list[int]
    seconds: float
