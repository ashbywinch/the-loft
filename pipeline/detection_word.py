"""The detector's box for one word inside a detected line.

A detected line's ``words`` are the boxes the detector measured inside it —
one box per word, no text (the line carries the text). The box is what the
multi-orientation layout pairs with the transcription's tokens, so the
record is the box and nothing else; it is named because the code reads it
by position otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DetectionWord:
    """One word box the detector measured inside a detected line."""

    box: list[float] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DetectionWord:
        """The word box a detection's ``words`` entry describes — an entry
        with no box is the unboxed word (the rec could not place it)."""
        return cls(box=raw.get("box"))

    def to_dict(self) -> dict[str, Any]:
        """The word box as its detection entry."""
        return {"box": self.box}
