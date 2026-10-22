"""One line of the model's transcription and the box it measured.

The ``page.vlm.json`` sidecar's line record: the transcription's own line of
text plus its box in the model's NORMALIZED 0-1000 frame (the layout pass
converts to the image's pixels). The HTR stage writes the sidecar and the
layout's VLM-box loader reads it back, so the record is named once and both
sides speak it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BOX_COORDINATE_COUNT = 4  # a box is [x0, y0, x1, y1]


@dataclass(frozen=True)
class TranscriptionLine:
    """One transcribed line and the box the model measured for it."""

    text: str
    box: list[float]

    @classmethod
    def of(cls, raw: Any) -> TranscriptionLine | None:
        """The line one sidecar entry holds — None when it carries no
        usable box: a truncated or NaN box anchors nothing, and a reader
        must never adopt one (the model's list is free-form)."""
        if not isinstance(raw, dict):
            return None
        box = raw.get("box")
        if not (isinstance(box, list) and len(box) == BOX_COORDINATE_COUNT):
            return None
        if not all(isinstance(v, (int, float)) and v == v for v in box):
            return None
        return cls(text=str(raw.get("text", "")), box=[float(v) for v in box])

    def to_dict(self) -> dict[str, Any]:
        """The line as its sidecar record."""
        return {"text": self.text, "box": self.box}
