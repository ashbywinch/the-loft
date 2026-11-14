"""The page projection — the registry's image, its reading and its rows.

TECHSPEC/05 §18.4: `pages` is the page's state, `readings` the full reading
blob's sha and counts, `page_rows` the queryable rows, and `row_adjustments`
the reviewer's drawn lines. The work tree is read once; the blob is the reading
(lines and words together), so a rebuild reads the blob, not the tree.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, ClassVar

from loft.live.errors import StaleVersion
from loft.live.person_row import RowPosition


@dataclass(frozen=True)
class PageState:
    """One page's current state — the image, orientation, category and stage."""

    page_id: str
    image_asset_id: str
    sha256: str
    revision: int
    rotation: int
    category: str
    status: str
    event_seq: int = 0


@dataclass(frozen=True)
class ReadingState:
    """The page's full-reading blob and its row/word counts."""

    page_id: str
    reading_sha: str
    corrected_sha: str
    rows: int
    words: int
    event_seq: int = 0


@dataclass(frozen=True)
class PageRow:
    """One queryable row — the reading line as the review renders it."""

    page_id: str
    ordinal: int
    source: str
    trust: str
    text: str
    box: str
    kind: str
    orientation: int
    revision: int
    event_seq: int = 0


@dataclass(frozen=True)
class AdjustmentState:
    """The reviewer's drawn row lines for a page (the second blob)."""

    page_id: str
    sha256: str
    updated_at: str
    event_seq: int = 0


@dataclass(frozen=True)
class PageBundle:
    """One page's aggregate: its state, reading, rows and correction."""

    page: PageState
    reading: ReadingState | None
    rows: tuple[PageRow, ...]
    adjustment: AdjustmentState | None


