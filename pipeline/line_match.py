"""A detector line matched to a VLM transcription line.

The association's record: the VLM line's text and index, the detector's
box and recognized text, the recognition's score, the words each reader
produced, and how the box was found ("content" = the rec read the line's
text; "positional" = the order-based fallback). It never reaches the wire —
it is the in-memory working record the anchor resolution reads — so it
carries no serialization of its own.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.detection_word import DetectionWord


@dataclass(frozen=True)
class LineMatch:
    """A detector line matched to a VLM transcription line."""

    vlm: str
    vlm_index: int
    box: list[float] | None
    rec_text: str
    rec_score: float
    rec_words: list[str]
    det_words: list[DetectionWord]
    box_source: str
    orientation: int

    def confirms(self) -> bool:
        """Did the rec READ the line's text there? Only a content match
        confirms a line (the rec read the same words)."""
        return self.box_source == "content"

    def rec_word_set(self) -> set[str]:
        """The rec's words — the comparison side of the rec-vs-VLM
        agreement the positional fallback and the orientation both judge."""
        return set(self.rec_words)
