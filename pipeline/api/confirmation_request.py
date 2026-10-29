"""The /api/sync/confirmations request.

One document's reviewed reading, pushed by the frontend: the batch and the
document's index in it, the boundary that was reviewed (its pages and their
greeting/signoff), the corrected text — ``None`` marks a rejection, and
``record_confirmation`` writes it as such (nothing is silently dropped) — and,
for an agreed document, its own facts: the title and the date the family
gives it (a document cannot become an archive item without them).

The shape is validated by the sync contract's own guard
(``validate_confirmation``), so the receiver and the CLI review gate read ONE
rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pipeline.api.sync import validate_confirmation
from pipeline.boundary import Boundary


@dataclass(frozen=True)
class ConfirmationRequest:
    """A reviewed document: the batch, the document, its corrected text, and
    (when agreed) the facts that mint its item."""

    batch_id: str
    doc_index: int
    boundary: Boundary
    text: str | None
    title: str = ""
    date: str = ""
    date_precision: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ConfirmationRequest:
        """The confirmation a client states."""
        payload = validate_confirmation(dict(raw))
        return cls(
            batch_id=str(payload["batch_id"]),
            doc_index=int(payload["doc_index"]),
            boundary=Boundary.from_dict(payload),
            text=payload.get("text") if payload.get("status") == "confirmed" else None,
            title=str(payload.get("title", "")),
            date=str(payload.get("date", "")),
            date_precision=str(payload.get("date_precision", "")),
        )
