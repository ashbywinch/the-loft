"""Where a person lived and when: the place as given, the date sides, the note.

The island's residence record — the RESI event's wire shape
(``{"from": …, "to": …, "place": …}``, plus ``note`` where the record
carries one and ``status`` where the archive states one) — and the class
owns it. The place is the NAME as given, never a link to a Place; an
archive residence's place ID resolves through the export's place set at
render time (gedcom_document.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GedcomResidence:
    """One residence: the two date sides (either may be empty — a bare RESI
    is legal), the place name, an optional note, and the archive's status
    (the island never carries one; a pending/proposed residence never
    leaves the archive)."""

    from_: str = ""
    to: str = ""
    place: str = ""
    note: str | None = None
    status: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GedcomResidence:
        """The residence a wire record states — ``from`` is spelled ``from_``
        here (a Python keyword), the wire key stays ``from``."""
        return cls(
            from_=str(raw.get("from", "")),
            to=str(raw.get("to", "")),
            place=str(raw.get("place", "")),
            note=raw.get("note"),
            status=raw.get("status"),
        )

    def to_dict(self) -> dict[str, Any]:
        """The residence as its wire record — a note or status only where
        the record states one."""
        out: dict[str, Any] = {"from": self.from_, "to": self.to, "place": self.place}
        if self.note is not None:
            out["note"] = self.note
        if self.status is not None:
            out["status"] = self.status
        return out
