"""The island's record set: its people, their relationships, and its places.

The GEDCOM island is a folder of record files — ``people.json`` (people +
relationships) and ``places.json`` (places), the same file names as the
archive's identity tables, unrelated to the live archive. This class owns
that set and its files: ``read``/``write`` are the folder seam, and
``from_dict``/``to_dict`` the merged wire; ``from_archive`` builds the set
from the archive's identity tables (the export path).

The records are held id-ordered (people and places by id, edges by
a/kind/b), so the folder's bytes are deterministic whatever order the
caller supplies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from tools.gedcom_edge import GedcomEdge
from tools.gedcom_person import GedcomPerson
from tools.gedcom_place import GedcomPlace
from tools.records import PeopleTable, PlacesTable


@dataclass(frozen=True)
class _ExportSet:
    """What leaves the archive — the confirmed/estimated people and edges,
    plus the lookup maps the export renders them with: exported ids, edges,
    place names, people by id, and the deterministic xref ids (sorted order,
    documented mapping). Named fields instead of the positional 5-tuple the
    call site could not read."""

    exported_ids: set[str]
    edges: tuple[GedcomEdge, ...]
    place_names: dict[str, str]
    by_id: dict[str, GedcomPerson]
    xref: dict[str, str]


@dataclass(frozen=True)
class GedcomShapes:
    """The island's record set: the people, the relationship edges, the places."""

    PEOPLE_FILE = "people.json"
    PLACES_FILE = "places.json"

    # which keys of the merged wire each file carries: the people file carries
    # the people and their relationships, the places file the places
    _ISLAND_FILES: ClassVar[tuple[tuple[str, tuple[str, ...]], ...]] = (
        (PEOPLE_FILE, ("people", "relationships")),
        (PLACES_FILE, ("places",)),
    )

    people: tuple[GedcomPerson, ...] = ()
    relationships: tuple[GedcomEdge, ...] = ()
    places: tuple[GedcomPlace, ...] = ()

    def __post_init__(self) -> None:
        """The island's records are id-ordered — the folder's bytes are
        deterministic (id order, like every other record file)."""
        object.__setattr__(self, "people", tuple(sorted(self.people, key=lambda person: person.id)))
        object.__setattr__(
            self, "relationships", tuple(sorted(self.relationships, key=lambda edge: (edge.a, edge.kind, edge.b)))
        )
        object.__setattr__(self, "places", tuple(sorted(self.places, key=lambda place: place.id)))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GedcomShapes:
        """A folder's record files, merged, as the island's record set."""
        return cls(
            people=tuple(GedcomPerson.from_dict(person) for person in (raw.get("people") or [])),
            relationships=tuple(GedcomEdge.from_dict(edge) for edge in (raw.get("relationships") or [])),
            places=tuple(GedcomPlace.from_dict(place) for place in (raw.get("places") or [])),
        )

    @classmethod
    def from_archive(cls, people: PeopleTable, places: PlacesTable) -> GedcomShapes:
        """The archive's identity tables as the island's record set — the
        export path."""
        return cls(
            people=tuple(GedcomPerson.from_person(person) for person in people.people),
            relationships=tuple(GedcomEdge.from_relationship(edge) for edge in people.relationships),
            places=tuple(GedcomPlace.from_place(place) for place in places.places),
        )

    def export_set(self) -> _ExportSet:
        """The confirmed/estimated people and edges that leave the archive —
        proposed records stay out (2026-08-09 review) — plus the lookup maps:
        exported ids, edges, place names, people by id, and the deterministic
        xref ids (sorted order, documented mapping)."""
        exported = tuple(person for person in self.people if person.status in (None, "confirmed", "estimated"))
        exported_ids = {person.id for person in exported}
        edges = tuple(
            edge
            for edge in self.relationships
            if edge.a in exported_ids
            and edge.b in exported_ids
            and edge.status in (None, "confirmed", "estimated")  # proposed edges stay out too (2026-08-09 review)
        )
        place_names = {place.id: place.name for place in self.places}
        by_id = {person.id: person for person in exported}
        xref = {pid: f"P{i}" for i, pid in enumerate(sorted(exported_ids), start=1)}
        return _ExportSet(exported_ids, edges, place_names, by_id, xref)

    @classmethod
    def read(cls, folder: Path) -> GedcomShapes:
        """The island's folder -> its record set."""
        people = json.loads((folder / GedcomShapes.PEOPLE_FILE).read_text(encoding="utf-8"))
        places = json.loads((folder / GedcomShapes.PLACES_FILE).read_text(encoding="utf-8"))
        return cls(
            people=tuple(GedcomPerson.from_dict(person) for person in (people.get("people") or [])),
            relationships=tuple(GedcomEdge.from_dict(edge) for edge in (people.get("relationships") or [])),
            places=tuple(GedcomPlace.from_dict(place) for place in (places.get("places") or [])),
        )

    def to_dict(self) -> dict[str, Any]:
        """The island's record set as its merged wire."""
        return {
            "people": [person.to_dict() for person in self.people],
            "relationships": [edge.to_dict() for edge in self.relationships],
            "places": [place.to_dict() for place in self.places],
        }

    def write(self, folder: Path) -> None:
        """Write the island's record files — the same file names and shape
        as the archive's identity tables, sorted keys, indent 2, one
        trailing newline."""
        wire = self.to_dict()
        for name, keys in GedcomShapes._ISLAND_FILES:
            payload = {key: wire[key] for key in keys}
            (folder / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
