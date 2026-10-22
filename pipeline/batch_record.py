"""The batch record: one adopted scan folder as the registry stores it.

The registry's ``<batch-id>.json`` is this class's record — the label the user
gave the pile, where the pile lives, the page hashes it was adopted at, the
boundaries the grouping scored and the review decided, and the state the
stages move it through. The class owns the wire format (the file's keys, in
the file's order) and the operations the adoption performs on it: a pile that
moved, a pile whose content changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from document.document import DOCUMENT_AGREED
from pipeline.boundary import Boundary

STATUS_PENDING = "pending"  # the state a fresh adoption's record starts in


@dataclass
class BatchRecord:
    """One batch's registry record."""

    batch_id: str
    path: Path
    label: str = ""
    source: str = ""
    status: str = STATUS_PENDING
    arrived_at: str = ""
    pages: dict[str, str] = field(default_factory=dict)
    fingerprint: list[str] = field(default_factory=list)
    boundaries: list[Boundary] | None = None
    content_changed: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BatchRecord:
        """The record a registry file holds."""
        boundaries = raw.get("boundaries")
        return cls(
            batch_id=str(raw["batch_id"]),
            path=Path(str(raw.get("path", ""))),
            label=str(raw.get("label", "")),
            source=str(raw.get("source", "")),
            status=str(raw.get("status", STATUS_PENDING)),
            arrived_at=str(raw.get("arrived_at", "")),
            pages={str(page): str(sha) for page, sha in (raw.get("pages") or {}).items()},
            fingerprint=[str(sha) for sha in raw.get("fingerprint") or []],
            boundaries=None if boundaries is None else [Boundary.from_dict(boundary) for boundary in boundaries],
            content_changed=bool(raw.get("content_changed", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        """The record as its registry file — the same keys, in the same order,
        with ``content_changed`` only while the flag is set."""
        record: dict[str, Any] = {
            "batch_id": self.batch_id,
            "path": str(self.path),
            "label": self.label,
            "source": self.source,
            "status": self.status,
            "arrived_at": self.arrived_at,
            "pages": dict(self.pages),
            "fingerprint": list(self.fingerprint),
            "boundaries": None if self.boundaries is None else [boundary.to_dict() for boundary in self.boundaries],
        }
        if self.content_changed:
            record["content_changed"] = True
        return record

    def re_home(self, folder: Path) -> None:
        """The pile moved: the record follows it (R4 — reorganising costs us
        work, never data)."""
        self.path = folder

    def apply_content_changed(self, folder: Path, pages: dict[str, str], fingerprint: list[str]) -> None:
        """The pile's content changed where it sits: the new page hashes, the
        pile's new home, and the flag for a manual review. The regenerable
        boundaries are cleared unless a confirmed transcription survives —
        those are never auto-cleared (the operator reviews what changed
        first)."""
        self.path = folder
        self.pages = dict(pages)
        self.fingerprint = list(fingerprint)
        self.status = STATUS_PENDING
        self.content_changed = True
        if not self.confirmed_boundaries():
            self.boundaries = None

    def confirmed_boundaries(self) -> list[Boundary]:
        """The documents the reviewer confirmed — the records never cleared."""
        return [boundary for boundary in self.boundaries or [] if boundary.status == DOCUMENT_AGREED]
