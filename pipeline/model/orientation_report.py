"""One page's orientation report: the regions that run in their own
direction and the located lines.

The report is the sidecar record (``{"orientation_hint", "lines"}``) the
layout's multi-direction assembly reads, so the class owns the record's
shape on both sides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.model.orientation_hint import OrientationHint
from pipeline.model.orientation_line import OrientationLine


@dataclass(frozen=True)
class OrientationReport:
    """What one orientation call reported: the flagged regions and the
    located lines (the lines keyed to the given transcription's numbers)."""

    hints: list[OrientationHint] = field(default_factory=list)
    lines: list[OrientationLine] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OrientationReport:
        """The report a stored sidecar carries — every field it holds, the
        per-line text included (an entry that is not a usable hint or line is
        dropped, not fatal)."""
        return cls._of(raw, keep_text=True)

    @classmethod
    def from_answer(cls, data: dict[str, Any]) -> OrientationReport:
        """The report a fresh model answer holds: the same record, except
        that a line's own text is left behind (see ``OrientationLine.of``)."""
        return cls._of(data, keep_text=False)

    @classmethod
    def _of(cls, raw: dict[str, Any], *, keep_text: bool) -> OrientationReport:
        raw_hints = raw.get("orientation_hint") if isinstance(raw.get("orientation_hint"), list) else []
        raw_lines = raw.get("lines") if isinstance(raw.get("lines"), list) else []
        return cls(
            hints=[hint for hint in (OrientationHint.of(entry) for entry in raw_hints) if hint is not None],
            lines=[
                line
                for line in (OrientationLine.of(entry, i, keep_text=keep_text) for i, entry in enumerate(raw_lines))
                if line is not None
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        """The report as its sidecar record."""
        return {
            "orientation_hint": [hint.to_dict() for hint in self.hints],
            "lines": [line.to_dict() for line in self.lines],
        }
