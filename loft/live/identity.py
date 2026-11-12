"""The identity collections beyond people — places, orgs, themes, relationships.

TECHSPEC/08 §19.4: one repository per collection on `Change`, one reader on
the store; each owns its record's row mapping. The four kinds share the
version/event/upsert mechanics, so one `Collection` class takes a `Kind`
description (its table, columns, payload and row mapping); the record types
stay typed.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from loft.live.errors import Conflict, NotFound, StaleVersion
from loft.live.person_row import RowPosition
from tools.records import Org, Place, Relationship
from tools.theme import Theme


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def relationship_id(record: Relationship) -> str:
    """The edge's stable id — its two ends and its kind."""
    return f"rel-{record.a}-{record.b}-{record.kind}"


@dataclass(frozen=True)
class Kind:
    """One identity collection's table, columns and record mapping."""

    name: str
    table: str
    id_column: str
    columns: tuple[str, ...]
    to_values: Callable[[Any, RowPosition], tuple[Any, ...]]
    from_row: Callable[[sqlite3.Row], Any]
    entity_kind: str


def _place_values(place: Place, position: RowPosition) -> tuple[Any, ...]:
    return (
        place.id,
        place.name,
        place.note,
        place.precision,
        place.lat,
        place.lng,
        place.x,
        place.y,
        place.address,
        place.status,
        _json(list(place.aliases)),
        _json(place.basis),
        position.version,
        position.event_no,
        position.event_seq,
        position.updated_at,
    )


def _place_row(row: sqlite3.Row) -> Place:
    raw: dict[str, Any] = {
        "id": row["place_id"],
        "name": row["name"],
        "note": row["note"] or "",
        "precision": row["precision"] or "",
        "address": row["address"] or "",
        "status": row["status"],
        "aliases": json.loads(row["aliases_json"] or "[]"),
    }
    for key in ("lat", "lng", "x", "y"):
        if row[key] is not None:
            raw[key] = row[key]
    if row["basis_json"]:
        raw["basis"] = json.loads(row["basis_json"])
    return replace(Place.from_dict(raw), version=row["version"])


PLACE = Kind(
    name="places",
    table="places",
    id_column="place_id",
    columns=(
        "place_id",
        "name",
        "note",
        "precision",
        "lat",
        "lng",
        "x",
        "y",
        "address",
        "status",
        "aliases_json",
        "basis_json",
        "version",
        "event_no",
        "event_seq",
        "updated_at",
    ),
    to_values=_place_values,
    from_row=_place_row,
    entity_kind="place",
)


def _org_values(org: Org, position: RowPosition) -> tuple[Any, ...]:
    return (
        org.id,
        org.name,
        org.address,
        org.branch,
        org.note,
        org.status,
        None,
        _json(list(org.aliases)),
        position.version,
        position.event_no,
        position.event_seq,
        position.updated_at,
    )


def _org_row(row: sqlite3.Row) -> Org:
    return replace(
        Org.from_dict(
            {
                "id": row["org_id"],
                "name": row["name"],
                "address": row["address"] or "",
                "branch": row["branch"] or "",
                "note": row["note"] or "",
                "status": row["status"],
                "aliases": json.loads(row["aliases_json"] or "[]"),
            }
        ),
        version=row["version"],
    )


ORG = Kind(
    name="orgs",
    table="orgs",
    id_column="org_id",
    columns=(
        "org_id",
        "name",
        "address",
        "branch",
        "note",
        "status",
        "basis_json",
        "aliases_json",
        "version",
        "event_no",
        "event_seq",
        "updated_at",
    ),
    to_values=_org_values,
    from_row=_org_row,
    entity_kind="org",
)


def _theme_values(theme: Theme, position: RowPosition) -> tuple[Any, ...]:
    raw = theme.to_dict()
    return (
        theme.id,
        theme.title,
        str(raw.get("subtitle", "")),
        1 if raw.get("seeded") else 0,
        str(raw.get("status", "confirmed")),
        _json(raw.get("basis")),
        _json(raw),
        position.version,
        position.event_no,
        position.event_seq,
        position.updated_at,
    )


def _theme_row(row: sqlite3.Row) -> Theme:
    return replace(Theme.from_dict(json.loads(row["body_json"])), version=row["version"])


