"""The person projection's row mapping — the domain type owns no SQL.

TECHSPEC/05 §18.4: scalar fields become columns, the small nested structures
JSON columns, and the shared version/event columns carry the projection's
position in the log. A2 projects people only.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
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


def _precision_of(text: str) -> str:
    return {4: "year", 7: "month", 10: "exact"}.get(len(text.strip()), "year")


@contextmanager
def _one_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Make the statements inside land together, or not at all.

    The connection is autocommit (``database.py`` opens it with
    ``isolation_level=None``), so without this the person row and its
    residences would commit separately and a failure between them would leave
    one half written. A caller already inside a transaction — a change's
    ``BEGIN IMMEDIATE``, the replay's — is joined, never nested (SQLite
    refuses a second ``BEGIN``); there the caller owns the commit and the
    rollback. This guard adds a rollback only when it opened the transaction
    itself, and lets every exception through either way.
    """
    owns = not connection.in_transaction
    if owns:
        connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        if owns:
            connection.execute("ROLLBACK")
        raise
    else:
        if owns:
            connection.execute("COMMIT")


class PersonProjection:
    """One connection's person rows: the reader, the guarded writer and the
    delete — the items' and pages' projection shape."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get(self, person_id: str) -> Person | None:
        """The person a projection row holds, or None."""
        row = self.connection.execute("SELECT * FROM people WHERE person_id = ?", (person_id,)).fetchone()
        if row is None:
            return None
        return from_row(row, self._residences(person_id))

    def write(self, person: Person, position: RowPosition, *, base: int | None) -> None:
        """Upsert the row behind the version guard, with its residences, as one unit.

        A zero-row result means the row moved or is gone: both are
        ``StaleVersion``, carrying the row as it now stands (``None`` when it
        is gone). ``People.save`` refuses a gone row as ``NotFound`` before it
        gets here, so a caller meets ``StaleVersion`` only for a version that
        changed underneath it.
        """
        with _one_transaction(self.connection):
            cursor = self.connection.execute(
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
                raise StaleVersion(current=self.get(person.id), base=base)
            self._replace_residences(person)

    def delete(self, person_id: str) -> None:
        """Remove the person and their residences — the delete determination,
        one unit: a refused person delete keeps the residences it would have
        orphaned."""
        with _one_transaction(self.connection):
            self.connection.execute("DELETE FROM person_residences WHERE person_id = ?", (person_id,))
            self.connection.execute("DELETE FROM people WHERE person_id = ?", (person_id,))

    def _replace_residences(self, person: Person) -> None:
        """Make the stored rows match the record's tuple: the record is the
        truth, so a residence it no longer lists is removed rather than left
        behind, and one it lists is written with the basis the record carries.
        """
        self.connection.execute("DELETE FROM person_residences WHERE person_id = ?", (person.id,))
        for residence in person.residence:
            place = str(residence.get("place", ""))
            start = str(residence.get("from", ""))
            end = str(residence.get("to", ""))
            status = str(residence.get("status", "confirmed"))
            # The residence's own basis, when its record carries one — writing
            # None unconditionally would drop provenance on every update.
            basis = residence.get("basis")
            self.connection.execute(
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
                    json.dumps(basis, sort_keys=True) if basis else None,
                ),
            )

    def _residences(self, person_id: str) -> list[dict[str, Any]]:
        """The person's residences as their records carried them.

        A residence's basis round-trips: the column is written from the record
        and read back here, so an update neither invents nor loses provenance.
        """
        rows = self.connection.execute(
            "SELECT place_id, from_date, to_date, status, basis_json"
            " FROM person_residences WHERE person_id = ? ORDER BY rowid",
            (person_id,),
        ).fetchall()
        residences: list[dict[str, Any]] = []
        for row in rows:
            residence: dict[str, Any] = {
                "place": row["place_id"],
                "from": row["from_date"],
                "to": row["to_date"] or "",
                "status": row["status"],
            }
            if row["basis_json"]:
                residence["basis"] = json.loads(row["basis_json"])
            residences.append(residence)
        return residences


def from_row(row: sqlite3.Row, residences: list[dict[str, Any]] | None = None) -> Person:
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
