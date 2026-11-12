"""The batch projection — a registry record and the scans it adopted.

TECHSPEC/05 §18.4: `batches` is the adoption's state and `scans` the page
images it registered. The registry record is the source; the scans derive from
its pages map, in the record's own order.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from loft.live.errors import StaleVersion
from loft.live.person_row import RowPosition


@dataclass(frozen=True)
class BatchState:
    """One adopted batch's current state."""

    batch_id: str
    label: str
    source: str
    path: str
    status: str
    arrived_at: str
    started_at: str
    started_pid: int
    started_host: str
    fingerprint: list[str]
    content_changed: bool
    version: int = 0


@dataclass(frozen=True)
class ScanState:
    """One page image the adoption registered."""

    scan_id: str
    batch_id: str
    page_id: str
    sha256: str
    path: str
    ordinal: int
    created_at: str


@dataclass(frozen=True)
class BatchBundle:
    """The batch row and its scans."""

    batch: BatchState
    scans: tuple[ScanState, ...]


class BatchRow:
    """The batch/scan row mapping."""

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "batch_id",
        "label",
        "source",
        "path",
        "status",
        "arrived_at",
        "started_at",
        "started_pid",
        "started_host",
        "fingerprint_json",
        "content_changed",
        "version",
        "event_no",
        "event_seq",
        "updated_at",
    )

    @classmethod
    def to_values(cls, batch: BatchState, position: RowPosition) -> tuple[Any, ...]:
        return (
            batch.batch_id,
            batch.label or None,
            batch.source or None,
            batch.path,
            batch.status,
            batch.arrived_at or None,
            batch.started_at or None,
            batch.started_pid,
            batch.started_host or None,
            json.dumps(batch.fingerprint) if batch.fingerprint else None,
            1 if batch.content_changed else 0,
            position.version,
            position.event_no,
            position.event_seq,
            position.updated_at,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> BatchState:
        return BatchState(
            batch_id=row["batch_id"],
            label=row["label"] or "",
            source=row["source"] or "",
            path=row["path"],
            status=row["status"],
            arrived_at=row["arrived_at"] or "",
            started_at=row["started_at"] or "",
            started_pid=row["started_pid"] or 0,
            started_host=row["started_host"] or "",
            fingerprint=list(json.loads(row["fingerprint_json"] or "[]")),
            content_changed=bool(row["content_changed"]),
            version=row["version"],
        )


class BatchProjection:
    """One connection's batch rows: the reader and the guarded writer."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def current_version(self, batch_id: str) -> int | None:
        row = self.connection.execute("SELECT version FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
        return None if row is None else int(row["version"])

    def get(self, batch_id: str) -> BatchState | None:
        row = self.connection.execute("SELECT * FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
        return None if row is None else BatchRow.from_row(row)

    def scans(self, batch_id: str) -> tuple[ScanState, ...]:
        rows = self.connection.execute(
            """SELECT scan_id, batch_id, page_id, sha256, path, ordinal, created_at
               FROM scans WHERE batch_id = ? ORDER BY ordinal""",
            (batch_id,),
        ).fetchall()
        return tuple(
            ScanState(
                scan_id=row["scan_id"],
                batch_id=row["batch_id"],
                page_id=row["page_id"],
                sha256=row["sha256"],
                path=row["path"],
                ordinal=row["ordinal"],
                created_at=row["created_at"] or "",
            )
            for row in rows
        )

    def write(self, bundle: BatchBundle, position: RowPosition, *, base: int | None) -> None:
        values = BatchRow.to_values(bundle.batch, position)
        placeholders = ", ".join("?" for _ in values)
        assignments = ", ".join(f"{column} = excluded.{column}" for column in BatchRow.COLUMNS if column != "batch_id")
        cursor = self.connection.execute(
            f"""INSERT INTO batches ({", ".join(BatchRow.COLUMNS)}) VALUES ({placeholders})
                ON CONFLICT (batch_id) DO UPDATE SET {assignments}
                WHERE batches.version IS ?""",
            (*values, base),
        )
        if cursor.rowcount == 0:
            raise StaleVersion(current=self.get(bundle.batch.batch_id), base=base)
        self.connection.execute("DELETE FROM scans WHERE batch_id = ?", (bundle.batch.batch_id,))
        for scan in bundle.scans:
            self.connection.execute(
                """INSERT INTO scans (scan_id, batch_id, page_id, sha256, path, ordinal, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (scan.scan_id, scan.batch_id, scan.page_id, scan.sha256, scan.path, scan.ordinal, scan.created_at),
            )


def page_id_of(batch_id: str, page: str) -> str:
    """The page's stable id — the batch and the page file name, never the bare
    file name (two batches both have a page-01)."""
    return f"{batch_id}/{page}"


def scan_state(batch: BatchState, page: str, sha: str, ordinal: int) -> ScanState:
    return ScanState(
        scan_id=page_id_of(batch.batch_id, page),
        batch_id=batch.batch_id,
        page_id=page_id_of(batch.batch_id, page),
        sha256=sha,
        path=str(Path(batch.path) / page),
        ordinal=ordinal,
        created_at=batch.arrived_at,
    )
