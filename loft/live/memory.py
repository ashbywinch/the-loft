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

from loft.live import item_row
from loft.live.errors import Conflict, NotFound, StaleVersion
from loft.live.event import event_hash
from loft.live.identity import ORG, PLACE, RELATIONSHIP, THEME, Kind, record_id
from loft.live.item_row import AssetRecord, ItemAsset, ItemContent, ItemRef
from loft.live.items import ContentInput, build_contents, item_payload, payload_assets, payload_contents
from loft.live.review_row import (
    ReviewDecisionRow,
    ReviewMessageRow,
    ReviewRow,
    ReviewSessionRow,
    session_from_payload,
    session_payload,
)
from tools.records import Item, Person, Session, split_content


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
        self._items: dict[str, Item] = {}
        self._item_refs: dict[str, tuple[ItemRef, ...]] = {}
        self._item_assets: dict[str, tuple[ItemAsset, ...]] = {}
        self._item_contents: dict[str, tuple[ItemContent, ...]] = {}
        self._assets: dict[str, AssetRecord] = {}
        self._review_sessions: dict[str, ReviewSessionRow] = {}
        self._review_messages: dict[str, tuple[ReviewMessageRow, ...]] = {}
        self._review_decisions: dict[str, tuple[ReviewDecisionRow, ...]] = {}
        self._content: dict[str, bytes] = {}
        self._events: list[dict[str, Any]] = []
        self._applied: set[str] = set()
        self.people = _MemoryPeople(self)
        self.items = _MemoryItems(self)
        self.reviews = _MemoryReviews(self)
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

    def rebuild_items(self) -> None:
        """Replay the item events into fresh item projections and catalog."""
        rebuilt: dict[str, Item] = {}
        refs: dict[str, tuple[ItemRef, ...]] = {}
        edges: dict[str, tuple[ItemAsset, ...]] = {}
        contents: dict[str, tuple[ItemContent, ...]] = {}
        catalog: dict[str, AssetRecord] = {}
        for event in self._events:
            if event["entity_kind"] != "item" or event["entity_version"] is None:
                continue
            payload = json.loads(event["payload"])
            item = Item.from_dict(payload["item"])
            records = tuple(replace(record, event_seq=event["seq"]) for record in payload_assets(payload))
            rebuilt[item.id] = replace(item, version=int(event["entity_version"]))
            refs[item.id] = item_row.ItemRow.refs(item)
            edges[item.id] = item_row.ItemRow.assets(item, records)
            contents[item.id] = payload_contents(payload)
            catalog.update({record.asset_id: record for record in records})
        self._items.clear()
        self._items.update(rebuilt)
        self._item_refs.clear()
        self._item_refs.update(refs)
        self._item_assets.clear()
        self._item_assets.update(edges)
        self._item_contents.clear()
        self._item_contents.update(contents)
        self._assets.clear()
        self._assets.update(catalog)

    def rebuild_reviews(self) -> None:
        """Replay the session events into fresh review projections."""
        sessions: dict[str, ReviewSessionRow] = {}
        messages: dict[str, tuple[ReviewMessageRow, ...]] = {}
        decisions: dict[str, tuple[ReviewDecisionRow, ...]] = {}
        for event in self._events:
            if event["entity_kind"] != "review_session" or event["entity_version"] is None:
                continue
            session, thinking = session_from_payload(json.loads(event["payload"]))
            rows = ReviewRow.build(session, thinking)
            sessions[session.id] = replace(rows.session, version=int(event["entity_version"]))
            messages[session.id] = rows.messages
            decisions[session.id] = rows.decisions
        self._review_sessions.clear()
        self._review_sessions.update(sessions)
        self._review_messages.clear()
        self._review_messages.update(messages)
        self._review_decisions.clear()
        self._review_decisions.update(decisions)

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


