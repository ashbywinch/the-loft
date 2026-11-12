"""The in-memory live store — the same contract, no SQL (TECHSPEC/08 §19.7).

The contract suite runs against this and the SQLite store; the memory store
is what domain and pipeline tests use.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Self

from loft.live.errors import Conflict, NotFound, StaleVersion
from loft.live.event import event_hash
from loft.live.identity import ORG, PLACE, RELATIONSHIP, THEME, Kind, record_id
from tools.records import Person


class MemoryContentStore:
    """The content store's memory twin."""

    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs

    def put(self, data: bytes, *, mime: str = "application/octet-stream") -> str:
        sha = hashlib.sha256(data).hexdigest()
        if sha in self.blobs and self.blobs[sha] != data:
            raise Conflict(f"content {sha} exists with different bytes")
        self.blobs[sha] = data
        return sha

    def get(self, sha: str) -> bytes:
        if sha not in self.blobs:
            raise NotFound(f"no content {sha}")
        return self.blobs[sha]

    def has(self, sha: str) -> bool:
        return sha in self.blobs


class MemoryLiveStore:
    """The memory store: dicts and a list, the same facade as LiveStore."""

    def __init__(self, *, app_version: str = "test") -> None:
        self.app_version = app_version
        self._people: dict[str, Person] = {}
        self._content: dict[str, bytes] = {}
        self._events: list[dict[str, Any]] = []
        self._applied: set[str] = set()
        self.people = _MemoryPeople(self)
        self._collections: dict[str, dict[str, object]] = {kind.name: {} for kind in (PLACE, ORG, THEME, RELATIONSHIP)}
        self.places = _MemoryCollection(self, PLACE)
        self.orgs = _MemoryCollection(self, ORG)
        self.themes = _MemoryCollection(self, THEME)
        self.relationships = _MemoryCollection(self, RELATIONSHIP)
        self.content = MemoryContentStore(self._content)

    def change(self, *, actor: str, note: str = "", command_id: str | None = None) -> _MemoryChange:
        return _MemoryChange(self, actor=actor, note=note, command_id=command_id)

    def events_for(self, entity_id: str, *, entity_kind: str = "person") -> list[dict]:
        return [e for e in self._events if e["entity_kind"] == entity_kind and e["entity_id"] == entity_id]

    def verify_chain(self) -> tuple[str, ...]:
        findings: list[str] = []
        heads: dict[tuple[str, str], str] = {}
        for event in self._events:
            key = (event["entity_kind"], event["entity_id"])
            if event["hash"] != event_hash(event):
                findings.append(f"event {event['event_id']} hash does not match")
            if event["prev_hash"] != heads.get(key):
                findings.append(f"event {event['event_id']} prev_hash does not match the entity's head")
            heads[key] = event["hash"]
        return tuple(findings)

    def rebuild_people(self) -> None:
        """Replay the person events into a fresh projection."""
        rebuilt: dict[str, Person] = {}
        for event in self._events:
            if event["entity_kind"] != "person" or event["entity_version"] is None:
                continue
            if event["event_type"] == "deleted":
                rebuilt.pop(event["entity_id"], None)
                continue
            rebuilt[event["entity_id"]] = replace(
                Person.from_dict(json.loads(event["payload"])), version=int(event["entity_version"])
            )
        self._people.clear()
        self._people.update(rebuilt)

    def close(self) -> None:
        return None


class _MemoryPeople:
    """The memory collection: read through the store, write through a change."""

    def __init__(self, store: MemoryLiveStore, change: _MemoryChange | None = None) -> None:
        self.store = store
        self.change = change

    def get(self, person_id: str) -> Person | None:
        return self.store._people.get(person_id)

    def require(self, person_id: str) -> Person:
        person = self.get(person_id)
        if person is None:
            raise NotFound(f"no person {person_id}")
        return person

    def save(self, person: Person, base: int | None = None) -> Person:
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
        self.change.append(
            entity_kind="person",
            entity_id=person.id,
            event_type=event_type,
            entity_version=version,
            payload=payload,
        )
        saved = replace(person, version=version)
        self.store._people[person.id] = saved
        return saved


