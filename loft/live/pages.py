"""The pages collection — the page's image, reading, rows and correction.

TECHSPEC/08 §19.4: `store.pages` reads the page state and its reading; the
read stage and the review write through `change.pages`. The reading blob is
content-addressed; the rows derive from it, so the page and the reading cannot
disagree. A write is a `PageCommit`: the page's own step inside the change.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from loft.live.content_store import ContentStore
from loft.live.errors import Conflict, NotFound
from loft.live.page_commit import PageCommit, page_payload
from loft.live.page_row import (
    AdjustmentState,
    PageProjection,
    PageRow,
    PageState,
    ReadingState,
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
        commit = PageCommit(change, self.projection, page, base=base)
        return commit.commit(reading, adjustment=adjustment, adjustment_at=adjustment_at)

    def correct(self, page_id: str, adjustments: bytes, *, adjustment_at: str) -> PageState:
        """Record the reviewer's drawn lines as the page's current correction —
        one change. The revision advances; the reading and its rows are not
        rewritten, because the corrected rows derive from the reading plus this
        blob (a re-read's newer rows are never replaced by an older correction)."""
        change = self.change
        if change is None:
            raise Conflict("pages.correct needs a change")
        current = self.require(page_id)
        adjustment = AdjustmentState(
            page_id=page_id,
            sha256=change.content.put(adjustments, mime="application/json"),
            updated_at=adjustment_at,
        )
        version = current.revision + 1
        payload = page_payload(replace(current, revision=version), self.reading(page_id), adjustment)
        event = change.append(
            entity_kind="page",
            entity_id=page_id,
            event_type="superseded",
            entity_version=version,
            payload=payload,
        )
        saved = replace(current, revision=version, event_seq=event["seq"])
        self.projection.write_correction(
            saved,
            adjustment,
            RowPosition(
                version=version,
                event_no=event["event_no"],
                event_seq=event["seq"],
                updated_at=event["recorded_at"],
            ),
            base=current.revision,
        )
        return saved
