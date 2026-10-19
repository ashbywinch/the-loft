"""The page-fix answers: the rotate and the re-read.

The page the reviewer fixed and whether its transcription is now re-running in
the background — the surface greys the document while ``processing`` is true
and lets the reviewer navigate on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PageProcessingAnswer:
    """A page-fix route's answer: the page and its re-read's state."""

    batch_id: str
    page: str
    processing: bool

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {"ok": True, "batch_id": self.batch_id, "page": self.page, "processing": self.processing}
