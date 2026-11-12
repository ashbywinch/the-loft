"""The people collection — the repository both the store and a change expose.

TECHSPEC/08 §19.4: `store.people` reads current state; `change.people` writes
inside the change. One class owns both halves, so the collection has one name
and the write half cannot be used outside a transaction.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import TYPE_CHECKING

from loft.live import person_row
from loft.live.errors import Conflict, NotFound, StaleVersion
from tools.records import Person

if TYPE_CHECKING:
    from loft.live.change import Change


class People:
    """The person collection: read through the store, write through a change."""

    def __init__(self, connection: sqlite3.Connection, change: Change | None = None) -> None:
        self.connection = connection
        self.change = change

    def get(self, person_id: str) -> Person | None:
        return person_row.read_row(self.connection, person_id)

    def all(self) -> tuple[Person, ...]:
        rows = self.connection.execute("SELECT person_id FROM people ORDER BY person_id").fetchall()
        return tuple(self.require(row["person_id"]) for row in rows)

    def require(self, person_id: str) -> Person:
        person = self.get(person_id)
        if person is None:
            raise NotFound(f"no person {person_id}")
        return person

    def save(self, person: Person, base: int | None = None) -> Person:
        """Write a create (base None) or a supersede, version-checked."""
        if self.change is None:
            raise Conflict("people.save needs a change")
        current = self.get(person.id)
        if base is None:
            if current is not None:
                raise Conflict(f"person {person.id} exists")
            event_type = "created"
            version = 1
        else:
            if current is None:
                raise NotFound(f"no person {person.id}")
            if current.version != base:
                raise StaleVersion(current=current, base=base)
            event_type = "superseded"
            version = base + 1
        payload = json.dumps(person.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        event = self.change.append(
            entity_kind="person",
            entity_id=person.id,
            event_type=event_type,
            entity_version=version,
            payload=payload,
        )
        saved = replace(person, version=version)
        person_row.write_row(
            self.connection,
            saved,
            person_row.RowPosition(
                version=version,
                event_no=event["event_no"],
                event_seq=event["seq"],
                updated_at=event["recorded_at"],
            ),
            base=base,
        )
        return saved
