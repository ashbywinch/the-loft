"""A tool result that says nothing matched: the note the model reads before
it moves on.

The note is a dead end, never evidence — the model must not turn "no matches"
into a finding (the findings report what the records DO show, never a bare
absence). The shape the model reads (``{"note": …}``) is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolNote:
    """A tool's dead end — the note saying what was not found."""

    note: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ToolNote:
        """The note a wire record states."""
        return cls(note=str(raw.get("note", "")))

    def to_dict(self) -> dict[str, Any]:
        """The note as its wire record."""
        return {"note": self.note}
