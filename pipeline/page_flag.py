"""One page's guess-stage flags: its corrected reading and its boundaries.

The guess stage asks the model for one entry per page — the verbatim corrected
text, whether the page opens or closes a document, and the greeting or sign-off
the page carries. That entry is this record's wire (`from_dict` reads the
model's answer, `to_dict` writes it), and the grouping stage scores the
documents from these flags, so the record is the guess stage's own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PageFlag:
    """One page's guess-stage record: what it reads and where it sits in a document."""

    page: str
    text: str = ""
    starts_document: bool = False
    ends_document: bool = False
    greeting: str | None = None
    signoff: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PageFlag:
        """The flag record the model's answer entry states.

        The boundary flags arrive as JSON booleans; a string form must not
        coerce ("false" → True would mis-group documents), so only a real
        boolean (or a 0/1 number, or "true"/"1") counts."""
        if not isinstance(raw, dict) or "page" not in raw or "text" not in raw:
            raise ValueError(f"not a page flag record: {raw!r}")
        return cls(
            page=str(raw["page"]),
            text=str(raw["text"]),
            starts_document=_flag_bool(raw.get("starts_document")),
            ends_document=_flag_bool(raw.get("ends_document")),
            greeting=raw.get("greeting"),
            signoff=raw.get("signoff"),
        )

    def to_dict(self) -> dict[str, Any]:
        """The flag record as the guess stage's own entry."""
        return {
            "page": self.page,
            "text": self.text,
            "starts_document": self.starts_document,
            "ends_document": self.ends_document,
            "greeting": self.greeting,
            "signoff": self.signoff,
        }


def _flag_bool(value: object) -> bool:
    """The model's boundary flags are JSON booleans; string forms must not
    coerce ("false" → True would mis-group documents)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1")
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return False
