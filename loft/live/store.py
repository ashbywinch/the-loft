"""The live store facade — the one public write and read seam.

TECHSPEC/08 §19.3: `with store.change(actor=...) as change:` is the only
write path; `store.people` reads current state; `rebuild_people` proves the
projection is derived. A2 exposes people and content only.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path
from typing import Self

from loft.live import item_row, person_row
from loft.live.aliases import Aliases
from loft.live.batch_row import BatchBundle, BatchProjection
from loft.live.batches import Batches, batch_from_payload
from loft.live.change import Change, ChangeContext
from loft.live.content import ContentStore
from loft.live.database import LiveDatabase
from loft.live.document_row import DocumentBundle, DocumentProjection
from loft.live.documents import Documents, document_from_payload
from loft.live.event import event_hash
from loft.live.identities import Identities
from loft.live.identity import ORG, PLACE, RELATIONSHIP, THEME, Collection, Kind
from loft.live.item_row import RowPosition
from loft.live.items import Items, payload_assets, payload_contents
from loft.live.page_row import PageProjection
from loft.live.pages import Pages, page_from_payload
from loft.live.people import People
from loft.live.review_row import ReviewProjection, ReviewRow, session_from_payload
from loft.live.reviews import Reviews
from tools.records import Item, Person


class LiveStore:
    """The SQLite live store: one connection, one writer, one change at a time."""

    IDENTITY_KINDS: tuple[Kind, ...] = (PLACE, ORG, THEME, RELATIONSHIP)

    def __init__(self, database: LiveDatabase, app_version: str) -> None:
        self.database = database
        self.app_version = app_version
        self.lock = threading.RLock()
        content = ContentStore(database.connection)
        self.people = People(database.connection)
        self.items = Items(database.connection, content)
        self.reviews = Reviews(database.connection, content)
        self.batches = Batches(database.connection)
        self.pages = Pages(database.connection, content)
        self.documents = Documents(database.connection)
        self.places = Collection(database.connection, PLACE)
        self.orgs = Collection(database.connection, ORG)
        self.themes = Collection(database.connection, THEME)
        self.relationships = Collection(database.connection, RELATIONSHIP)
        self.aliases = Aliases(database.connection)
        self.identities = Identities(self)
        self.content = content

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
        return Change(
            ChangeContext(connection=self.connection, lock=self.lock),
            actor=actor,
            app_version=self.app_version,
            note=note,
            command_id=command_id,
        )

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
        """Drop the person projection (and the person aliases) and replay its events in seq order."""
        self.connection.execute("DELETE FROM person_residences")
        self.connection.execute("DELETE FROM people")
        self.connection.execute("DELETE FROM aliases WHERE loser_kind = 'person'")
        for row in self.connection.execute("SELECT * FROM events WHERE entity_kind = 'person' ORDER BY seq").fetchall():
            event = dict(row)
            if event["entity_version"] is None:
                continue
            if event["event_type"] == "deleted":
                self.connection.execute("DELETE FROM people WHERE person_id = ?", (event["entity_id"],))
                self.connection.execute("DELETE FROM person_residences WHERE person_id = ?", (event["entity_id"],))
                continue
            payload = json.loads(event["payload"])
            if event["event_type"] == "merged":
                person = Person.from_dict(payload["person"])
                self.connection.execute(
                    """INSERT INTO aliases (loser_kind, loser_id, survivor_kind, survivor_id, event_seq)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT (loser_kind, loser_id) DO UPDATE SET
                         survivor_kind = excluded.survivor_kind,
                         survivor_id = excluded.survivor_id,
                         event_seq = excluded.event_seq""",
                    ("person", event["entity_id"], "person", str(payload["merged_into"]), int(event["seq"])),
                )
            else:
                person = Person.from_dict(payload)
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

    def rebuild_items(self) -> None:
        """Drop the item projections (and the asset catalog) and replay their events."""
        for table in ("item_refs", "item_assets", "item_content", "items", "assets"):
            self.connection.execute(f"DELETE FROM {table}")
        projection = item_row.ItemProjection(self.connection)
        for row in self.connection.execute("SELECT * FROM events WHERE entity_kind = 'item' ORDER BY seq").fetchall():
            event = dict(row)
            if event["entity_version"] is None:
                continue
            payload = json.loads(event["payload"])
            item = Item.from_dict(payload["item"])
            catalog = tuple(replace(record, event_seq=event["seq"]) for record in payload_assets(payload))
            projection.write(
                item_row.ItemState(
                    item=replace(item, version=int(event["entity_version"])),
                    position=RowPosition(
                        version=int(event["entity_version"]),
                        event_no=int(event["event_no"]),
                        event_seq=int(event["seq"]),
                        updated_at=event["recorded_at"],
                    ),
                    refs=item_row.ItemRow.refs(item),
                    assets=item_row.ItemRow.assets(item, catalog),
                    contents=payload_contents(payload),
                    catalog=catalog,
                ),
                base=projection.current_version(item.id),
            )
        self.connection.commit()

    def rebuild_reviews(self) -> None:
        """Drop the review projections and replay the session events."""
        for table in ("review_messages", "review_decisions", "review_sessions"):
            self.connection.execute(f"DELETE FROM {table}")
        projection = ReviewProjection(self.connection)
        for row in self.connection.execute(
            "SELECT * FROM events WHERE entity_kind = 'review_session' ORDER BY seq"
        ).fetchall():
            event = dict(row)
            if event["entity_version"] is None:
                continue
            payload = json.loads(event["payload"])
            session, thinking = session_from_payload(payload)
            projection.write(
                ReviewRow.build(session, thinking),
                RowPosition(
                    version=int(event["entity_version"]),
                    event_no=int(event["event_no"]),
                    event_seq=int(event["seq"]),
                    updated_at=event["recorded_at"],
                ),
                base=projection.current_version(session.id),
            )
        self.connection.commit()

    def rebuild_pipeline(self) -> None:
        """Drop the pipeline projections and replay the batch/page/document events."""
        for table in (
            "document_pages",
            "documents",
            "row_adjustments",
            "page_rows",
            "readings",
            "pages",
            "scans",
            "batches",
        ):
            self.connection.execute(f"DELETE FROM {table}")
        batches = BatchProjection(self.connection)
        pages = PageProjection(self.connection)
        documents = DocumentProjection(self.connection)
        for row in self.connection.execute(
            """SELECT * FROM events
               WHERE entity_kind IN ('batch', 'page', 'document') ORDER BY seq"""
        ).fetchall():
            event = dict(row)
            if event["entity_version"] is None:
                continue
            payload = json.loads(event["payload"])
            position = RowPosition(
                version=int(event["entity_version"]),
                event_no=int(event["event_no"]),
                event_seq=int(event["seq"]),
                updated_at=event["recorded_at"],
            )
            if event["entity_kind"] == "batch":
                batch, scans = batch_from_payload(payload)
                batches.write(
                    BatchBundle(batch=batch, scans=scans), position, base=batches.current_version(batch.batch_id)
                )
            elif event["entity_kind"] == "page":
                bundle = page_from_payload(payload, self.content, int(event["entity_version"]))
                pages.write(
                    bundle,
                    position,
                    base=pages.current_revision(bundle.page.page_id),
                )
            else:
                document, doc_pages = document_from_payload(payload, int(event["entity_version"]))
                documents.write(
                    DocumentBundle(document=document, pages=doc_pages),
                    position,
                    base=documents.current_version(document.document_id),
                )
        self.connection.commit()

    def rebuild_identities(self) -> None:
        """Drop places/orgs/themes/relationships (and theme items) and replay them."""
        for table in ("theme_items", "places", "orgs", "themes", "relationships"):
            self.connection.execute(f"DELETE FROM {table}")
        kinds = {kind.entity_kind: kind for kind in self.IDENTITY_KINDS}
        for row in self.connection.execute(
            """SELECT * FROM events
               WHERE entity_kind IN ('place', 'org', 'theme', 'relationship') ORDER BY seq"""
        ).fetchall():
            event = dict(row)
            if event["entity_version"] is None:
                continue
            kind = kinds[event["entity_kind"]]
            collection = getattr(self, kind.name)
            if event["event_type"] == "deleted":
                self.connection.execute(f"DELETE FROM {kind.table} WHERE {kind.id_column} = ?", (event["entity_id"],))
                if kind is THEME:
                    self.connection.execute("DELETE FROM theme_items WHERE theme_id = ?", (event["entity_id"],))
                continue
            record = kind.from_payload(json.loads(event["payload"]))
            collection.project(
                record,
                version=int(event["entity_version"]),
                position=RowPosition(
                    version=int(event["entity_version"]),
                    event_no=int(event["event_no"]),
                    event_seq=int(event["seq"]),
                    updated_at=event["recorded_at"],
                ),
            )
        self.connection.commit()

    def rebuild_all(self) -> None:
        """Replay every projection from the event log — the rebuild gate."""
        self.rebuild_identities()
        self.rebuild_people()
        self.rebuild_items()
        self.rebuild_reviews()
        self.rebuild_pipeline()

    def close(self) -> None:
        self.database.close()
