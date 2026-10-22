"""A page's line association: the matches and the lines nobody claimed.

The association is ONE outcome — the pairs the content matcher found, and
the detector lines left over (the positional fallback fills the boxless
transcription lines from the leftovers, and the rest become the layout's
extras) — so the two lists travel as one named record instead of a pair
every caller unpacks by position.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.detection import Detection
from pipeline.line_match import LineMatch


@dataclass(frozen=True)
class Association:
    """The matcher's outcome: the matches and the unclaimed detections."""

    matches: list[LineMatch]
    unmatched: list[Detection]
