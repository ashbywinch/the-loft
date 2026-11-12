"""The live store facade — the one public write and read seam.

TECHSPEC/08 §19.3: `with store.change(actor=...) as change:` is the only
write path; `store.people` reads current state; `rebuild_people` proves the
projection is derived. A2 exposes people and content only.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Self

from loft.live import person_row
from loft.live.change import Change
from loft.live.content import ContentStore
from loft.live.database import LiveDatabase
from loft.live.event import event_hash
from loft.live.people import People
from tools.records import Person


class LiveStore:
    """The SQLite live store: one connection, one writer, one change at a time."""

    def __init__(self, database: LiveDatabase, app_version: str) -> None:
        self.database = database
        self.app_version = app_version
        self.people = People(database.connection)
        self.content = ContentStore(database.connection)

    @classmethod
    def create(cls, path: Path, *, app_version: str) -> Self:
        return cls(LiveDatabase.create(path, app_version=app_version), app_version)

    @classmethod
    def open(cls, path: Path, *, app_version: str) -> Self:
        return cls(LiveDatabase.open(path), app_version)

    @property
    def connection(self) -> sqlite3.Connection:
        return self.database.connection

    def change(self, *, actor: str, note: str = "", command_id: str | None = None) -> Change:
        return Change(self.connection, actor=actor, app_version=self.app_version, note=note, command_id=command_id)

    def events_for(self, entity_id: str, *, entity_kind: str = "person") -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM events WHERE entity_kind = ? AND entity_id = ? ORDER BY seq",
            (entity_kind, entity_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def verify_chain(self) -> tuple[str, ...]:
        """Recompute every event's hash and its per-entity previous link."""
        findings: list[str] = []
        heads: dict[tuple[str, str], str] = {}
        for row in self.connection.execute("SELECT * FROM events ORDER BY seq"):
            event = dict(row)
            key = (event["entity_kind"], event["entity_id"])
            if event["hash"] != event_hash(event):
                findings.append(f"event {event['event_id']} hash does not match")
            if event["prev_hash"] != heads.get(key):
                findings.append(f"event {event['event_id']} prev_hash does not match the entity's head")
            heads[key] = event["hash"]
        return tuple(findings)

    def rebuild_people(self) -> None:
        """Drop the person projection and replay its events in seq order."""
        self.connection.execute("DELETE FROM people")
        for row in self.connection.execute("SELECT * FROM events WHERE entity_kind = 'person' ORDER BY seq").fetchall():
            event = dict(row)
            if event["entity_version"] is None:
                continue
            if event["event_type"] == "deleted":
                self.connection.execute("DELETE FROM people WHERE person_id = ?", (event["entity_id"],))
                continue
            person = Person.from_dict(json.loads(event["payload"]))
            current = person_row.read_row(self.connection, person.id)
            person_row.write_row(
                self.connection,
                person,
                person_row.RowPosition(
                    version=int(event["entity_version"]),
                    event_no=int(event["event_no"]),
                    event_seq=int(event["seq"]),
                    updated_at=event["recorded_at"],
                ),
                base=current.version if current is not None else None,
            )
        self.connection.commit()

    def close(self) -> None:
        self.database.close()
