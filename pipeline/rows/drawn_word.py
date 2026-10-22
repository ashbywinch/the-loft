"""One word as the render draws it: its page index, its box, and its lines.

The drawing walks the page's words, not the boxes it was handed: `drawn_geometry`
zips each box with the geometry that will be drawn for it. Three things travel
together — the word's index ON THE PAGE (a strip's boxes are a subset of the
page's words, so the override keyed by page index still matches), the box, and
the measured-or-overridden lines (None: the word draws no lines at all — a
refused word, or a box with almost no ink). Naming the triple keeps the index
and the box from being read in the wrong order, the class of bug a bare tuple
hides.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pipeline.detect.mark import WordGeometry


@dataclass(frozen=True)
class DrawnWord:
    """One word as it is drawn: its page index, its box, and the lines for it."""

    page_index: int
    box: Sequence[float]
    geometry: WordGeometry | None
