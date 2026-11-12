"""The pages collection — the page's image, reading, rows and correction.

TECHSPEC/08 §19.4: `store.pages` reads the page state and its reading; the
read stage and the review write through `change.pages`. The reading blob is
content-addressed; the rows derive from it, so the page and the reading cannot
disagree.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from loft.live.content import ContentStore
from loft.live.errors import Conflict, NotFound, StaleVersion
from loft.live.page_row import (
    AdjustmentState,
    PageBundle,
    PageProjection,
    PageRow,
    PageState,
    ReadingState,
    reading_blob,
    reading_rows,
)
from loft.live.person_row import RowPosition

if TYPE_CHECKING:
    from loft.live.change import Change


class Pages:
    """The page collection: read through the store, write through a change."""

    def __init__(self, connection: sqlite3.Connection, content: ContentStore, change: Change | None = None) -> None:
        self.content_store = content
        self.projection = PageProjection(connection)
        self.change = change

    # -- reads -------------------------------------------------------------

    def get(self, page_id: str) -> PageState | None:
        return self.projection.get(page_id)

    def require(self, page_id: str) -> PageState:
        page = self.get(page_id)
        if page is None:
            raise NotFound(f"no page {page_id}")
        return page

    def reading(self, page_id: str) -> ReadingState | None:
        return self.projection.reading(page_id)

    def rows(self, page_id: str) -> tuple[PageRow, ...]:
        return self.projection.rows(page_id)

    def adjustment(self, page_id: str) -> AdjustmentState | None:
        return self.projection.adjustment(page_id)

    def reading_blob(self, page_id: str) -> dict[str, Any] | None:
        reading = self.reading(page_id)
        if reading is None:
            return None
        return json.loads(self.content_store.get(reading.reading_sha))

    # -- writes ------------------------------------------------------------

    # lucidlint: ignore feature-envy the save IS the page transaction's step;
    # the change is the write seam it commits through, not a second owner
    def save(
        self,
        page: PageState,
        *,
        base: int | None = None,
        reading: dict[str, Any] | None = None,
        adjustment: bytes | None = None,
        adjustment_at: str = "",
    ) -> PageState:
        """Write a page and its reading; the rows derive from the reading blob."""
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
            sha = change.content.put(_bytes(blob), mime="application/json")
            corrected = str(blob.get("corrected", ""))
            rows = reading_rows(page.page_id, blob, revision=version, corrected=bool(corrected))
            reading_state = ReadingState(
                page_id=page.page_id,
                reading_sha=sha,
                corrected_sha=corrected,
                rows=len(rows),
                words=len(blob.get("words") or []),
            )
        adjustment_state: AdjustmentState | None = None
        if adjustment is not None:
            adjustment_state = AdjustmentState(
                page_id=page.page_id,
                sha256=change.content.put(adjustment, mime="application/json"),
                updated_at=adjustment_at,
            )
        payload = page_payload(replace(page, revision=version), reading_state, adjustment_state)
        event = change.append(
            entity_kind="page",
            entity_id=page.page_id,
            event_type=event_type,
            entity_version=version,
            payload=payload,
        )
        saved = replace(page, revision=version, event_seq=event["seq"])
        self.projection.write(
            PageBundle(page=saved, reading=reading_state, rows=rows, adjustment=adjustment_state),
            RowPosition(
                version=version,
                event_no=event["event_no"],
                event_seq=event["seq"],
                updated_at=event["recorded_at"],
            ),
            base=base,
        )
        return saved


def _bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def page_payload(page: PageState, reading: ReadingState | None, adjustment: AdjustmentState | None) -> str:
    """The event payload: the page's state, its reading and its correction."""
    return json.dumps(
        {
            "page": _page_dict(page),
            "reading": _reading_dict(reading),
            "adjustment": _adjustment_dict(adjustment),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _page_dict(page: PageState) -> dict[str, Any]:
    return {
        "page_id": page.page_id,
        "image_asset_id": page.image_asset_id,
        "sha256": page.sha256,
        "revision": page.revision,
        "rotation": page.rotation,
        "category": page.category,
        "status": page.status,
    }


def _reading_dict(reading: ReadingState | None) -> dict[str, Any] | None:
    if reading is None:
        return None
    return {
        "sha256": reading.reading_sha,
        "corrected": reading.corrected_sha,
        "rows": reading.rows,
        "words": reading.words,
    }


def _adjustment_dict(adjustment: AdjustmentState | None) -> dict[str, Any] | None:
    if adjustment is None:
        return None
    return {"sha256": adjustment.sha256, "updated_at": adjustment.updated_at}


def page_from_payload(payload: dict[str, Any], content: Any, version: int) -> PageBundle:
    """The page, reading, rows and adjustment an event carries; the rows are
    re-derived from the reading blob (the one source)."""
    raw = payload["page"]
    page = PageState(
        page_id=str(raw["page_id"]),
        image_asset_id=str(raw["image_asset_id"]),
        sha256=str(raw["sha256"]),
        revision=version,
        rotation=int(raw.get("rotation") or 0),
        category=str(raw.get("category") or ""),
        status=str(raw["status"]),
    )
    reading_raw = payload.get("reading")
    reading_state: ReadingState | None = None
    rows: tuple[PageRow, ...] = ()
    if reading_raw:
        corrected = str(reading_raw.get("corrected") or "")
        blob = json.loads(content.get(str(reading_raw["sha256"])))
        rows = reading_rows(page.page_id, blob, revision=version, corrected=bool(corrected))
        reading_state = ReadingState(
            page_id=page.page_id,
            reading_sha=str(reading_raw["sha256"]),
            corrected_sha=corrected,
            rows=int(reading_raw["rows"]),
            words=int(reading_raw["words"]),
        )
    adjustment_raw = payload.get("adjustment")
    adjustment = (
        AdjustmentState(
            page_id=page.page_id,
            sha256=str(adjustment_raw["sha256"]),
            updated_at=str(adjustment_raw.get("updated_at") or ""),
        )
        if adjustment_raw
        else None
    )
    return PageBundle(page=page, reading=reading_state, rows=rows, adjustment=adjustment)
