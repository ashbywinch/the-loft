"""The page commit — one page version's write inside a change.

TECHSPEC/05 §18.4, 08 §19.4: a page's write is its own step. It decides
create vs supersede against the projection, puts the reading and correction
blobs through the change's content store, appends the one page event and
writes the projection row. The change is the transaction it commits through;
the page, its base revision and the version it becomes are the commit's own
state. The reading blob is content-addressed and the rows derive from it, so
the page, its reading and its correction cannot disagree.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

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


class PageCommit:
    """One page version's commit: its event, its content blobs and its row."""

    def __init__(
        self,
        change: Change,
        projection: PageProjection,
        page: PageState,
        *,
        base: int | None = None,
    ) -> None:
        self.change = change
        self.projection = projection
        self.page = page
        self.base = base

    def commit(
        self,
        reading: dict[str, Any] | None = None,
        *,
        adjustment: bytes | None = None,
        adjustment_at: str = "",
    ) -> PageState:
        """Write the page's next version, with its reading and its correction."""
        event_type, version = self._version()
        reading_state, rows = self._reading(reading, version)
        adjustment_state = self._adjustment(adjustment, adjustment_at)
        payload = page_payload(replace(self.page, revision=version), reading_state, adjustment_state)
        event = self.change.append(
            entity_kind="page",
            entity_id=self.page.page_id,
            event_type=event_type,
            entity_version=version,
            payload=payload,
        )
        saved = replace(self.page, revision=version, event_seq=event["seq"])
        self.projection.write(
            PageBundle(page=saved, reading=reading_state, rows=rows, adjustment=adjustment_state),
            RowPosition(
                version=version,
                event_no=event["event_no"],
                event_seq=event["seq"],
                updated_at=event["recorded_at"],
            ),
            base=self.base,
        )
        return saved

    def _version(self) -> tuple[str, int]:
        """The event type and the version it becomes: created at the page's own
        version, superseded at the base plus one — checked against the page as
        it stands. A page cannot carry a version below 1 (`PageState`), so a
        create has nothing to repair."""
        current = self.projection.get(self.page.page_id)
        if self.base is None:
            if current is not None:
                raise Conflict(f"page {self.page.page_id} exists")
            return "created", self.page.revision
        if current is None:
            raise NotFound(f"no page {self.page.page_id}")
        if current.revision != self.base:
            raise StaleVersion(current=current, base=self.base)
        return "superseded", self.base + 1

    def _reading(self, reading: dict[str, Any] | None, version: int) -> tuple[ReadingState | None, tuple[PageRow, ...]]:
        """The reading blob, stored and counted — the rows derive from it.

        The reading arrives in the blob's own wire shape (the read stage's
        output, `reading_blob`'s), so its fields are read once here, before the
        blob is built: the words and the correction are the caller's, and the
        blob is their constructor's."""
        if reading is None:
            return None, ()
        words = list(reading.get("words") or [])
        corrected = str(reading.get("corrected") or "")
        blob = reading_blob(
            self.page.page_id,
            reading,
            words,
            rotation=self.page.rotation,
            revision=version,
        )
        sha = self.change.content.put(_canonical_bytes(blob), mime="application/json")
        rows = reading_rows(self.page.page_id, blob, revision=version, corrected=bool(corrected))
        state = ReadingState(
            page_id=self.page.page_id,
            reading_sha=sha,
            corrected_sha=corrected,
            rows=len(rows),
            words=len(blob.get("words") or []),
        )
        return state, rows

    def _adjustment(self, adjustment: bytes | None, adjustment_at: str) -> AdjustmentState | None:
        """The reviewer's drawn lines, stored as the page's correction."""
        if adjustment is None:
            return None
        return AdjustmentState(
            page_id=self.page.page_id,
            sha256=self.change.content.put(adjustment, mime="application/json"),
            updated_at=adjustment_at,
        )


def _canonical_bytes(value: dict[str, Any]) -> bytes:
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
