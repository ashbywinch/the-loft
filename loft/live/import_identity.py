"""A3 — import the identity tables from the file archive (TECHSPEC/11).

The old tree is read-only; the DB is a copy. The import is one change, skips a
record the store already holds (a re-run is a no-op), and refuses without the
backup marker `11 §Preconditions` requires. A dry run prints the plan and
writes nothing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

from loft.live.errors import LiveError
from loft.live.identity import relationship_id
from loft.live.identity_map import disposition_of
from loft.live.store import LiveStore
from tools.records import (
    Org,
    OrgsTable,
    PeopleTable,
    Place,
    PlacesTable,
    ThemesTable,
)
from tools.theme import Theme

_VERSION = re.compile(r"-(\d+)\.json$")


class BackupMarkerError(LiveError):
    """The migration refuses to run without a verified backup marker."""


@dataclass(frozen=True)
class IdentityReport:
    """What the import did (or would do) — the counts, operations and result."""

    counts: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    operations: tuple[str, ...] = ()
    dry_run: bool = False
    mismatches: tuple[str, ...] = ()


def _latest(archive: Path, name: str) -> Path:
    """The newest version of an identity table (v1 is the unversioned file)."""
    versioned = [
        (int(match.group(1)), path) for path in archive.glob(f"{name}-*.json") if (match := _VERSION.search(path.name))
    ]
    if versioned:
        return max(versioned)[1]
    return archive / f"{name}.json"


def _mapped_person(person: Any) -> Any:
    status, basis = disposition_of(person.status, person.basis)
    return replace(person, status=cast(Any, status), basis=basis)


def _mapped_place(place: Place) -> Place:
    status, basis = disposition_of(place.status, place.basis)
    return replace(place, status=cast(Any, status), basis=basis)


def _mapped_org(org: Org) -> Org:
    status, _basis = disposition_of(org.status)
    return replace(org, status=cast(Any, status))


def _mapped_theme(theme: Theme) -> Theme:
    raw = theme.to_dict()
    status, basis = disposition_of(str(raw.get("status", "confirmed")), raw.get("basis"))
    return Theme.from_dict({**raw, "status": status, "basis": basis})


@dataclass(frozen=True)
class IdentityTables:
    """The five identity tables as the archive states them."""

    people: PeopleTable
    places: PlacesTable
    orgs: OrgsTable
    themes: ThemesTable


def _read_tables(archive: Path) -> IdentityTables:
    return IdentityTables(
        people=PeopleTable.from_dict(json.loads(_latest(archive, "people").read_text(encoding="utf-8"))),
        places=PlacesTable.from_dict(json.loads(_latest(archive, "places").read_text(encoding="utf-8"))),
        orgs=OrgsTable.from_dict(json.loads(_latest(archive, "orgs").read_text(encoding="utf-8"))),
        themes=ThemesTable.from_dict(json.loads(_latest(archive, "themes").read_text(encoding="utf-8"))),
    )


def _check_marker(marker: Path) -> None:
    if not marker.is_file():
        raise BackupMarkerError(f"no verified backup marker at {marker} — take the snapshot first")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BackupMarkerError(f"backup marker {marker} is unreadable: {error}") from error
    if payload.get("verified") is not True:
        raise BackupMarkerError(f"backup marker {marker} is not verified")


def _plan(store: LiveStore, archive: Path) -> tuple[list[tuple[str, Any]], dict[str, int]]:
    """The records to import (skipping what the store holds) and the skips."""
    tables = _read_tables(archive)
    planned: list[tuple[str, Any]] = []
    skipped = {"people": 0, "relationships": 0, "places": 0, "orgs": 0, "themes": 0}
    for person in tables.people.people:
        mapped = _mapped_person(person)
        if store.people.get(mapped.id) is not None:
            skipped["people"] += 1
        else:
            planned.append(("people", mapped))
    for edge in tables.people.relationships:
        if store.relationships.get(relationship_id(edge)) is not None:
            skipped["relationships"] += 1
        else:
            planned.append(("relationships", edge))
    for place in tables.places.places:
        mapped = _mapped_place(place)
        if store.places.get(mapped.id) is not None:
            skipped["places"] += 1
        else:
            planned.append(("places", mapped))
    for org in tables.orgs.orgs:
        mapped = _mapped_org(org)
        if store.orgs.get(mapped.id) is not None:
            skipped["orgs"] += 1
        else:
            planned.append(("orgs", mapped))
    for theme in tables.themes.themes:
        mapped = _mapped_theme(theme)
        if store.themes.get(mapped.id) is not None:
            skipped["themes"] += 1
        else:
            planned.append(("themes", mapped))
    return planned, skipped


def _entity_id(kind: str, record: Any) -> str:
    if kind == "relationships":
        return relationship_id(record)
    return str(record.id)


def _compare(store: LiveStore, planned: list[tuple[str, Any]]) -> tuple[str, ...]:
    mismatches: list[str] = []
    for kind, record in planned:
        stored = getattr(store, kind).require(_entity_id(kind, record))
        if stored.to_dict() != record.to_dict():
            mismatches.append(f"{kind} {_entity_id(kind, record)} differs from the imported record")
    return tuple(mismatches)


def import_identities(
    store: LiveStore,
    archive: Path,
    *,
    backup_marker: Path,
    dry_run: bool = False,
) -> IdentityReport:
    """Import people, relationships, places, orgs and themes from the archive."""
    _check_marker(backup_marker)
    planned, skipped = _plan(store, archive)
    counts = {"people": 0, "relationships": 0, "places": 0, "orgs": 0, "themes": 0}
    for kind, _record in planned:
        counts[kind] += 1
    operations = tuple(f"{kind[:-1]} {_entity_id(kind, record)}" for kind, record in planned)
    if dry_run:
        return IdentityReport(counts=counts, skipped=skipped, operations=operations, dry_run=True)
    with store.change(actor="import", note="identity tables") as change:
        for kind, record in planned:
            getattr(change, kind).save(record)
    return IdentityReport(
        counts=counts,
        skipped=skipped,
        operations=operations,
        dry_run=False,
        mismatches=_compare(store, planned),
    )
