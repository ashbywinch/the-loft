"""The ASSO records keyed by the person they sit on.

The island's associations are read and written per person — the import
groups an INDI's ASSO children under its xref, the export asks each
exported person for its own. The class holds that grouping so no caller
threads a bare mapping: ``add`` is the one write, ``for_person`` the one
read, ``records`` the whole set (the edge builder takes it all).
"""

from __future__ import annotations

from tools.gedcom_association import GedcomAssociation


class GedcomAssociations:
    """The ASSO records, by their subject person."""

    def __init__(self) -> None:
        self._by_subject: dict[str, list[GedcomAssociation]] = {}

    def add(self, association: GedcomAssociation) -> None:
        """Record one association under its subject."""
        self._by_subject.setdefault(association.subject, []).append(association)

    def for_person(self, person_id: str) -> tuple[GedcomAssociation, ...]:
        """The associations that sit on one person — empty for a person
        with none."""
        return tuple(self._by_subject.get(person_id, ()))

    def records(self) -> tuple[GedcomAssociation, ...]:
        """Every association, in the order it was recorded."""
        return tuple(association for associations in self._by_subject.values() for association in associations)
