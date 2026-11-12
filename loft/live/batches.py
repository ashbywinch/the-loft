"""The batches collection — the registry record and its scans.

TECHSPEC/08 §19.4: `store.batches` reads the adoption state; `change.batches`
writes it inside the change. The registry record is the source; the scans are
its pages map, in the record's order.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from loft.live.batch_row import BatchBundle, BatchProjection, BatchState, ScanState
from loft.live.errors import Conflict, NotFound, StaleVersion
from loft.live.person_row import RowPosition

if TYPE_CHECKING:
    from loft.live.change import Change


class Batches:
    """The batch collection: read through the store, write through a change."""

    def __init__(self, connection: sqlite3.Connection, change: Change | None = None) -> None:
        self.projection = BatchProjection(connection)
        self.change = change

    # -- reads -------------------------------------------------------------

    def get(self, batch_id: str) -> BatchState | None:
        return self.projection.get(batch_id)

    def require(self, batch_id: str) -> BatchState:
        batch = self.get(batch_id)
        if batch is None:
            raise NotFound(f"no batch {batch_id}")
        return batch

    def scans(self, batch_id: str) -> tuple[ScanState, ...]:
        return self.projection.scans(batch_id)

    # -- writes ------------------------------------------------------------

    def save(self, batch: BatchState, scans: tuple[ScanState, ...] = (), *, base: int | None = None) -> BatchState:
        """Write a create (base None) or a supersede, version-checked."""
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
        payload = batch_payload(batch, scans)
        event = change.append(
            entity_kind="batch",
            entity_id=batch.batch_id,
            event_type=event_type,
            entity_version=version,
            payload=payload,
        )
        saved = replace(batch, version=version)
        self.projection.write(
            BatchBundle(batch=saved, scans=scans),
            RowPosition(
                version=version,
                event_no=event["event_no"],
                event_seq=event["seq"],
                updated_at=event["recorded_at"],
            ),
            base=base,
        )
        return saved


def batch_payload(batch: BatchState, scans: tuple[ScanState, ...]) -> str:
    """The event payload: the registry record and its scans."""
    return json.dumps(
        {"batch": _batch_dict(batch), "scans": [_scan_dict(scan) for scan in scans]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _batch_dict(batch: BatchState) -> dict[str, Any]:
    return {
        "batch_id": batch.batch_id,
        "label": batch.label,
        "source": batch.source,
        "path": batch.path,
        "status": batch.status,
        "arrived_at": batch.arrived_at,
        "started_at": batch.started_at,
        "started_pid": batch.started_pid,
        "started_host": batch.started_host,
        "fingerprint": list(batch.fingerprint),
        "content_changed": batch.content_changed,
    }


def _scan_dict(scan: ScanState) -> dict[str, Any]:
    return {
        "scan_id": scan.scan_id,
        "batch_id": scan.batch_id,
        "page_id": scan.page_id,
        "sha256": scan.sha256,
        "path": scan.path,
        "ordinal": scan.ordinal,
        "created_at": scan.created_at,
    }


def batch_from_payload(payload: dict[str, Any]) -> tuple[BatchState, tuple[ScanState, ...]]:
    """The batch and scans an event carries."""
    raw = payload["batch"]
    batch = BatchState(
        batch_id=str(raw["batch_id"]),
        label=str(raw.get("label") or ""),
        source=str(raw.get("source") or ""),
        path=str(raw["path"]),
        status=str(raw["status"]),
        arrived_at=str(raw.get("arrived_at") or ""),
        started_at=str(raw.get("started_at") or ""),
        started_pid=int(raw.get("started_pid") or 0),
        started_host=str(raw.get("started_host") or ""),
        fingerprint=[str(value) for value in raw.get("fingerprint") or []],
        content_changed=bool(raw.get("content_changed")),
    )
    scans = tuple(
        ScanState(
            scan_id=str(entry["scan_id"]),
            batch_id=str(entry["batch_id"]),
            page_id=str(entry["page_id"]),
            sha256=str(entry["sha256"]),
            path=str(entry["path"]),
            ordinal=int(entry["ordinal"]),
            created_at=str(entry.get("created_at") or ""),
        )
        for entry in payload.get("scans") or []
    )
    return batch, scans