class PageProjection:
    """One connection's page rows: the reader and the guarded writer."""

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "page_id",
        "image_asset_id",
        "sha256",
        "revision",
        "rotation",
        "category",
        "status",
        "event_seq",
    )

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def current_revision(self, page_id: str) -> int | None:
        row = self.connection.execute("SELECT revision FROM pages WHERE page_id = ?", (page_id,)).fetchone()
        return None if row is None else int(row["revision"])

    def get(self, page_id: str) -> PageState | None:
        row = self.connection.execute("SELECT * FROM pages WHERE page_id = ?", (page_id,)).fetchone()
        if row is None:
            return None
        return PageState(
            page_id=row["page_id"],
            image_asset_id=row["image_asset_id"],
            sha256=row["sha256"],
            revision=row["revision"],
            rotation=row["rotation"],
            category=row["category"],
            status=row["status"],
            event_seq=row["event_seq"],
        )

    def reading(self, page_id: str) -> ReadingState | None:
        row = self.connection.execute("SELECT * FROM readings WHERE page_id = ?", (page_id,)).fetchone()
        if row is None:
            return None
        return ReadingState(
            page_id=row["page_id"],
            reading_sha=row["reading_sha"],
            corrected_sha=row["corrected_sha"],
            rows=row["rows"],
            words=row["words"],
            event_seq=row["event_seq"],
        )

    def rows(self, page_id: str) -> tuple[PageRow, ...]:
        rows = self.connection.execute(
            """SELECT page_id, ordinal, source, trust, text, box, kind, orientation, revision, event_seq
               FROM page_rows WHERE page_id = ? ORDER BY ordinal""",
            (page_id,),
        ).fetchall()
        return tuple(
            PageRow(
                page_id=row["page_id"],
                ordinal=row["ordinal"],
                source=row["source"],
                trust=row["trust"],
                text=row["text"],
                box=row["box"],
                kind=row["kind"],
                orientation=row["orientation"] or 0,
                revision=row["revision"],
                event_seq=row["event_seq"],
            )
            for row in rows
        )

    def adjustment(self, page_id: str) -> AdjustmentState | None:
        row = self.connection.execute(
            "SELECT page_id, sha256, updated_at, event_seq FROM row_adjustments WHERE page_id = ?",
            (page_id,),
        ).fetchone()
        if row is None:
            return None
        return AdjustmentState(
            page_id=row["page_id"], sha256=row["sha256"], updated_at=row["updated_at"], event_seq=row["event_seq"]
        )

    def write(self, bundle: PageBundle, position: RowPosition, *, base: int | None) -> None:
        values = (
            bundle.page.page_id,
            bundle.page.image_asset_id,
            bundle.page.sha256,
            position.version,
            bundle.page.rotation,
            bundle.page.category,
            bundle.page.status,
            position.event_seq,
        )
        cursor = self.connection.execute(
            f"""INSERT INTO pages ({", ".join(self.COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (page_id) DO UPDATE SET
                  image_asset_id = excluded.image_asset_id, sha256 = excluded.sha256,
                  revision = excluded.revision, rotation = excluded.rotation,
                  category = excluded.category, status = excluded.status, event_seq = excluded.event_seq
                WHERE pages.revision IS ?""",
            (*values, base),
        )
        if cursor.rowcount == 0:
            raise StaleVersion(current=self.get(bundle.page.page_id), base=base)
        self.connection.execute("DELETE FROM readings WHERE page_id = ?", (bundle.page.page_id,))
        if bundle.reading is not None:
            self.connection.execute(
                """INSERT INTO readings (page_id, reading_sha, corrected_sha, rows, words, event_seq)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    bundle.reading.page_id,
                    bundle.reading.reading_sha,
                    bundle.reading.corrected_sha,
                    bundle.reading.rows,
                    bundle.reading.words,
                    position.event_seq,
                ),
            )
        self.connection.execute("DELETE FROM page_rows WHERE page_id = ?", (bundle.page.page_id,))
        for row in bundle.rows:
            self.connection.execute(
                """INSERT INTO page_rows (page_id, ordinal, source, trust, text, box, kind,
                                          orientation, revision, event_seq)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row.page_id,
                    row.ordinal,
                    row.source,
                    row.trust,
                    row.text,
                    row.box,
                    row.kind,
                    row.orientation,
                    row.revision,
                    position.event_seq,
                ),
            )
        self.connection.execute("DELETE FROM row_adjustments WHERE page_id = ?", (bundle.page.page_id,))
        if bundle.adjustment is not None:
            self.connection.execute(
                "INSERT INTO row_adjustments (page_id, sha256, updated_at, event_seq) VALUES (?, ?, ?, ?)",
                (
                    bundle.adjustment.page_id,
                    bundle.adjustment.sha256,
                    bundle.adjustment.updated_at,
                    position.event_seq,
                ),
            )

    def write_correction(
        self, page: PageState, adjustment: AdjustmentState, position: RowPosition, *, base: int
    ) -> None:
        """Record one correction: the page's revision moves and the drawn-lines
        row is replaced; the reading and its rows are left exactly as they are
        (the rows derive from the reading plus this blob)."""
        cursor = self.connection.execute(
            "UPDATE pages SET revision = ?, event_seq = ? WHERE page_id = ? AND revision IS ?",
            (position.version, position.event_seq, page.page_id, base),
        )
        if cursor.rowcount == 0:
            raise StaleVersion(current=self.get(page.page_id), base=base)
        self.connection.execute("DELETE FROM row_adjustments WHERE page_id = ?", (page.page_id,))
        self.connection.execute(
            "INSERT INTO row_adjustments (page_id, sha256, updated_at, event_seq) VALUES (?, ?, ?, ?)",
            (adjustment.page_id, adjustment.sha256, adjustment.updated_at, position.event_seq),
        )


def reading_blob(
    page: str, raw: dict[str, Any], words: list[dict[str, Any]], *, rotation: int, revision: int
) -> dict[str, Any]:
    """The full-reading blob: the old reading's lines plus its words, with the
    page's applied orientation and revision named as the target's fields."""
    blob = dict(raw)
    blob["page"] = page
    blob["rotation"] = rotation
    blob["revision"] = revision
    blob.setdefault("width", 0)
    blob.setdefault("height", 0)
    blob.setdefault("lines", [])
    blob["words"] = words
    blob.setdefault("corrected", "")
    return blob


def reading_rows(
    page_id: str,
    blob: dict[str, Any],
    *,
    revision: int,
    corrected: bool,
) -> tuple[PageRow, ...]:
    """The reading's lines as the queryable rows — the blob is the one source."""
    rows: list[PageRow] = []
    for index, line in enumerate(blob.get("lines") or []):
        rows.append(
            PageRow(
                page_id=page_id,
                ordinal=index + 1,
                source="human" if corrected else "machine",
                trust="guess",
                text=str(line.get("text", "")),
                box=json.dumps(line.get("box"), ensure_ascii=False),
                kind=str(line.get("kind", "body")),
                orientation=int(line.get("orientation", 0)),
                revision=revision,
            )
        )
    return tuple(rows)
