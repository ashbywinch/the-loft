"""One page's content classification: the kind the classifier chose and the
confidences behind it (TECHSPEC §16.14).

The kind is not free-standing data — it IS the strongest label among the
confidences — so the two travel as one record, and `classify.json`'s per-page
record is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PageClassification:
    """The content kind a page was given, with the confidences behind it."""

    kind: str
    confidences: dict[str, float]

    def __post_init__(self) -> None:
        if self.kind not in self.confidences:
            raise ValueError(f"kind {self.kind!r} is not one of the confidences: {sorted(self.confidences)}")

    @classmethod
    def from_confidences(cls, confidences: dict[str, float]) -> PageClassification:
        """The classification the confidences imply: the strongest label wins
        (a tie goes to the first — the caller's label order decides)."""
        kind = max(confidences.items(), key=lambda item: item[1])[0]
        return cls(kind, confidences)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PageClassification:
        """The classification a ``classify.json`` record states."""
        confidences = {str(label): float(value) for label, value in raw["confidences"].items()}
        return cls(str(raw["kind"]), confidences)

    def to_dict(self) -> dict[str, Any]:
        """The classification as its ``classify.json`` record."""
        return {"kind": self.kind, "confidences": self.confidences}