class _MemoryChange:
    def __init__(self, store: MemoryLiveStore, *, actor: str, note: str, command_id: str | None) -> None:
        self.store = store
        self.actor = actor
        self.note = note
        self.command_id = command_id
        self.change_id = uuid.uuid4().hex
        self.content = store.content
        self.people = _MemoryPeople(store, change=self)
        self.places = _MemoryCollection(store, PLACE, change=self)
        self.orgs = _MemoryCollection(store, ORG, change=self)
        self.themes = _MemoryCollection(store, THEME, change=self)
        self.relationships = _MemoryCollection(store, RELATIONSHIP, change=self)
        self._people: dict[str, Person] | None = None
        self._content: dict[str, bytes] | None = None
        self._events: list[dict[str, Any]] | None = None
        self._applied: set[str] | None = None
        self._collections: dict[str, dict[str, object]] = {}

    def __enter__(self) -> Self:
        self._people = dict(self.store._people)
        self._content = dict(self.store._content)
        self._events = list(self.store._events)
        self._applied = set(self.store._applied)
        self._collections = {name: dict(records) for name, records in self.store._collections.items()}
        return self

    def _restore(self) -> None:
        assert self._people is not None and self._content is not None
        assert self._events is not None and self._applied is not None
        self.store._people.clear()
        self.store._people.update(self._people)
        self.store._content.clear()
        self.store._content.update(self._content)
        self.store._events[:] = self._events
        self.store._applied.clear()
        self.store._applied.update(self._applied)
        self.store._collections.clear()
        self.store._collections.update({name: dict(records) for name, records in self._collections.items()})

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any) -> None:
        if exc_type is not None:
            self._restore()
            return
        if self.command_id is not None:
            if self.command_id in self.store._applied:
                self._restore()
                raise Conflict(f"command {self.command_id} already applied")
            self.store._applied.add(self.command_id)

    def append(
        self,
        *,
        entity_kind: str,
        entity_id: str,
        event_type: str,
        entity_version: int | None,
        payload: str,
    ) -> dict[str, Any]:
        head = next(
            (
                e
                for e in reversed(self.store._events)
                if e["entity_kind"] == entity_kind and e["entity_id"] == entity_id
            ),
            None,
        )
        event: dict[str, Any] = {
            "seq": len(self.store._events) + 1,
            "event_id": uuid.uuid4().hex,
            "change_id": self.change_id,
            "entity_kind": entity_kind,
            "entity_id": entity_id,
            "event_no": (int(head["event_no"]) + 1) if head is not None else 1,
            "entity_version": entity_version,
            "event_type": event_type,
            "payload": payload,
            "payload_schema": 1,
            "recorded_at": datetime.now(UTC).isoformat(),
            "actor_kind": "system" if self.actor in {"pipeline", "sync", "import"} else "person",
            "actor_id": self.actor,
            "command_id": self.command_id,
            "app_version": self.store.app_version,
            "prev_hash": head["hash"] if head is not None else None,
        }
        event["hash"] = event_hash(event)
        self.store._events.append(event)
        return event


class _MemoryCollection:
    """One identity collection in memory, with the same write rules."""

    def __init__(self, store: MemoryLiveStore, kind: Kind, change: _MemoryChange | None = None) -> None:
        self.store = store
        self.kind = kind
        self.change = change

    @property
    def records(self) -> dict[str, object]:
        return self.store._collections[self.kind.name]

    def get(self, entity_id: str) -> object | None:
        return self.records.get(entity_id)

    def require(self, entity_id: str) -> object:
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
            if getattr(current, "version", 0) != base:
                raise StaleVersion(current=current, base=base)
            event_type = "superseded"
            version = base + 1
        payload = json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.change.append(
            entity_kind=self.kind.entity_kind,
            entity_id=entity_id,
            event_type=event_type,
            entity_version=version,
            payload=payload,
        )
        saved = replace(record, version=version)
        self.records[entity_id] = saved
        return saved
