"""A page's text line as the detection stage hands it over.

The stage's output shape: the box in the oriented image's pixels, the
recognized text, the recognition's score, the per-word boxes the detector
measured, and (once a pass has run) the orientation the text was read at.
It is a named shape, not a bare map: every consumer reads these fields by
name, and the layout's association, admission and rotation all speak it.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from pipeline.detection_word import DetectionWord


class Detection(TypedDict):
    """A text line + its box, as the detection stage produces it."""

    box: list[float]
    text: str
    score: float
    words: list[DetectionWord]
    orientation: NotRequired[int]
