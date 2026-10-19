"""The confirmation a recorded boundary entry carries: the review push's own
keys, stored beside the boundary's fields because the payload is what the
write seam records.

They are the transport's keys, not the boundary's (document/document.py says
the same of the artefact's entries), and they travel together, so they are one
record. ``from_dict`` returns None for an entry carrying none of them — the
grouping's own entry, which no push has confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# The confirmation payload's keys (the sync contract's REQUIRED_FIELDS): a
# recorded entry carries all of them or none.
CONFIRMATION_KEYS = ("batch_id", "doc_index", "text", "confirmed_at")


@dataclass(frozen=True)
class Confirmation:
    """The review push's keys as the registry recorded them."""

    batch_id: str
    doc_index: int
    text: str | None
    confirmed_at: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Confirmation | None:
        """The confirmation a boundary entry carries, or None when the entry
        is the grouping's own (no push has recorded a decision)."""
        if not all(key in raw for key in CONFIRMATION_KEYS):
            return None
        return cls(
            batch_id=str(raw["batch_id"]),
            doc_index=int(raw["doc_index"]),
            text=raw["text"],
            confirmed_at=str(raw["confirmed_at"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """The confirmation's keys, in the payload's own order."""
        return {
            "batch_id": self.batch_id,
            "doc_index": self.doc_index,
            "text": self.text,
            "confirmed_at": self.confirmed_at,
        }
