"""One relationship edge of the GEDCOM interchange.

The island's edge record — the relationship wire shape (``{"a", "b",
"kind"}``, plus a date a marriage states and the status the record carries:
the island's ``pending``, the archive's confirmed/proposed/estimated) — and
the class owns it. Its own class, not ``records.Relationship``: a GEDCOM
ASSO's kind is whatever the file's ROLE/RELA states (never the archive's
closed vocabulary) and its status is ``pending``. ``from_relationship`` is
the one seam between the archive's edge and the island's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.gedcom_date import GedcomDate
from tools.records import Relationship


@dataclass(frozen=True)
class GedcomEdge:
    """One edge: the two ends, the kind, and the date/status the record
    states."""

    a: str
    b: str
    kind: str
    date: GedcomDate | None = None
    status: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GedcomEdge:
        """The edge a wire record states."""
        return cls(
            a=str(raw.get("a", "")),
            b=str(raw.get("b", "")),
            kind=str(raw.get("kind", "")),
            date=GedcomDate.from_dict(raw["date"]) if raw.get("date") else None,
            status=raw.get("status"),
        )

    @classmethod
    def from_relationship(cls, relationship: Relationship) -> GedcomEdge:
        """The archive's relationship as the island's edge (the archive's
        labels are the app's, never the interchange's)."""
        return cls(
            a=relationship.a,
            b=relationship.b,
            kind=relationship.kind,
            date=GedcomDate.from_dated_fact(relationship.date) if relationship.date else None,
            status=relationship.status,
        )

    def to_dict(self) -> dict[str, Any]:
        """The edge as its wire record — a date or status only where the
        record states one."""
        out: dict[str, Any] = {"a": self.a, "b": self.b, "kind": self.kind}
        if self.date is not None:
            out["date"] = self.date.to_dict()
        if self.status is not None:
            out["status"] = self.status
        return out
