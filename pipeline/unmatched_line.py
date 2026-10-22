"""A detector line that no transcription line claimed.

The layout rides these along with conf 0: their geometry is real, a
confident text anchor is not (the surface renders them as the page's
unclaimed ink). It is the artefact's ``unmatched`` entry, so the class owns
that wire record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UnmatchedLine:
    """A detector line that matched no transcription line."""

    box: list[float]
    text: str
    conf: float = 0.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> UnmatchedLine:
        """The unclaimed line a layout's ``unmatched`` entry describes."""
        return cls(box=raw["box"], text=str(raw.get("text", "")), conf=float(raw.get("conf", 0.0)))

    def to_dict(self) -> dict[str, Any]:
        """The unclaimed line as its layout-JSON entry."""
        return {"box": self.box, "text": self.text, "conf": self.conf}