class _MemoryItems:
    """The item collection in memory, with the same aggregate and write rules."""

    def __init__(self, store: MemoryLiveStore, change: _MemoryChange | None = None) -> None:
        self.store = store
        self.change = change

    def get(self, item_id: str) -> Item | None:
        return self.store._items.get(item_id)

    def require(self, item_id: str) -> Item:
        item = self.get(item_id)
        if item is None:
            raise NotFound(f"no item {item_id}")
        return item

    def refs(self, item_id: str) -> tuple[ItemRef, ...]:
        return self.store._item_refs.get(item_id, ())

    def assets(self, item_id: str) -> tuple[ItemAsset, ...]:
        return self.store._item_assets.get(item_id, ())

    def asset(self, asset_id: str) -> AssetRecord | None:
        return self.store._assets.get(asset_id)

    def contents(self, item_id: str) -> tuple[ItemContent, ...]:
        return self.store._item_contents.get(item_id, ())

    def content_sha(self, item_id: str, kind: str) -> str | None:
        for content in self.contents(item_id):
            if content.kind == kind:
                return content.sha256
        return None

    def content(self, item_id: str, kind: str) -> bytes | None:
        sha = self.content_sha(item_id, kind)
        return None if sha is None else self.store.content.get(sha)

    def save(
        self,
        item: Item,
        *,
        base: int | None = None,
        content: tuple[ContentInput, ...] = (),
        files: dict[str, bytes] | None = None,
    ) -> Item:
        change = self.change
        if change is None:
            raise Conflict("items.save needs a change")
        split = split_content(item)
        sidecar = split.sidecar
        current = self.get(sidecar.id)
        if base is None:
            if current is not None:
                raise Conflict(f"item {sidecar.id} exists")
            event_type = "deleted" if sidecar.status == "deleted" else "created"
            version = 1
        else:
            if current is None:
                raise NotFound(f"no item {sidecar.id}")
            if current.version != base:
                raise StaleVersion(current=current, base=base)
            event_type = "deleted" if sidecar.status == "deleted" else "superseded"
            version = base + 1
        contents = build_contents(change.content, sidecar, split.content, content)
        supplied = files or {}
        catalog: list[AssetRecord] = []
        for asset in sidecar.assets:
            data = supplied.get(asset.file)
            if data is None:
                raise Conflict(f"item {sidecar.id} has no bytes for asset {asset.file}")
            record = item_row.ItemRow.catalog_entry(sidecar.id, asset, data, 0)
            existing = self.store._assets.get(record.asset_id)
            if existing is not None:
                if (
                    existing.sha256,
                    existing.kind,
                    existing.mime,
                    existing.size,
                    existing.path,
                ) != (record.sha256, record.kind, record.mime, record.size, record.path):
                    raise Conflict(f"asset {record.asset_id} exists with different bytes")
                record = existing
            catalog.append(record)
        change.append(
            entity_kind="item",
            entity_id=sidecar.id,
            event_type=event_type,
            entity_version=version,
            payload=item_payload(sidecar, contents, tuple(catalog)),
        )
        saved = replace(sidecar, version=version)
        self.store._items[sidecar.id] = saved
        self.store._item_refs[sidecar.id] = item_row.ItemRow.refs(sidecar)
        self.store._item_assets[sidecar.id] = item_row.ItemRow.assets(sidecar, tuple(catalog))
        self.store._item_contents[sidecar.id] = contents
        self.store._assets.update({record.asset_id: record for record in catalog})
        return saved


