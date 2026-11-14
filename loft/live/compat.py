"""The compatibility exporter — the old-shape identity tables, from the DB.

TECHSPEC/08 §19.4 and REWRITE-PLAN B1: from the flip the DB is the write
source, but the old readers still parse the archive's own tables. After every
identity write the service calls this exporter, which rewrites
`people.json` (with its relationships), `places.json`, `orgs.json` and
`themes.json` in the archive's append-only, versioned form. A table identical
to the last file writes nothing — no byte-identical versions.

The proposed queue is the same surface's second half (B3b): the queue files
follow the rows, through `ProposedCompatibility`.

The mapping is `identity_map`'s reverse: a confirmed record with a
recollection/inference basis below certainty is the old `estimated` status,
and the model's basis/confidence pair is not part of the old wire shape. A
`rejected` or merged-away record is excluded from browse.
"""

from __future__ import annotations

from typing import Any

from loft.live.compat_proposed import ProposedCompatibility
from loft.live.identity_map import BasisKinds, renders_estimated
from loft.live.protocols import IdentityStore
from tools.archive import Archive
from tools.records import Org, OrgsTable, PeopleTable, Person, Place, PlacesTable, Relationship, ThemesTable
from tools.theme import Theme


def legacy_status(status: str, basis: dict[str, str] | None) -> str:
    """The old status for a live disposition + basis (`estimated` is the
    rendering of a confirmed recollection below certainty)."""
    if status in ("proposed", "estimated", "rejected"):
        return status
    if renders_estimated(basis):
        return "estimated"
    return "confirmed"


def legacy_basis(basis: dict[str, str] | None) -> dict[str, str] | None:
    """The old wire basis — the reviewer's own words, never the model's
    basis/confidence pair."""
    evidence = {key: str(value) for key, value in (basis or {}).items() if key in BasisKinds.EVIDENCE and value}
    return evidence or None


def legacy_person(person: Person) -> dict[str, Any]:
    """One person in the archive's own wire shape."""
    return _legacy_record(person)


def legacy_place(place: Place) -> dict[str, Any]:
    return _legacy_record(place)


def _legacy_record(record: Any) -> dict[str, Any]:
    raw = record.to_dict()
    raw.pop("status", None)
    raw.pop("basis", None)
    status = legacy_status(record.status, record.basis)
    if status != "confirmed":
        raw["status"] = status
    basis = legacy_basis(record.basis)
    if basis:
        raw["basis"] = basis
    return raw


def legacy_org(org: Org) -> dict[str, Any]:
    raw = org.to_dict()
    if raw.get("status") == "confirmed":
        raw.pop("status")
    return raw


def legacy_theme(theme: Theme) -> dict[str, Any]:
    raw = dict(theme.to_dict())
    basis = raw.pop("basis", None)
    raw.pop("status", None)
    status = legacy_status(theme_status(theme), basis)
    if status != "confirmed":
        raw["status"] = status
    evidence = legacy_basis(basis)
    if evidence:
        raw["basis"] = evidence
    return raw


def theme_status(theme: Theme) -> str:
    """The theme's disposition — its wire record carries it in the body."""
    return str(theme.to_dict().get("status", "confirmed"))


def legacy_relationship(edge: Relationship) -> dict[str, Any]:
    raw = edge.to_dict()
    if raw.get("status") == "confirmed":
        raw.pop("status")
    return raw


class CompatibilityExport:
    """Rewrite the old-shape identity tables and proposed queue from the live store."""

    def __init__(self, store: IdentityStore, archive: Archive) -> None:
        self.store = store
        self.archive = archive
        self.queue = ProposedCompatibility(store, archive)

    def write(self) -> tuple[str, ...]:
        """Write every table whose content moved and maintain the queue files;
        return the tables written. Every table is built before the first write,
        so a record the old reader cannot parse leaves the tree untouched."""
        tables = {"people": self._people(), "places": self._places(), "orgs": self._orgs(), "themes": self._themes()}
        written = tuple(name for name, table in tables.items() if self._write(name, table))
        self.queue.write()
        return written

    def _people(self) -> PeopleTable:
        losers = self.store.aliases.losers("person")
        people = [
            legacy_person(person)
            for person in self.store.people.all()
            if person.status != "rejected" and person.id not in losers
        ]
        edges = [legacy_relationship(edge) for edge in self.store.relationships.all() if edge.status != "rejected"]
        return PeopleTable.from_dict({"people": people, "relationships": edges})

    def _places(self) -> PlacesTable:
        return PlacesTable.from_dict(
            {"places": [legacy_place(place) for place in self.store.places.all() if place.status != "rejected"]}
        )

    def _orgs(self) -> OrgsTable:
        return OrgsTable.from_dict(
            {"orgs": [legacy_org(org) for org in self.store.orgs.all() if org.status != "rejected"]}
        )

    def _themes(self) -> ThemesTable:
        return ThemesTable.from_dict(
            {"themes": [legacy_theme(theme) for theme in self.store.themes.all() if theme_status(theme) != "rejected"]}
        )

    def _write(self, name: str, table: Any) -> bool:
        current = self.archive.get_identity(name)
        if current is not None and current.to_dict() == table.to_dict():
            return False
        self.archive.save_identity(name, table)
        return True
