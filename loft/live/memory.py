"""The in-memory live store — the same contract, no SQL (TECHSPEC/08 §19.7).

The contract suite runs against this and the SQLite store; the memory store
is what domain and pipeline tests use.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Self, cast

from loft.live import item_row
from loft.live.aliases import Alias, MemoryAliases
from loft.live.batch_row import BatchState, ScanState
from loft.live.batches import batch_from_payload, batch_payload
from loft.live.document_row import DocumentPage, DocumentState
from loft.live.documents import document_from_payload, document_payload
from loft.live.errors import Conflict, NotFound, StaleVersion
from loft.live.event import event_hash
from loft.live.identities import Identities
from loft.live.identity import ORG, PLACE, RELATIONSHIP, THEME, Kind, record_id, relationship_id
from loft.live.identity_map import BasisKinds, basis_after, renders_estimated
from loft.live.item_row import AssetRecord, ItemAsset, ItemContent, ItemRef
from loft.live.items import ContentInput, build_contents, item_payload, payload_assets, payload_contents
from loft.live.page_row import AdjustmentState, PageRow, PageState, ReadingState, reading_blob, reading_rows
from loft.live.pages import page_from_payload, page_payload
from loft.live.review_row import (
    ReviewDecisionRow,
    ReviewMessageRow,
    ReviewRow,
    ReviewSessionRow,
    session_from_payload,
    session_payload,
)
from tools.gone_person import GonePerson
from tools.records import Item, Person, Relationship, Session, split_content


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
        self._batches: dict[str, BatchState] = {}
        self._scans: dict[str, tuple[ScanState, ...]] = {}
        self._pages: dict[str, PageState] = {}
        self._readings: dict[str, ReadingState] = {}
        self._page_rows: dict[str, tuple[PageRow, ...]] = {}
        self._adjustments: dict[str, AdjustmentState] = {}
        self._documents: dict[str, DocumentState] = {}
        self._document_pages: dict[str, tuple[DocumentPage, ...]] = {}
        self._content: dict[str, bytes] = {}
        self._events: list[dict[str, Any]] = []
        self._applied: set[str] = set()
        self._aliases: dict[tuple[str, str], Alias] = {}
        self.lock = threading.RLock()
        self.people = _MemoryPeople(self)
        self.items = _MemoryItems(self)
        self.reviews = _MemoryReviews(self)
        self.batches = _MemoryBatches(self)
        self.pages = _MemoryPages(self)
        self.documents = _MemoryDocuments(self)
        self._collections: dict[str, dict[str, object]] = {kind.name: {} for kind in (PLACE, ORG, THEME, RELATIONSHIP)}
        self.places = _MemoryCollection(self, PLACE)
        self.orgs = _MemoryCollection(self, ORG)
        self.themes = _MemoryCollection(self, THEME)
        self.relationships = _MemoryCollection(self, RELATIONSHIP)
        self.aliases = MemoryAliases(self._aliases)
        self.content = MemoryContentStore(self._content)
        self.identities = Identities(self)

    def change(self, *, actor: str, note: str = "", command_id: str | None = None) -> _MemoryChange:
        return _MemoryChange(self, actor=actor, note=note, command_id=command_id, lock=self.lock)

    def creation_order(self, entity_kind: str, entity_ids: Any) -> list[str]:
        """The archive's own order for one collection: its create sequence."""
        first: dict[str, int] = {}
        for event in self._events:
            if event["entity_kind"] == entity_kind and event["entity_id"] in entity_ids:
                first.setdefault(event["entity_id"], int(event["seq"]))
        return sorted(entity_ids, key=lambda entity_id: (first.get(entity_id, 0), entity_id))

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
        """Replay the person events into a fresh projection (and aliases)."""
        rebuilt: dict[str, Person] = {}
        self._aliases.clear()
        for event in self._events:
            if event["entity_kind"] != "person" or event["entity_version"] is None:
                continue
            if event["event_type"] == "deleted":
                rebuilt.pop(event["entity_id"], None)
                continue
            payload = json.loads(event["payload"])
            if event["event_type"] == "merged":
                person = Person.from_dict(payload["person"])
                self._aliases[("person", event["entity_id"])] = Alias(
                    loser_kind="person",
                    loser_id=event["entity_id"],
                    survivor_kind="person",
                    survivor_id=str(payload["merged_into"]),
                    event_seq=int(event["seq"]),
                )
            else:
                person = Person.from_dict(payload)
            rebuilt[person.id] = replace(person, version=int(event["entity_version"]))
        self._people.clear()
        self._people.update(rebuilt)

    def rebuild_identities(self) -> None:
        """Replay the place/org/theme/relationship events into fresh collections."""
        kinds = {kind.entity_kind: kind for kind in (PLACE, ORG, THEME, RELATIONSHIP)}
        rebuilt: dict[str, dict[str, object]] = {kind.name: {} for kind in kinds.values()}
        for event in self._events:
            if event["entity_kind"] not in kinds or event["entity_version"] is None:
                continue
            kind = kinds[event["entity_kind"]]
            if event["event_type"] == "deleted":
                rebuilt[kind.name].pop(event["entity_id"], None)
                continue
            record = kind.from_payload(json.loads(event["payload"]))
            rebuilt[kind.name][record_id(kind, record)] = replace(record, version=int(event["entity_version"]))
        self._collections.clear()
        self._collections.update(rebuilt)

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

    def rebuild_pipeline(self) -> None:
        """Replay the batch/page/document events into fresh pipeline projections."""
        batches: dict[str, BatchState] = {}
        scans: dict[str, tuple[ScanState, ...]] = {}
        pages: dict[str, PageState] = {}
        readings: dict[str, ReadingState] = {}
        rows: dict[str, tuple[PageRow, ...]] = {}
        adjustments: dict[str, AdjustmentState] = {}
        documents: dict[str, DocumentState] = {}
        document_pages: dict[str, tuple[DocumentPage, ...]] = {}
        for event in self._events:
            if event["entity_kind"] not in ("batch", "page", "document") or event["entity_version"] is None:
                continue
            payload = json.loads(event["payload"])
            version = int(event["entity_version"])
            if event["entity_kind"] == "batch":
                batch, batch_scans = batch_from_payload(payload)
                batches[batch.batch_id] = replace(batch, version=version)
                scans[batch.batch_id] = batch_scans
            elif event["entity_kind"] == "page":
                bundle = page_from_payload(payload, self.content, version)
                pages[bundle.page.page_id] = bundle.page
                if bundle.reading is not None:
                    readings[bundle.page.page_id] = bundle.reading
                rows[bundle.page.page_id] = bundle.rows
                if bundle.adjustment is not None:
                    adjustments[bundle.page.page_id] = bundle.adjustment
            else:
                document, pages_order = document_from_payload(payload, version)
                documents[document.document_id] = document
                document_pages[document.document_id] = pages_order
        self._batches.clear()
        self._batches.update(batches)
        self._scans.clear()
        self._scans.update(scans)
        self._pages.clear()
        self._pages.update(pages)
        self._readings.clear()
        self._readings.update(readings)
        self._page_rows.clear()
        self._page_rows.update(rows)
        self._adjustments.clear()
        self._adjustments.update(adjustments)
        self._documents.clear()
        self._documents.update(documents)
        self._document_pages.clear()
        self._document_pages.update(document_pages)

    def rebuild_all(self) -> None:
        """Replay every projection from the event log — the rebuild gate."""
        self.rebuild_identities()
        self.rebuild_people()
        self.rebuild_items()
        self.rebuild_reviews()
        self.rebuild_pipeline()

    def close(self) -> None:
        return None


