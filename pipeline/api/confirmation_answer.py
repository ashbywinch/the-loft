"""The /api/sync/confirmations answer.

The document the receiver recorded — the batch and the document's index in it
— so the frontend can mark the pushed item received and drain the outbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfirmationAnswer:
    """The confirmation receiver's answer: the recorded document."""

    batch_id: str
    doc_index: int

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {"ok": True, "batch_id": self.batch_id, "doc_index": self.doc_index}
