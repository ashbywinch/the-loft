"""The page work write surface — the reviewer's row correction (B4a).

TECHSPEC/08 §19.4 and REWRITE-PLAN B4a: the drawn row lines are one `Change`.
The correction is a blob (`row_adjustments`), and the page's rows derive from
the reading plus that blob — the write records what the reviewer drew and
never rebuilds the rows, so a re-read's newer rows are not silently replaced
by an older correction (TECHSPEC/05 §18.4). The page's revision advances, the
optimistic token the review's other writes check against.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loft.live.page_row import PageState
from loft.live.protocols import PageStore


class PageWrites:
    """The page's write surface: the review's row correction, one change."""

    def __init__(self, store: PageStore) -> None:
        self.store = store

    def correct_rows(self, page_id: str, adjustments: bytes, reading: dict[str, Any], *, actor: str) -> PageState:
        """Record the reviewer's drawn lines as the page's current correction."""
        with self.store.change(actor=actor, note=f"correct rows {page_id}") as change:
            page = change.pages.require(page_id)
            return change.pages.save(
                page,
                base=page.revision,
                reading=reading,
                adjustment=adjustments,
                adjustment_at=datetime.now(UTC).isoformat(),
            )