THEME = Kind(
    name="themes",
    table="themes",
    id_column="theme_id",
    columns=(
        "theme_id",
        "title",
        "subtitle",
        "seeded",
        "status",
        "basis_json",
        "body_json",
        "version",
        "event_no",
        "event_seq",
        "updated_at",
    ),
    to_values=_theme_values,
    from_row=_theme_row,
    entity_kind="theme",
)


def _relationship_values(record: Relationship, position: RowPosition) -> tuple[Any, ...]:
    return (
        relationship_id(record),
        "person",
        record.a,
        "person",
        record.b,
        record.kind,
        record.label_a,
        record.label_b,
        _json(record.date.to_dict() if record.date is not None else None),
        None,
        record.status,
        position.version,
        position.event_no,
        position.event_seq,
        position.updated_at,
    )


def _relationship_row(row: sqlite3.Row) -> Relationship:
    raw: dict[str, Any] = {
        "a": row["a_id"],
        "b": row["b_id"],
        "kind": row["kind"],
        "label_a": row["label_a"] or "",
        "label_b": row["label_b"] or "",
    }
    if row["date_json"]:
        raw["date"] = json.loads(row["date_json"])
    if row["status"] is not None:
        raw["status"] = row["status"]
    return replace(Relationship.from_dict(raw), version=row["version"])


RELATIONSHIP = Kind(
    name="relationships",
    table="relationships",
    id_column="relationship_id",
    columns=(
        "relationship_id",
        "a_kind",
        "a_id",
        "b_kind",
        "b_id",
        "kind",
        "label_a",
        "label_b",
        "date_json",
        "basis_json",
        "status",
        "version",
        "event_no",
        "event_seq",
        "updated_at",
    ),
    to_values=_relationship_values,
    from_row=_relationship_row,
    entity_kind="relationship",
)


def record_id(kind: Kind, record: Any) -> str:
    if kind is RELATIONSHIP:
        return relationship_id(record)
    return str(record.id)


class Collection:
    """One identity collection on a connection (read) or a change (write)."""

    def __init__(self, connection: sqlite3.Connection, kind: Kind, change: Any | None = None) -> None:
        self.connection = connection
        self.kind = kind
        self.change = change

    def get(self, entity_id: str) -> Any | None:
        row = self.connection.execute(
            f"SELECT * FROM {self.kind.table} WHERE {self.kind.id_column} = ?", (entity_id,)
        ).fetchone()
        return None if row is None else self.kind.from_row(row)

    def require(self, entity_id: str) -> Any:
        record = self.get(entity_id)
        if record is None:
            raise NotFound(f"no {self.kind.name[:-1]} {entity_id}")
        return record

    def save(self, record: Any, base: int | None = None) -> Any:
        if self.change is None:
            raise Conflict(f"{self.kind.name}.save needs a change")
        entity_id = record_id(self.kind, record)
        current = self.get(entity_id)
        if base is None:
            if current is not None:
                raise Conflict(f"{self.kind.name[:-1]} {entity_id} exists")
            event_type = "created"
            version = 1
        else:
            if current is None:
                raise NotFound(f"no {self.kind.name[:-1]} {entity_id}")
            if current.version != base:
                raise StaleVersion(current=current, base=base)
            event_type = "superseded"
            version = base + 1
        payload = json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        event = self.change.append(
            entity_kind=self.kind.entity_kind,
            entity_id=entity_id,
            event_type=event_type,
            entity_version=version,
            payload=payload,
        )
        saved = _with_version(record, version)
        self._write(saved, RowPosition(version, event["event_no"], event["seq"], event["recorded_at"]), base)
        return saved

    def _write(self, record: Any, position: RowPosition, base: int | None) -> None:
        values = self.kind.to_values(record, position)
        placeholders = ", ".join("?" for _ in values)
        assignments = ", ".join(
            f"{column} = excluded.{column}" for column in self.kind.columns if column != self.kind.id_column
        )
        cursor = self.connection.execute(
            f"""INSERT INTO {self.kind.table} ({", ".join(self.kind.columns)}) VALUES ({placeholders})
                ON CONFLICT ({self.kind.id_column}) DO UPDATE SET {assignments}
                WHERE {self.kind.table}.version IS ?""",
            (*values, base),
        )
        if cursor.rowcount == 0:
            current = self.get(record_id(self.kind, record))
            raise StaleVersion(current=current, base=base)


def _with_version(record: Any, version: int) -> Any:
    return replace(record, version=version)