class _MemoryPeople:
    """The memory collection: read through the store, write through a change."""

    def __init__(self, store: MemoryLiveStore, change: _MemoryChange | None = None) -> None:
        self.store = store
        self.change = change

    def get(self, person_id: str) -> Person | None:
        return self.store._people.get(person_id)

    def all(self) -> tuple[Person, ...]:
        order = self.store.creation_order("person", self.store._people)
        return tuple(self.store._people[key] for key in order)

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

    def confirm(self, person_id: str, relation: str | None = None) -> Person:
        current = self.require(person_id)
        if current.status != "proposed":
            return current
        updated = replace(current, status="confirmed", basis=basis_after(current.basis, BasisKinds.KNOWN))
        if relation:
            updated = replace(updated, relation=relation)
        return self.save(updated, base=current.version)

    def promote(self, person_id: str) -> Person:
        current = self.require(person_id)
        if current.status != "proposed":
            raise Conflict(f"person {person_id} is {current.status}, not a proposal")
        return self.save(
            replace(current, status="confirmed", basis=basis_after(current.basis, BasisKinds.KNOWN)),
            base=current.version,
        )

    def resolve(self, person_id: str, decision: str, basis: dict[str, str] | None = None) -> Person | GonePerson | None:
        current = self.get(person_id)
        if current is None or current.status == "rejected":
            return current  # a rejected proposal is terminal (TECHSPEC/05 §18.2)
        if decision == "pending":
            return current
        if decision == "delete":
            self.delete(person_id)
            return GonePerson(person_id)
        if decision == "attested":
            if current.status != "proposed" and not renders_estimated(current.basis):
                return current
            updated = replace(current, status="confirmed", basis=basis_after(current.basis, BasisKinds.KNOWN))
        elif decision == "estimated":
            if basis is None or not str(basis.get("text", "")).strip():
                raise ValueError(f"estimated needs a basis: {person_id}")
            updated = replace(
                current, status="confirmed", basis=basis_after(current.basis, BasisKinds.RECOLLECTED, basis)
            )
        else:
            raise ValueError(f"unknown decision: {decision!r}")
        return current if updated == current else self.save(updated, base=current.version)

    def reject(self, person_id: str) -> Person:
        current = self.require(person_id)
        if current.status != "proposed":
            raise Conflict(f"person {person_id} is {current.status}, not a proposal")
        rejected, _ = self._write_event(replace(current, status="rejected"), "rejected")
        self._delete_edges(person_id)
        return rejected

    def delete(self, person_id: str) -> None:
        current = self.require(person_id)
        self._write_event(current, "deleted")
        self.store._people.pop(person_id, None)
        self._delete_edges(person_id)

    def merge(self, loser_id: str, survivor_id: str, by: str) -> Person:
        if loser_id == survivor_id:
            raise Conflict("a record cannot merge into itself")
        survivor = self.require(survivor_id)
        loser = self.require(loser_id)
        _, event = self._write_event(loser, "merged", extra={"merged_into": survivor_id, "by": by})
        self.store._aliases[("person", loser_id)] = Alias(
            loser_kind="person",
            loser_id=loser_id,
            survivor_kind="person",
            survivor_id=survivor_id,
            event_seq=int(event["seq"]),
        )
        self._move_edges(loser_id, survivor_id)
        return survivor

    def _move_edges(self, loser_id: str, survivor_id: str) -> None:
        if self.change is None:
            raise Conflict("people needs a change")
        for edge in cast(tuple[Relationship, ...], tuple(self.change.relationships.all())):
            if loser_id not in (edge.a, edge.b):
                continue
            moved = replace(
                edge,
                a=survivor_id if edge.a == loser_id else edge.a,
                b=survivor_id if edge.b == loser_id else edge.b,
            )
            self.change.relationships.delete(relationship_id(edge))
            self.change.relationships.save(moved)

    def _write_event(
        self, person: Person, event_type: str, extra: dict[str, Any] | None = None
    ) -> tuple[Person, dict[str, Any]]:
        if self.change is None:
            raise Conflict("people needs a change")
        version = person.version + 1
        record = replace(person, version=version)
        payload_record = {"person": record.to_dict(), **(extra or {})} if event_type == "merged" else record.to_dict()
        event = self.change.append(
            entity_kind="person",
            entity_id=person.id,
            event_type=event_type,
            entity_version=version,
            payload=json.dumps(payload_record, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        )
        if event_type != "deleted":
            self.store._people[person.id] = record
        return record, event

    def _delete_edges(self, person_id: str) -> None:
        if self.change is None:
            raise Conflict("people needs a change")
        for edge in cast(tuple[Relationship, ...], tuple(self.change.relationships.all())):
            if person_id in (edge.a, edge.b):
                self.change.relationships.delete(relationship_id(edge))


class _MemoryItems:
    """The item collection in memory, with the same aggregate and write rules."""

    def __init__(self, store: MemoryLiveStore, change: _MemoryChange | None = None) -> None:
        self.store = store
        self.change = change

    def get(self, item_id: str) -> Item | None:
        return self.store._items.get(item_id)

    def all(self) -> tuple[Item, ...]:
        return tuple(self.store._items[key] for key in sorted(self.store._items))

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


class _MemoryBatches:
    """The batch collection in memory, with the same rows and write rules."""

    def __init__(self, store: MemoryLiveStore, change: _MemoryChange | None = None) -> None:
        self.store = store
        self.change = change

    def get(self, batch_id: str) -> BatchState | None:
        return self.store._batches.get(batch_id)

    def all(self) -> tuple[BatchState, ...]:
        return tuple(self.store._batches[key] for key in sorted(self.store._batches))

    def require(self, batch_id: str) -> BatchState:
        batch = self.get(batch_id)
        if batch is None:
            raise NotFound(f"no batch {batch_id}")
        return batch

    def scans(self, batch_id: str) -> tuple[ScanState, ...]:
        return self.store._scans.get(batch_id, ())

    def save(self, batch: BatchState, scans: tuple[ScanState, ...] = (), *, base: int | None = None) -> BatchState:
        change = self.change
        if change is None:
            raise Conflict("batches.save needs a change")
        current = self.get(batch.batch_id)
        if base is None:
            if current is not None:
                raise Conflict(f"batch {batch.batch_id} exists")
            event_type = "created"
            version = 1
        else:
            if current is None:
                raise NotFound(f"no batch {batch.batch_id}")
            if current.version != base:
                raise StaleVersion(current=current, base=base)
            event_type = "superseded"
            version = base + 1
        change.append(
            entity_kind="batch",
            entity_id=batch.batch_id,
            event_type=event_type,
            entity_version=version,
            payload=batch_payload(batch, scans),
        )
        saved = replace(batch, version=version)
        self.store._batches[batch.batch_id] = saved
        self.store._scans[batch.batch_id] = scans
        return saved


class _MemoryPages:
    """The page collection in memory, with the same aggregate and write rules."""

    def __init__(self, store: MemoryLiveStore, change: _MemoryChange | None = None) -> None:
        self.store = store
        self.change = change

    def get(self, page_id: str) -> PageState | None:
        return self.store._pages.get(page_id)

    def require(self, page_id: str) -> PageState:
        page = self.get(page_id)
        if page is None:
            raise NotFound(f"no page {page_id}")
        return page

    def reading(self, page_id: str) -> ReadingState | None:
        return self.store._readings.get(page_id)

    def rows(self, page_id: str) -> tuple[PageRow, ...]:
        return self.store._page_rows.get(page_id, ())

    def adjustment(self, page_id: str) -> AdjustmentState | None:
        return self.store._adjustments.get(page_id)

    def reading_blob(self, page_id: str) -> dict[str, Any] | None:
        reading = self.reading(page_id)
        if reading is None:
            return None
        return json.loads(self.store.content.get(reading.reading_sha))

    def save(
        self,
        page: PageState,
        *,
        base: int | None = None,
        reading: dict[str, Any] | None = None,
        adjustment: bytes | None = None,
        adjustment_at: str = "",
    ) -> PageState:
        change = self.change
        if change is None:
            raise Conflict("pages.save needs a change")
        current = self.get(page.page_id)
        if base is None:
            if current is not None:
                raise Conflict(f"page {page.page_id} exists")
            event_type = "created"
            version = page.revision if page.revision > 0 else 1
        else:
            if current is None:
                raise NotFound(f"no page {page.page_id}")
            if current.revision != base:
                raise StaleVersion(current=current, base=base)
            event_type = "superseded"
            version = base + 1
        reading_state: ReadingState | None = None
        rows: tuple[PageRow, ...] = ()
        if reading is not None:
            blob = reading_blob(
                page.page_id,
                reading,
                list(reading.get("words") or []),
                rotation=page.rotation,
                revision=version,
            )
            sha = change.content.put(
                json.dumps(blob, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
                mime="application/json",
            )
            corrected = str(blob.get("corrected", ""))
            rows = reading_rows(page.page_id, blob, revision=version, corrected=bool(corrected))
            reading_state = ReadingState(page.page_id, sha, corrected, len(rows), len(blob.get("words") or []))
        adjustment_state: AdjustmentState | None = None
        if adjustment is not None:
            adjustment_state = AdjustmentState(
                page.page_id,
                change.content.put(adjustment, mime="application/json"),
                adjustment_at,
            )
        change.append(
            entity_kind="page",
            entity_id=page.page_id,
            event_type=event_type,
            entity_version=version,
            payload=page_payload(replace(page, revision=version), reading_state, adjustment_state),
        )
        saved = replace(page, revision=version)
        self.store._pages[page.page_id] = saved
        if reading_state is not None:
            self.store._readings[page.page_id] = reading_state
        self.store._page_rows[page.page_id] = rows
        if adjustment_state is not None:
            self.store._adjustments[page.page_id] = adjustment_state
        return saved


class _MemoryDocuments:
    """The document collection in memory, with the same rows and write rules."""

    def __init__(self, store: MemoryLiveStore, change: _MemoryChange | None = None) -> None:
        self.store = store
        self.change = change

    def get(self, document_id: str) -> DocumentState | None:
        return self.store._documents.get(document_id)

    def require(self, document_id: str) -> DocumentState:
        document = self.get(document_id)
        if document is None:
            raise NotFound(f"no document {document_id}")
        return document

    def pages(self, document_id: str) -> tuple[DocumentPage, ...]:
        return self.store._document_pages.get(document_id, ())

    def for_batch(self, batch_id: str) -> tuple[DocumentState, ...]:
        return tuple(
            sorted(
                (document for document in self.store._documents.values() if document.batch_id == batch_id),
                key=lambda document: document.doc_index,
            )
        )

    def all(self) -> tuple[DocumentState, ...]:
        return tuple(self.store._documents[key] for key in sorted(self.store._documents))

    def save(
        self,
        document: DocumentState,
        pages: tuple[str, ...],
        *,
        base: int | None = None,
        text: str | None = None,
    ) -> DocumentState:
        change = self.change
        if change is None:
            raise Conflict("documents.save needs a change")
        current = self.get(document.document_id)
        if base is None:
            if current is not None:
                raise Conflict(f"document {document.document_id} exists")
            event_type = "created"
            version = 1
        else:
            if current is None:
                raise NotFound(f"no document {document.document_id}")
            if current.version != base:
                raise StaleVersion(current=current, base=base)
            event_type = "superseded"
            version = base + 1
        if document.status == "confirmed" and not document.item_id:
            raise Conflict(f"document {document.document_id} is confirmed without an item")
        text_sha = document.text_sha
        if text is not None:
            text_sha = change.content.put(text.encode("utf-8"), mime="text/plain")
        saved = replace(document, text_sha=text_sha, version=version)
        change.append(
            entity_kind="document",
            entity_id=document.document_id,
            event_type=event_type,
            entity_version=version,
            payload=document_payload(saved, pages),
        )
        self.store._documents[document.document_id] = saved
        self.store._document_pages[document.document_id] = tuple(
            DocumentPage(document_id=document.document_id, page_id=page_id, ordinal=index)
            for index, page_id in enumerate(pages)
        )
        return saved


class _MemoryChange:
    def __init__(
        self,
        store: MemoryLiveStore,
        *,
        actor: str,
        note: str,
        command_id: str | None,
        lock: threading.RLock | None = None,
    ) -> None:
        self.store = store
        self.actor = actor
        self.note = note
        self.command_id = command_id
        self.lock = lock if lock is not None else threading.RLock()
        self.change_id = uuid.uuid4().hex
        self.content = store.content
        self.items = _MemoryItems(store, change=self)
        self.reviews = _MemoryReviews(store, change=self)
        self.batches = _MemoryBatches(store, change=self)
        self.pages = _MemoryPages(store, change=self)
        self.documents = _MemoryDocuments(store, change=self)
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
        self._batches: dict[str, BatchState] | None = None
        self._scans: dict[str, tuple[ScanState, ...]] | None = None
        self._pages: dict[str, PageState] | None = None
        self._readings: dict[str, ReadingState] | None = None
        self._page_rows: dict[str, tuple[PageRow, ...]] | None = None
        self._adjustments: dict[str, AdjustmentState] | None = None
        self._documents: dict[str, DocumentState] | None = None
        self._document_pages: dict[str, tuple[DocumentPage, ...]] | None = None
        self._content: dict[str, bytes] | None = None
        self._events: list[dict[str, Any]] | None = None
        self._applied: set[str] | None = None
        self._aliases: dict[tuple[str, str], Alias] | None = None
        self._collections: dict[str, dict[str, object]] = {}

    def __enter__(self) -> Self:
        self.lock.acquire()
        self._people = dict(self.store._people)
        self._items = dict(self.store._items)
        self._item_refs = dict(self.store._item_refs)
        self._item_assets = dict(self.store._item_assets)
        self._item_contents = dict(self.store._item_contents)
        self._assets = dict(self.store._assets)
        self._review_sessions = dict(self.store._review_sessions)
        self._review_messages = dict(self.store._review_messages)
        self._review_decisions = dict(self.store._review_decisions)
        self._batches = dict(self.store._batches)
        self._scans = dict(self.store._scans)
        self._pages = dict(self.store._pages)
        self._readings = dict(self.store._readings)
        self._page_rows = dict(self.store._page_rows)
        self._adjustments = dict(self.store._adjustments)
        self._documents = dict(self.store._documents)
        self._document_pages = dict(self.store._document_pages)
        self._content = dict(self.store._content)
        self._events = list(self.store._events)
        self._applied = set(self.store._applied)
        self._aliases = dict(self.store._aliases)
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
        assert self._batches is not None and self._scans is not None
        assert self._pages is not None and self._readings is not None
        assert self._page_rows is not None and self._adjustments is not None
        assert self._documents is not None and self._document_pages is not None
        self.store._batches.clear()
        self.store._batches.update(self._batches)
        self.store._scans.clear()
        self.store._scans.update(self._scans)
        self.store._pages.clear()
        self.store._pages.update(self._pages)
        self.store._readings.clear()
        self.store._readings.update(self._readings)
        self.store._page_rows.clear()
        self.store._page_rows.update(self._page_rows)
        self.store._adjustments.clear()
        self.store._adjustments.update(self._adjustments)
        self.store._documents.clear()
        self.store._documents.update(self._documents)
        self.store._document_pages.clear()
        self.store._document_pages.update(self._document_pages)
        self.store._content.clear()
        self.store._content.update(self._content)
        self.store._events[:] = self._events
        self.store._applied.clear()
        self.store._applied.update(self._applied)
        assert self._aliases is not None
        self.store._aliases.clear()
        self.store._aliases.update(self._aliases)
        self.store._collections.clear()
        self.store._collections.update({name: dict(records) for name, records in self._collections.items()})

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any) -> None:
        try:
            if exc_type is not None:
                self._restore()
                return
            if self.command_id is not None:
                if self.command_id in self.store._applied:
                    self._restore()
                    raise Conflict(f"command {self.command_id} already applied")
                self.store._applied.add(self.command_id)
        finally:
            self.lock.release()

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

    def all(self) -> tuple[object, ...]:
        order = self.store.creation_order(self.kind.entity_kind, self.records)
        return tuple(self.records[key] for key in order)

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

    def promote(self, entity_id: str) -> Any:
        current: Any = self.require(entity_id)
        if self.status(current) != "proposed":
            raise Conflict(f"{self.kind.name[:-1]} {entity_id} is {self.status(current)}, not a proposal")
        return self.save(self._with_status(current, "confirmed", confirm_basis=True), base=current.version)

    def reject(self, entity_id: str) -> Any:
        current: Any = self.require(entity_id)
        if self.status(current) != "proposed":
            raise Conflict(f"{self.kind.name[:-1]} {entity_id} is {self.status(current)}, not a proposal")
        return self.save(self._with_status(current, "rejected"), base=current.version)

    def delete(self, entity_id: str) -> None:
        current: Any = self.require(entity_id)
        if self.change is None:
            raise Conflict(f"{self.kind.name} needs a change")
        self.change.append(
            entity_kind=self.kind.entity_kind,
            entity_id=entity_id,
            event_type="deleted",
            entity_version=current.version + 1,
            payload=json.dumps(current.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        )
        self.records.pop(entity_id, None)

    @staticmethod
    def status(record: Any) -> str:
        return str(record.to_dict().get("status", "confirmed"))

    def _with_status(self, record: Any, status: str, *, confirm_basis: bool = False) -> Any:
        raw = record.to_dict()
        raw["status"] = status
        if confirm_basis and raw.get("basis"):
            raw["basis"] = basis_after(raw["basis"], BasisKinds.KNOWN)
        return replace(self.kind.from_payload(raw), version=record.version)
