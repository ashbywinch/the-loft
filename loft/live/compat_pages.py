"""The page compatibility exporter — the old work files a correction writes.

TECHSPEC/08 §19.4 and REWRITE-PLAN B4a: from the flip the drawn lines and the
reading are blobs in the DB, but the review surface and the worker still read
`<page>.row-adjustments.json` (the lines, as drawn) and
`<page>.rows-adjusted.json` (the rows they made). After a correction this
exporter writes both from the stored blobs — the drawn bytes exactly as
stored, and the rows derived the same way the correction derives them, so the
files are byte-identical to the old writer's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from document.page_size import PageSize
from document.row_adjustments import RowAdjustments
from document.traces import Traces
from document.words import Words
from loft.live.errors import LiveError
from loft.live.protocols import PageStore
from pipeline.api.sync import BatchReadings
from pipeline.rows.rows import Row, Rows
from pipeline.rows_reading import RowsReading
from tools.atomic import atomic_write


class PageExportError(LiveError):
    """The page's correction cannot be reproduced from the stored blobs."""


def adjusted_rows(blob: dict[str, Any], drawn: str) -> list[Row]:
    """The correction's rows: the reading's lines regrouped by the drawn
    lines, exactly as `Rows.adjust` builds them for the response. A reading
    with no words cannot produce them — the correction would silently drop
    every word, so it fails loud instead."""
    if not blob.get("words"):
        raise PageExportError(f"page {blob.get('page', '')} has no words to derive its corrected rows from")
    reading = RowsReading.from_dict(blob)
    adjustments = RowAdjustments.from_dict(json.loads(drawn))
    traces = Traces(
        words=tuple(Words.from_dict({"words": blob.get("words") or []})),
        adjustments=adjustments,
        page_size=PageSize(reading.width, reading.height),
    )
    return Rows.from_traces(traces).adjust(adjustments)


class PageCompatibility:
    """Write one page's correction into the old work tree."""

    def __init__(self, store: PageStore, work_dir: Path) -> None:
        self.store = store
        self.work_dir = work_dir

    def write(self, page_id: str) -> tuple[str, ...]:
        """Write the page's drawn lines and the rows they made; return the
        paths written. An uncorrected page writes nothing."""
        page = self.store.pages.get(page_id)
        adjustment = self.store.pages.adjustment(page_id)
        blob = self.store.pages.reading_blob(page_id)
        if page is None or adjustment is None or blob is None:
            return ()
        drawn = self.store.content.get(adjustment.sha256).decode("utf-8")
        batch_id, page_name = page_id.split("/", 1)
        readings = BatchReadings(self.work_dir, batch_id)
        adjustments_path = readings.adjustments_path(page_name)
        atomic_write(adjustments_path, drawn)
        rows_path = readings.adjusted_rows_path(page_name)
        atomic_write(
            rows_path, json.dumps(Rows.to_dict(adjusted_rows(blob, drawn)), ensure_ascii=False, indent=1) + "\n"
        )
        return (str(adjustments_path), str(rows_path))
