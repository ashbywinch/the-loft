"""The basis a review decision records for an estimate: the reviewer's own
words, the named person who recalled them, the date, and — where one was
written beside them — the provenance note.

An estimate without a basis isn't an estimate: the words are the family's,
recorded verbatim, never the model's summary. The wire shape
(``{"text": …, "by": …, "when": …}``, plus ``note`` where one is written) is
this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DecisionBasis:
    """One decision's basis — the reviewer's words, who recalled them, when,
    and the provenance beside them."""

    text: str = ""
    by: str = ""
    when: str = ""
    note: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DecisionBasis:
        """The basis a wire record states."""
        return cls(
            text=str(raw.get("text", "")),
            by=str(raw.get("by", "")),
            when=str(raw.get("when", "")),
            note=str(raw.get("note", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """The basis as its wire record — an unwritten note stays absent."""
        out: dict[str, Any] = {"text": self.text, "by": self.by, "when": self.when}
        if self.note:
            out["note"] = self.note
        return out
