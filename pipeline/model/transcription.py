"""One transcription response: the text the model read and the per-line
boxes it measured.

The response is the model's own wire record — the JSON format the system
prompt requests (lines with normalized boxes), or the plain-text format a
model that did not follow the instruction answers with — so the class owns
the reading of both.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TranscribedLine:
    """One line of a transcription: its text and the box the model measured for
    it, in the response's NORMALIZED 0-1000 units."""

    text: str
    box: list[float]


@dataclass(frozen=True)
class Transcription:
    """What one vision call read: the transcription text (the .txt content,
    the lines joined with newlines) and the per-line boxes keyed by the line
    index that text's own split uses — None when the model measured none
    (the pipeline then falls back to the detector's association: the
    geometry must come from the model that can READ the cursive, not the rec
    engine that merges and misses its lines)."""

    _BOX_COORDINATE_COUNT = 4  # a box is [x0, y0, x1, y1]

    # A box smaller than a third of the median line height is degenerate: the
    # model's boxes COLLAPSE at the page's bottom edge, and a collapsed box is
    # worse than none — the line falls back to the detector's association.
    _DEGENERATE_BOX_DIVISOR = 3

    text: str
    boxes: dict[int, list[float]] | None = None

    def boxed_lines(self) -> list[TranscribedLine]:
        """This reading's lines as text/box pairs, in reading order. The pairing
        is this class's own invariant: ``from_lines`` builds ``text`` by joining
        one entry per line and keys each box by that entry's position, so every
        key is a valid index into ``text``'s split — a caller reads the pairs
        instead of splitting the text itself, and computes no index that could
        point past the text it indexes. A line the model measured no usable box
        for is absent: its geometry is only the lines it measured."""
        parts = self.text.split("\n")
        return [TranscribedLine(parts[index], box) for index, box in sorted((self.boxes or {}).items())]

    @classmethod
    def from_payload(cls, data: Any, fallback: str) -> Transcription:
        """The reading one parsed model answer holds: the JSON format the
        system prompt requests, or the plain text the model answered with
        when that structure is not there. The boxes are in NORMALIZED
        0-1000 units (the layout pass converts to the image's pixels)."""
        if isinstance(data, dict) and isinstance(data.get("lines"), list):
            lines = cls.from_lines(data["lines"])
            if lines is not None:
                return lines
        return cls(fallback)

    @classmethod
    def from_lines(cls, entries: list[Any]) -> Transcription | None:
        """The transcription from the model's "lines" array — blank lines
        carry no box (the .txt's own split skips them too, so the indexes
        stay aligned). None when an entry is not a usable object — the
        caller falls back to the plain-text form."""
        texts: list[str] = []
        boxes: dict[int, list[float]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                return None
            line = entry.get("text")
            if not isinstance(line, str) or not line.strip():
                continue  # blank lines carry no box — the .txt split skips them too
            index = len(texts)
            texts.append(line)
            box = entry.get("box")
            if (
                isinstance(box, list)
                and len(box) == Transcription._BOX_COORDINATE_COUNT
                and all(isinstance(v, (int, float)) and v == v for v in box)
            ):
                boxes[index] = [float(v) for v in box]
        return cls("\n".join(texts), _drop_degenerate_boxes(boxes) or None)


def _drop_degenerate_boxes(boxes: dict[int, list[float]]) -> dict[int, list[float]]:
    """Drop the model's degenerate boxes — any box smaller than a third of
    the median line height is unusable."""
    if not boxes:
        return boxes
    heights = sorted(y1 - y0 for x0, y0, x1, y1 in boxes.values())
    median_h = heights[len(heights) // 2]
    if median_h > 0:
        boxes = {
            i: [x0, y0, x1, y1]
            for i, (x0, y0, x1, y1) in boxes.items()
            if y1 - y0 >= median_h / Transcription._DEGENERATE_BOX_DIVISOR
        }
    return boxes
