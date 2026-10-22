"""One person of the GEDCOM interchange: the name, the life facts, the status.

The island's person record — the INDI's wire shape (``{"id", "name",
"aliases"}``, plus dob/dod, occupations, residence and a status) — and the
class owns it, including the HUSB/WIFE rule: attested pronouns when present,
else the pair's position, because gender is never inferred.

The archive's own identity record is ``records.Person``: a different record
for a different file (the island's residences hold place NAMES and its
status is ``pending``, which the archive's record refuses). ``from_person``
is the one seam between them, and the only source of ``pronouns``/``basis``
— the island's own files never carry either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.gedcom_date import GedcomDate
from tools.gedcom_residence import GedcomResidence
from tools.records import Person


@dataclass(frozen=True)
class GedcomPerson:
    """One person: the id (the archive id via REFN, else the record's xref),
    the name and its aliases, the life facts, and the status the record
    carries (the island's ``pending``, the archive's
    confirmed/proposed/estimated)."""

    id: str
    name: str
    aliases: tuple[str, ...] = ()
    pronouns: str | None = None  # the archive's attested pronouns — roles only, never inferred
    dob: GedcomDate | None = None
    dod: GedcomDate | None = None
    occupations: tuple[str, ...] = ()
    residence: tuple[GedcomResidence, ...] = ()
    status: str | None = None
    basis: dict[str, str] | None = None  # an estimate's evidence (the archive's review basis)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GedcomPerson:
        """The person a wire record states."""
        return cls(
            id=str(raw.get("id", "")),
            name=str(raw.get("name", "")),
            aliases=tuple(str(alias) for alias in (raw.get("aliases") or [])),
            dob=GedcomDate.from_dict(raw["dob"]) if raw.get("dob") else None,
            dod=GedcomDate.from_dict(raw["dod"]) if raw.get("dod") else None,
            occupations=tuple(str(occupation) for occupation in (raw.get("occupations") or [])),
            residence=tuple(GedcomResidence.from_dict(entry) for entry in (raw.get("residence") or [])),
            status=raw.get("status"),
            basis=raw.get("basis"),
        )

    @classmethod
    def from_person(cls, person: Person) -> GedcomPerson:
        """The archive's identity record as the island's person record."""
        return cls(
            id=person.id,
            name=person.name,
            aliases=person.aliases,
            pronouns=person.pronouns,
            dob=GedcomDate.from_dated_fact(person.dob) if person.dob else None,
            dod=GedcomDate.from_dated_fact(person.dod) if person.dod else None,
            occupations=person.occupations,
            residence=tuple(GedcomResidence.from_dict(entry) for entry in person.residence),
            status=person.status,
            basis=person.basis,
        )

    def role(self, position: int) -> str:
        """HUSB/WIFE from attested pronouns when present, else positionally
        (the first of a pair gets HUSB) — gender is never inferred: a
        they/them or unstated person is not forced into either role by
        default."""
        pronouns = (self.pronouns or "").lower()
        if pronouns.startswith("she"):
            return "WIFE"
        if pronouns.startswith("he"):
            return "HUSB"
        return "HUSB" if position == 0 else "WIFE"

    def to_dict(self) -> dict[str, Any]:
        """The person as the island's wire record — only what the record
        carries (pronouns and the estimate basis are the archive's, and the
        island's files never state them)."""
        out: dict[str, Any] = {"id": self.id, "name": self.name, "aliases": list(self.aliases)}
        if self.dob is not None:
            out["dob"] = self.dob.to_dict()
        if self.dod is not None:
            out["dod"] = self.dod.to_dict()
        if self.occupations:
            out["occupations"] = list(self.occupations)
        if self.residence:
            out["residence"] = [entry.to_dict() for entry in self.residence]
        if self.status is not None:
            out["status"] = self.status
        return out
