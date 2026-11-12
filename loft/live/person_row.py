"""The person projection's row mapping — the domain type owns no SQL.

TECHSPEC/05 §18.4: scalar fields become columns, the small nested structures
JSON columns, and the shared version/event columns carry the projection's
position in the log. A2 projects people only.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from typing import Any

from loft.live.errors import StaleVersion
from loft.live.identity_map import date_value
from tools.records import Person


@dataclass(frozen=True)
class RowPosition:
    """Where a projection row stands in the log — the shared columns."""

    version: int
    event_no: int
    event_seq: int
    updated_at: str


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def to_row(person: Person, position: RowPosition) -> tuple[Any, ...]:
    """The column values for one person row, in `people`'s column order."""
    return (
        person.id,
        person.name,
        person.years,
        person.relation,
        person.bio,
        person.email,
        person.pronouns,
        person.hue,
        person.status,
        _json(person.dob.to_dict() if person.dob is not None else None),
        _json(person.dod.to_dict() if person.dod is not None else None),
        _json(list(person.aliases)),
        _json(list(person.occupations)),
        _json(person.basis),
        position.version,
        position.event_no,
        position.event_seq,
        position.updated_at,
    )


def write_row(
    connection: sqlite3.Connection,
    person: Person,
    position: RowPosition,
    *,
    base: int | None,
) -> None:
    """Upsert the row behind the version guard; a zero-row result is stale."""
    cursor = connection.execute(
        """INSERT INTO people (person_id, name, years, relation, bio, email, pronouns, hue, status,
                               dob_json, dod_json, aliases_json, occupations_json, basis_json,
                               version, event_no, event_seq, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (person_id) DO UPDATE SET
             name = excluded.name, years = excluded.years, relation = excluded.relation,
             bio = excluded.bio, email = excluded.email, pronouns = excluded.pronouns,
             hue = excluded.hue, status = excluded.status, dob_json = excluded.dob_json,
             dod_json = excluded.dod_json, aliases_json = excluded.aliases_json,
             occupations_json = excluded.occupations_json, basis_json = excluded.basis_json,
             version = excluded.version, event_no = excluded.event_no,
             event_seq = excluded.event_seq, updated_at = excluded.updated_at
           WHERE people.version IS ?""",
        (*to_row(person, position), base),
    )
    if cursor.rowcount == 0:
        current = read_row(connection, person.id)
        raise StaleVersion(current=current, base=base)
    _write_residences(connection, person)


def read_row(connection: sqlite3.Connection, person_id: str) -> Person | None:
    """The person a projection row holds, or None."""
    row = connection.execute("SELECT * FROM people WHERE person_id = ?", (person_id,)).fetchone()
    if row is None:
        return None
    return from_row(row, _residences(connection, person_id))


def _precision_of(text: str) -> str:
    return {4: "year", 7: "month", 10: "exact"}.get(len(text.strip()), "year")


def _write_residences(connection: sqlite3.Connection, person: Person) -> None:
    connection.execute("DELETE FROM person_residences WHERE person_id = ?", (person.id,))
    for residence in person.residence:
        place = str(residence.get("place", ""))
        start = str(residence.get("from", ""))
        end = str(residence.get("to", ""))
        status = str(residence.get("status", "confirmed"))
        connection.execute(
            """INSERT INTO person_residences (person_id, place_id, date_json, from_date, to_date,
                                              from_precision, to_precision, status, basis_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                person.id,
                place,
                json.dumps(date_value(start, "period", end or None), sort_keys=True),
                start,
                end or None,
                _precision_of(start),
                _precision_of(end) if end else None,
                status,
                None,
            ),
        )


def _residences(connection: sqlite3.Connection, person_id: str) -> list[dict[str, str]]:
    rows = connection.execute(
        "SELECT place_id, from_date, to_date, status FROM person_residences WHERE person_id = ? ORDER BY rowid",
        (person_id,),
    ).fetchall()
    return [
        {"place": row["place_id"], "from": row["from_date"], "to": row["to_date"] or "", "status": row["status"]}
        for row in rows
    ]


def from_row(row: sqlite3.Row, residences: list[dict[str, str]] | None = None) -> Person:
    def decoded(value: str | None) -> Any:
        return None if value is None else json.loads(value)

    raw: dict[str, Any] = {
        "id": row["person_id"],
        "name": row["name"],
        "years": row["years"] or "—",
        "relation": row["relation"] or "",
        "bio": row["bio"] or "",
        "status": row["status"],
        "aliases": decoded(row["aliases_json"]) or [],
        "occupations": decoded(row["occupations_json"]) or [],
    }
    if residences:
        raw["residence"] = residences
    for key, column in (("email", "email"), ("pronouns", "pronouns"), ("hue", "hue")):
        value = row[column]
        if value is not None:
            raw[key] = value
    for key, column in (("dob", "dob_json"), ("dod", "dod_json"), ("basis", "basis_json")):
        value = decoded(row[column])
        if value is not None:
            raw[key] = value
    return replace(Person.from_dict(raw), version=row["version"])
