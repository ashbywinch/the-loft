"""One place of the GEDCOM interchange: its id, its name, its status.

The island's place record — the PLAC's wire shape (``{"id", "name"}``, plus
a status) — and the class owns it. The id is the record's REFN (the
round-trip seam, like people), else a deterministic slug of the payload
name. ``from_place`` is the seam to the archive's own ``records.Place``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.records import Place


@dataclass(frozen=True)
class GedcomPlace:
    """One place: the id, the name as given, and the status the record
    carries (the island's ``pending``, the archive's
    confirmed/proposed/estimated)."""

    id: str
    name: str
    status: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GedcomPlace:
        """The place a wire record states."""
        return cls(id=str(raw.get("id", "")), name=str(raw.get("name", "")), status=raw.get("status"))

    @classmethod
    def from_place(cls, place: Place) -> GedcomPlace:
        """The archive's place record as the island's place record."""
        return cls(id=place.id, name=place.name, status=place.status)

    def to_dict(self) -> dict[str, Any]:
        """The place as its wire record — a status only where the record
        states one."""
        out: dict[str, Any] = {"id": self.id, "name": self.name}
        if self.status is not None:
            out["status"] = self.status
        return out
