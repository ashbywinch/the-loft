"""The /api/sync/confirmations answer.

The document the receiver recorded — the batch, the document's index in it,
and the archive item an agreed document became (empty for a rejection) — so
the frontend can mark the pushed item received, drain the outbox, and link
the reviewer to what they just agreed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfirmationAnswer:
    """The confirmation receiver's answer: the recorded document."""

    batch_id: str
    doc_index: int
    item_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {"ok": True, "batch_id": self.batch_id, "doc_index": self.doc_index, "item_id": self.item_id}