class _MemoryReviews:
    """The review sessions in memory, with the same rows and write rules."""

    def __init__(self, store: MemoryLiveStore, change: _MemoryChange | None = None) -> None:
        self.store = store
        self.change = change

    def get(self, session_id: str) -> ReviewSessionRow | None:
        return self.store._review_sessions.get(session_id)

    def require(self, session_id: str) -> ReviewSessionRow:
        session = self.get(session_id)
        if session is None:
            raise NotFound(f"no review session {session_id}")
        return session

    def messages(self, session_id: str) -> tuple[ReviewMessageRow, ...]:
        return self.store._review_messages.get(session_id, ())

    def decisions(self, session_id: str) -> tuple[ReviewDecisionRow, ...]:
        return self.store._review_decisions.get(session_id, ())

    def thinking(self, session_id: str, ordinal: int) -> bytes | None:
        for message in self.messages(session_id):
            if message.ordinal == ordinal and message.thinking_sha is not None:
                return self.store.content.get(message.thinking_sha)
        return None

    def save(self, session: Session, *, base: int | None = None) -> Session:
        change = self.change
        if change is None:
            raise Conflict("reviews.save needs a change")
        current = self.get(session.id)
        if base is None:
            if current is not None:
                raise Conflict(f"review session {session.id} exists")
            event_type = "created"
            version = 1
        else:
            if current is None:
                raise NotFound(f"no review session {session.id}")
            if current.version != base:
                raise StaleVersion(current=current, base=base)
            event_type = "superseded"
            version = base + 1
        thinking: dict[str, str] = {}
        for attempt_index, attempt in enumerate(session.attempts):
            for message_index, message in enumerate(attempt.messages):
                if message.thinking:
                    thinking[ReviewRow.thinking_key(attempt_index, message_index)] = change.content.put(
                        message.thinking.encode("utf-8"), mime="text/plain"
                    )
        change.append(
            entity_kind="review_session",
            entity_id=session.id,
            event_type=event_type,
            entity_version=version,
            payload=session_payload(session, thinking),
        )
        saved = replace(session, version=version)
        rows = ReviewRow.build(saved, thinking)
        self.store._review_sessions[session.id] = replace(rows.session, version=version)
        self.store._review_messages[session.id] = rows.messages
        self.store._review_decisions[session.id] = rows.decisions
        return saved


class _MemoryChange:
    def __init__(self, store: MemoryLiveStore, *, actor: str, note: str, command_id: str | None) -> None:
        self.store = store
        self.actor = actor
        self.note = note
        self.command_id = command_id
        self.change_id = uuid.uuid4().hex
        self.content = store.content
        self.items = _MemoryItems(store, change=self)
        self.reviews = _MemoryReviews(store, change=self)
        self.people = _MemoryPeople(store, change=self)
        self.places = _MemoryCollection(store, PLACE, change=self)
        self.orgs = _MemoryCollection(store, ORG, change=self)
        self.themes = _MemoryCollection(store, THEME, change=self)
        self.relationships = _MemoryCollection(store, RELATIONSHIP, change=self)
        self._people: dict[str, Person] | None = None
        self._items: dict[str, Item] | None = None
        self._item_refs: dict[str, tuple[ItemRef, ...]] | None = None
        self._item_assets: dict[str, tuple[ItemAsset, ...]] | None = None
        self._item_contents: dict[str, tuple[ItemContent, ...]] | None = None
        self._assets: dict[str, AssetRecord] | None = None
        self._review_sessions: dict[str, ReviewSessionRow] | None = None
        self._review_messages: dict[str, tuple[ReviewMessageRow, ...]] | None = None
        self._review_decisions: dict[str, tuple[ReviewDecisionRow, ...]] | None = None
        self._content: dict[str, bytes] | None = None
        self._events: list[dict[str, Any]] | None = None
        self._applied: set[str] | None = None
        self._collections: dict[str, dict[str, object]] = {}

    def __enter__(self) -> Self:
        self._people = dict(self.store._people)
        self._items = dict(self.store._items)
        self._item_refs = dict(self.store._item_refs)
        self._item_assets = dict(self.store._item_assets)
        self._item_contents = dict(self.store._item_contents)
        self._assets = dict(self.store._assets)
        self._review_sessions = dict(self.store._review_sessions)
        self._review_messages = dict(self.store._review_messages)
        self._review_decisions = dict(self.store._review_decisions)
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
        assert self._items is not None and self._item_refs is not None
        assert self._item_assets is not None and self._item_contents is not None
        assert self._assets is not None
        self.store._items.clear()
        self.store._items.update(self._items)
        self.store._item_refs.clear()
        self.store._item_refs.update(self._item_refs)
        self.store._item_assets.clear()
        self.store._item_assets.update(self._item_assets)
        self.store._item_contents.clear()
        self.store._item_contents.update(self._item_contents)
        self.store._assets.clear()
        self.store._assets.update(self._assets)
        assert self._review_sessions is not None and self._review_messages is not None
        assert self._review_decisions is not None
        self.store._review_sessions.clear()
        self.store._review_sessions.update(self._review_sessions)
        self.store._review_messages.clear()
        self.store._review_messages.update(self._review_messages)
        self.store._review_decisions.clear()
        self.store._review_decisions.update(self._review_decisions)
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
