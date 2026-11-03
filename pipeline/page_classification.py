"""One page's content classification: the kind the classifier chose, the
confidences behind it, and — for a text page — the MEDIUM its writing is in
(TECHSPEC §16.14).

The kind is not free-standing data — it IS the strongest label among the
confidences — so they travel as one record, and `classify.json`'s per-page
record is this class's dict. The medium is a category, not a stage: printed
text and handwriting both read as "text", and the medium is what decides how
the page is read (one direct VLM transcription vs the row pipeline).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PageClassification:
    """The content kind a page was given, the confidences behind it, and the
    medium of a text page's writing (None for a photo or a drawing)."""

    kind: str
    confidences: dict[str, float]
    medium: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in self.confidences:
            raise ValueError(f"kind {self.kind!r} is not one of the confidences: {sorted(self.confidences)}")
        if self.medium is not None and self.kind not in ("postcard_face", "form"):
            raise ValueError(f"only a postcard face or a form carries a medium: {self.kind!r}")

    @classmethod
    def from_confidences(cls, confidences: dict[str, float], medium: str | None = None) -> PageClassification:
        """The classification the confidences imply: the strongest label wins
        (a tie goes to the first — the caller's label order decides)."""
        kind = max(confidences.items(), key=lambda item: item[1])[0]
        return cls(kind, confidences, medium if kind in ("postcard_face", "form") else None)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PageClassification:
        """The classification a ``classify.json`` record states."""
        confidences = {str(label): float(value) for label, value in raw["confidences"].items()}
        return cls(str(raw["kind"]), confidences, raw.get("medium"))

    def to_dict(self) -> dict[str, Any]:
        """The classification as its ``classify.json`` record."""
        record: dict[str, Any] = {"kind": self.kind, "confidences": self.confidences}
        if self.medium:
            record["medium"] = self.medium
        return record
