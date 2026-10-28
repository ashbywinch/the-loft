"""A page's status, read from its artefacts (TECHSPEC §16.14.2's marker rule).

The portal's "Check the rows" queue is this status: a page with draft rows and
no recorded check waits on a person; every other page is the machine's or
already checked (docs/PLAN/pipeline-stages-plan.md, the scan pickup).
"""

from __future__ import annotations

from pathlib import Path

from document.stages import PageStatus
from pipeline.api.sync import BatchReadings, pages_pending

PAGE = "p1.jpg"


def _readings(tmp_path: Path) -> BatchReadings:
    return BatchReadings(tmp_path, "batch-1")


def _write(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")


def test_each_marker_moves_the_page_to_its_stage(tmp_path: Path) -> None:
    """The ladder the stages write: orient, the reading's words, the read's
    rows, then the reviewer's check. `rows_draft` never reads back — the draft
    rows ARE the artefact — and a half-written check is not a check."""
    readings = _readings(tmp_path)
    assert readings.page_status(PAGE) is PageStatus.NEW
    _write(readings.oriented_path(PAGE))
    assert readings.page_status(PAGE) is PageStatus.ORIENTED
    _write(readings.words_path(PAGE))
    assert readings.page_status(PAGE) is PageStatus.WORDS
    _write(readings.rows_path(PAGE))
    assert readings.page_status(PAGE) is PageStatus.ROWS_PENDING
    _write(readings.adjustments_path(PAGE))
    assert readings.page_status(PAGE) is PageStatus.ROWS_PENDING  # a crash between the two writes
    _write(readings.adjusted_rows_path(PAGE))
    assert readings.page_status(PAGE) is PageStatus.ROWS_ADJUSTED


def test_the_queue_lists_the_pages_waiting_on_a_person(tmp_path: Path) -> None:
    """Only a page the read stage has finished waits on a person: an unread
    page and a checked page are not in the list."""
    readings = _readings(tmp_path)
    for page in ("waiting.jpg", "checked.jpg"):
        _write(readings.words_path(page))
        _write(readings.rows_path(page))
    _write(readings.adjustments_path("checked.jpg"))
    _write(readings.adjusted_rows_path("checked.jpg"))
    assert pages_pending(readings, ["unread.jpg", "waiting.jpg", "checked.jpg"]) == ["waiting.jpg"]
    assert pages_pending(readings, []) == []
