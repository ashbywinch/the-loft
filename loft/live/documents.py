"""The documents collection — a grouped boundary and its page order.

TECHSPEC/08 §19.4: `store.documents` reads the grouping; the review writes it
through `change.documents`. The registry's boundary is the source; an agreed
document carries the item link and the confirmed text's sha.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from loft.live.document_row import (
    DocumentBundle,
    DocumentPage,
    DocumentProjection,
    DocumentState,
)
from loft.live.errors import Conflict, NotFound, StaleVersion
from loft.live.person_row import RowPosition

if TYPE_CHECKING:
    from loft.live.change import Change


class Documents:
    """The document collection: read through the store, write through a change."""

    def __init__(self, connection: sqlite3.Connection, change: Change | None = None) -> None:
        self.projection = DocumentProjection(connection)
        self.change = change

    # -- reads -------------------------------------------------------------

    def get(self, document_id: str) -> DocumentState | None:
        return self.projection.get(document_id)

    def require(self, document_id: str) -> DocumentState:
        document = self.get(document_id)
        if document is None:
            raise NotFound(f"no document {document_id}")
        return document

    def pages(self, document_id: str) -> tuple[DocumentPage, ...]:
        return self.projection.pages(document_id)

    def for_batch(self, batch_id: str) -> tuple[DocumentState, ...]:
        return self.projection.for_batch(batch_id)

    # -- writes ------------------------------------------------------------

    def save(
        self,
        document: DocumentState,
        pages: tuple[str, ...],
        *,
        base: int | None = None,
        text: str | None = None,
    ) -> DocumentState:
        """Write a create (base None) or a supersede; the pages are the order."""
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
        payload = document_payload(saved, pages)
        event = change.append(
            entity_kind="document",
            entity_id=document.document_id,
            event_type=event_type,
            entity_version=version,
            payload=payload,
        )
        rows = tuple(
            DocumentPage(document_id=document.document_id, page_id=page_id, ordinal=index)
            for index, page_id in enumerate(pages)
        )
        self.projection.write(
            DocumentBundle(document=saved, pages=rows),
            RowPosition(
                version=version,
                event_no=event["event_no"],
                event_seq=event["seq"],
                updated_at=event["recorded_at"],
            ),
            base=base,
        )
        return saved


def document_payload(document: DocumentState, pages: tuple[str, ...]) -> str:
    """The event payload: the document and its page order."""
    return json.dumps(
        {"document": _document_dict(document), "pages": list(pages)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _document_dict(document: DocumentState) -> dict[str, Any]:
    return {
        "document_id": document.document_id,
        "item_id": document.item_id,
        "batch_id": document.batch_id,
        "doc_index": document.doc_index,
        "title": document.title,
        "date_json": document.date_json,
        "date": document.date,
        "date2": document.date2,
        "date_precision": document.date_precision,
        "status": document.status,
        "greeting": document.greeting,
        "signoff": document.signoff,
        "text_sha": document.text_sha,
        "confirmed_at": document.confirmed_at,
    }


def document_from_payload(payload: dict[str, Any], version: int) -> tuple[DocumentState, tuple[DocumentPage, ...]]:
    """The document and page order an event carries."""
    raw = payload["document"]
    document = DocumentState(
        document_id=str(raw["document_id"]),
        item_id=raw.get("item_id"),
        batch_id=str(raw["batch_id"]),
        doc_index=int(raw["doc_index"]),
        title=raw.get("title"),
        date_json=raw.get("date_json"),
        date=raw.get("date"),
        date2=raw.get("date2"),
        date_precision=raw.get("date_precision"),
        status=str(raw["status"]),
        greeting=raw.get("greeting"),
        signoff=raw.get("signoff"),
        text_sha=raw.get("text_sha"),
        confirmed_at=raw.get("confirmed_at"),
        version=version,
    )
    pages = tuple(
        DocumentPage(document_id=document.document_id, page_id=str(page_id), ordinal=index)
        for index, page_id in enumerate(payload.get("pages") or [])
    )
    return document, pages
