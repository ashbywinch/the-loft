"""The document projection — a registry boundary and the pages it runs over.

TECHSPEC/05 §18.4: `documents` is the grouped writing's state and
`document_pages` the page order. The registry's boundary is the source; the
item link and the confirmed text are carried where the boundary has them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, ClassVar

from loft.live.errors import StaleVersion
from loft.live.person_row import RowPosition


@dataclass(frozen=True)
class DocumentState:
    """One document's current state."""

    document_id: str
    item_id: str | None
    batch_id: str
    doc_index: int
    title: str | None
    date_json: str | None
    date: str | None
    date2: str | None
    date_precision: str | None
    status: str
    greeting: str | None
    signoff: str | None
    text_sha: str | None
    confirmed_at: str | None
    version: int = 0


@dataclass(frozen=True)
class DocumentPage:
    """One page in a document's reading order."""

    document_id: str
    page_id: str
    ordinal: int


@dataclass(frozen=True)
class DocumentBundle:
    """The document row and its pages."""

    document: DocumentState
    pages: tuple[DocumentPage, ...]


class DocumentRow:
    """The document row mapping."""

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "document_id",
        "item_id",
        "batch_id",
        "doc_index",
        "title",
        "date_json",
        "date",
        "date2",
        "date_precision",
        "status",
        "greeting",
        "signoff",
        "text_sha",
        "confirmed_at",
        "version",
        "event_no",
        "event_seq",
        "updated_at",
    )

    @classmethod
    def to_values(cls, document: DocumentState, position: RowPosition) -> tuple[Any, ...]:
        return (
            document.document_id,
            document.item_id,
            document.batch_id,
            document.doc_index,
            document.title,
            document.date_json,
            document.date,
            document.date2,
            document.date_precision,
            document.status,
            document.greeting,
            document.signoff,
            document.text_sha,
            document.confirmed_at,
            position.version,
            position.event_no,
            position.event_seq,
            position.updated_at,
        )


class DocumentProjection:
    """One connection's document rows: the reader and the guarded writer."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def current_version(self, document_id: str) -> int | None:
        row = self.connection.execute("SELECT version FROM documents WHERE document_id = ?", (document_id,)).fetchone()
        return None if row is None else int(row["version"])

    def get(self, document_id: str) -> DocumentState | None:
        row = self.connection.execute("SELECT * FROM documents WHERE document_id = ?", (document_id,)).fetchone()
        if row is None:
            return None
        return DocumentState(
            document_id=row["document_id"],
            item_id=row["item_id"],
            batch_id=row["batch_id"],
            doc_index=row["doc_index"],
            title=row["title"],
            date_json=row["date_json"],
            date=row["date"],
            date2=row["date2"],
            date_precision=row["date_precision"],
            status=row["status"],
            greeting=row["greeting"],
            signoff=row["signoff"],
            text_sha=row["text_sha"],
            confirmed_at=row["confirmed_at"],
            version=row["version"],
        )

    def pages(self, document_id: str) -> tuple[DocumentPage, ...]:
        rows = self.connection.execute(
            "SELECT document_id, page_id, ordinal FROM document_pages WHERE document_id = ? ORDER BY ordinal",
            (document_id,),
        ).fetchall()
        return tuple(
            DocumentPage(document_id=row["document_id"], page_id=row["page_id"], ordinal=row["ordinal"]) for row in rows
        )

    def for_batch(self, batch_id: str) -> tuple[DocumentState, ...]:
        rows = self.connection.execute(
            "SELECT * FROM documents WHERE batch_id = ? ORDER BY doc_index", (batch_id,)
        ).fetchall()
        return tuple(
            DocumentState(
                document_id=row["document_id"],
                item_id=row["item_id"],
                batch_id=row["batch_id"],
                doc_index=row["doc_index"],
                title=row["title"],
                date_json=row["date_json"],
                date=row["date"],
                date2=row["date2"],
                date_precision=row["date_precision"],
                status=row["status"],
                greeting=row["greeting"],
                signoff=row["signoff"],
                text_sha=row["text_sha"],
                confirmed_at=row["confirmed_at"],
                version=row["version"],
            )
            for row in rows
        )

    def write(self, bundle: DocumentBundle, position: RowPosition, *, base: int | None) -> None:
        values = DocumentRow.to_values(bundle.document, position)
        placeholders = ", ".join("?" for _ in values)
        assignments = ", ".join(
            f"{column} = excluded.{column}" for column in DocumentRow.COLUMNS if column != "document_id"
        )
        cursor = self.connection.execute(
            f"""INSERT INTO documents ({", ".join(DocumentRow.COLUMNS)}) VALUES ({placeholders})
                ON CONFLICT (document_id) DO UPDATE SET {assignments}
                WHERE documents.version IS ?""",
            (*values, base),
        )
        if cursor.rowcount == 0:
            raise StaleVersion(current=self.get(bundle.document.document_id), base=base)
        self.connection.execute("DELETE FROM document_pages WHERE document_id = ?", (bundle.document.document_id,))
        for page in bundle.pages:
            self.connection.execute(
                "INSERT INTO document_pages (document_id, page_id, ordinal) VALUES (?, ?, ?)",
                (page.document_id, page.page_id, page.ordinal),
            )
