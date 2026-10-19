"""One page's orientation scores: the rotation the arbiter chose and its counts.

The orient stage records, per page, the rotation the arbiter picked (degrees CW),
how many strong words that rotation carried, and the per-rotation counts. That
record is `rotations.json`'s value — this class's wire, read by the routing
(`apply_routes`) and the multi-orientation gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RotationScores:
    """One page's orientation: the chosen rotation and the words it carried."""

    degrees: int
    strong: int
    scores: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RotationScores:
        """The scores a rotations.json entry holds."""
        return cls(
            degrees=int(raw.get("degrees", 0)),
            strong=int(raw.get("strong", 0)),
            scores={str(k): int(v) for k, v in (raw.get("scores") or {}).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        """The scores as the rotations.json entry."""
        return {"degrees": self.degrees, "strong": self.strong, "scores": dict(self.scores)}
