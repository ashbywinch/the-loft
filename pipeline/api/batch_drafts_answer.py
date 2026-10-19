"""The /api/sync/batch/{id}/drafts answer.

The machine drafts the review surface renders — the guess's texts, boundaries
and layout, with the registry's per-document review status merged in — plus
the pages whose transcription is being re-run right now, so the surface greys
those documents while the async job works.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BatchDraftsAnswer:
    """The drafts route's answer: the batch's label, drafts and live jobs."""

    batch_id: str
    label: str
    documents: list[dict[str, Any]]
    processing: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {
            "batch_id": self.batch_id,
            "label": self.label,
            "documents": self.documents,
            "processing": self.processing,
        }
