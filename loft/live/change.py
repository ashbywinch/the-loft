"""The change — one transaction for one action (TECHSPEC/05 §18.5, 08 §19.3).

The caller supplies the domain change; the store derives the event kind,
writes the hash-chained event and the projection row in one transaction, and
rolls the whole thing back on an exception. No nested changes.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Self

from loft.live.content import ContentStore
from loft.live.errors import Conflict
from loft.live.event import event_hash
from loft.live.identity import ORG, PLACE, RELATIONSHIP, THEME, Collection
from loft.live.people import People


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Change:
    """One SQLite transaction: the event log, the projections and the content."""

    PAYLOAD_SCHEMA = 1

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        actor: str,
        app_version: str,
        note: str = "",
        command_id: str | None = None,
    ) -> None:
        self.connection = connection
        self.actor = actor
        self.app_version = app_version
        self.note = note
        self.command_id = command_id
        self.change_id = uuid.uuid4().hex
        self.content = ContentStore(connection)
        self.people = People(connection, change=self)
        self.places = Collection(connection, PLACE, change=self)
        self.orgs = Collection(connection, ORG, change=self)
        self.themes = Collection(connection, THEME, change=self)
        self.relationships = Collection(connection, RELATIONSHIP, change=self)
        self._entered = False

    def __enter__(self) -> Self:
        if self._entered:
            raise Conflict("a change cannot be nested")
        self.connection.execute("BEGIN IMMEDIATE")
        self._entered = True
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any) -> None:
        if exc_type is not None:
            self.connection.execute("ROLLBACK")
            return
        if self.command_id is not None:
            try:
                self.append(
                    entity_kind="command",
                    entity_id=self.command_id,
                    event_type="applied",
                    entity_version=None,
                    payload=json.dumps({"change_id": self.change_id}, sort_keys=True),
                )
            except sqlite3.IntegrityError as error:
                self.connection.execute("ROLLBACK")
                raise Conflict(f"command {self.command_id} already applied") from error
        self.connection.execute("COMMIT")

    def append(
        self,
        *,
        entity_kind: str,
        entity_id: str,
        event_type: str,
        entity_version: int | None,
        payload: str,
    ) -> dict[str, Any]:
        """Write one event for the entity, hash-chained to its predecessor."""
        head = self.connection.execute(
            """SELECT event_no, hash FROM events
               WHERE entity_kind = ? AND entity_id = ?
               ORDER BY seq DESC LIMIT 1""",
            (entity_kind, entity_id),
        ).fetchone()
        event_no = int(head["event_no"]) + 1 if head is not None else 1
        record: dict[str, Any] = {
            "event_id": uuid.uuid4().hex,
            "change_id": self.change_id,
            "entity_kind": entity_kind,
            "entity_id": entity_id,
            "event_no": event_no,
            "entity_version": entity_version,
            "event_type": event_type,
            "payload": payload,
            "payload_schema": self.PAYLOAD_SCHEMA,
            "recorded_at": _now(),
            "actor_kind": "system" if self.actor in {"pipeline", "sync", "import"} else "person",
            "actor_id": self.actor,
            "command_id": self.command_id,
            "app_version": self.app_version,
            "prev_hash": head["hash"] if head is not None else None,
        }
        record["hash"] = event_hash(record)
        cursor = self.connection.execute(
            """INSERT INTO events (event_id, change_id, entity_kind, entity_id, event_no,
                                   entity_version, event_type, payload, payload_schema, recorded_at,
                                   actor_kind, actor_id, command_id, app_version, prev_hash, hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(
                record[column]
                for column in (
                    "event_id",
                    "change_id",
                    "entity_kind",
                    "entity_id",
                    "event_no",
                    "entity_version",
                    "event_type",
                    "payload",
                    "payload_schema",
                    "recorded_at",
                    "actor_kind",
                    "actor_id",
                    "command_id",
                    "app_version",
                    "prev_hash",
                    "hash",
                )
            ),
        )
        record["seq"] = cursor.lastrowid
        return record
