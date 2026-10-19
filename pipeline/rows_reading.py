"""The page's reading artefact: what the read stage measured and read.

The read stage persists one reading per page — the page's name and pixel size,
the rotation the reading is in, its revision, and the reader's lines with the
text read for each. That file (`<page>.rows.json` beside the guess) is this
class's wire: `from_dict` reads it and `to_dict` writes it, so the review's
rotate and the drafts seam read the same record the read stage wrote.

The lines are the reader's own line records (`pipeline/detect/reader.py`); a
strip-era `layout.json` is a different artefact (`pipeline/layout.py`'s Layout)
and a rotate reads either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# the reader's line records: index, text, box, orientation, box_source, words
LineRecords = list[dict[str, Any]]


@dataclass
class RowsReading:
    """One page's reading: its page name, pixel size, rotation and lines.

    The rotate rewrites the record in place (the rotation, the dims and every
    line's box), so this one is mutable — the reading IS the state a rotate
    advances."""

    page: str
    width: int
    height: int
    rotation: int = 0
    revision: int = 1
    lines: LineRecords = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RowsReading:
        """The reading a rows.json holds."""
        return cls(
            page=str(raw["page"]),
            width=int(raw["width"]),
            height=int(raw["height"]),
            rotation=int(raw.get("rotation", 0)),
            revision=int(raw.get("revision", 1)),
            lines=list(raw.get("lines") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        """The reading as the rows.json artefact."""
        return {
            "page": self.page,
            "width": self.width,
            "height": self.height,
            "rotation": self.rotation,
            "revision": self.revision,
            "lines": list(self.lines),
        }
