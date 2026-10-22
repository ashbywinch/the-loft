"""One document boundary: the pages the grouping put in one document, the
greeting that opened it and the sign-off that closed it, and the state the
review left it in.

The grouping scorer scores boundaries and the registry stores them: the guess
stage's ``boundaries.json`` and a batch record's ``boundaries`` list are this
class's record. An entry the review's push recorded also carries the
confirmation that recorded it — see `Confirmation`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from document.document import DOCUMENT_STATUSES, DocumentStatus
from pipeline.confirmation import Confirmation
from pipeline.page_flag import PageFlag


@dataclass
class Boundary:
    """One document boundary: its pages in reading order, the greeting that
    opened it, the sign-off that closed it, and the reviewer's state.

    ``status`` is None while no gate has decided — the wire's absent status,
    which the review surface reads as the draft state."""

    pages: list[str]
    greeting: str | None = None
    signoff: str | None = None
    status: DocumentStatus | None = None
    confirmation: Confirmation | None = None

    def __post_init__(self) -> None:
        if self.status is not None and self.status not in DOCUMENT_STATUSES:
            raise ValueError(f"boundary status {self.status!r} is not one of {list(DOCUMENT_STATUSES)}")

    @classmethod
    def opening_at(cls, page: str, flag: PageFlag | None) -> Boundary:
        """A fresh boundary at ``page`` — the model's greeting when the page
        carries the starts_document flag (a photo page has no flag at all)."""
        greeting = flag.greeting if flag is not None and flag.starts_document else None
        return cls(pages=[page], greeting=greeting)

    def add(self, page: str) -> None:
        """Join ``page`` to the boundary, in reading order."""
        self.pages.append(page)

    def add_first(self, page: str) -> None:
        """``page`` becomes the boundary's first — the picture side scanned
        after its text side is still page 1 (user, 2026-08-17)."""
        self.pages.insert(0, page)

    def carry(self, flag: PageFlag | None) -> None:
        """Carry the model's greeting/sign-off in when a joined page has them
        — a duplex boundary opens with the picture side (no flag), and the
        text side's model values belong to the document (2026-08-17)."""
        if self.greeting is None and flag is not None and flag.greeting:
            self.greeting = flag.greeting
        if flag is not None and flag.ends_document and flag.signoff:
            self.signoff = flag.signoff

    def reviewed(self, status: DocumentStatus) -> None:
        """The reviewer's decision — the status is the state."""
        self.status = status

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Boundary:
        """The boundary a ``boundaries.json`` entry or a batch record's
        ``boundaries`` entry describes."""
        status = raw.get("status")
        return cls(
            pages=[str(page) for page in raw.get("pages") or []],
            greeting=raw.get("greeting"),
            signoff=raw.get("signoff"),
            status=None if status is None else str(status),  # type: ignore[arg-type]  # __post_init__ checks the vocabulary
            confirmation=Confirmation.from_dict(raw),
        )

    def to_dict(self) -> dict[str, Any]:
        """The boundary as its wire entry — the status and the confirmation's
        keys only when the record carries them."""
        entry: dict[str, Any] = {
            "pages": list(self.pages),
            "greeting": self.greeting,
            "signoff": self.signoff,
        }
        if self.status is not None:
            entry["status"] = self.status
        if self.confirmation is not None:
            entry.update(self.confirmation.to_dict())
        return entry
