"""B4a — the page's row correction writes through the service.

The ported correction scenarios: the reviewer's drawn lines are one `Change`
(the `row_adjustments` blob), the page's rows derive from the reading plus
that blob (never rebuilt by the write), and the compatibility exporter writes
the two old work files the review surface and the worker read — byte-identical
to the old writer. The suite runs on both stores (TECHSPEC/08 §19.7).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from document.row_adjustments import RowAdjustments
from loft.live.compat_pages import PageCompatibility, PageExportError
from loft.live.errors import NotFound
from loft.live.memory import MemoryLiveStore
from loft.live.page_row import PageState
from loft.live.page_writes import PageWrites
from loft.live.store import LiveStore
from pipeline.api.sync import BatchReadings, apply_row_adjustments
from tools.archive import Archive
from tools.store import MemoryStore

BATCH = "adopt-0001"
PAGE = "p1.jpg"
PAGE_ID = f"{BATCH}/{PAGE}"
DRAWN = {"lines": [[[0.05, 0.278], [0.55, 0.278]]]}


@pytest.fixture(params=["sqlite", "memory"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Any]:
    if request.param == "sqlite":
        live = LiveStore.create(tmp_path / "loft.db", app_version="test")
    else:
        live = MemoryLiveStore(app_version="test")
    yield live
    live.close()


def _reading() -> dict[str, Any]:
    """The page's reading as the read stage writes it (rows.json)."""
    return {
        "page": PAGE,
        "width": 600,
        "height": 1600,
        "rotation": 0,
        "revision": 1,
        "lines": [{"index": 0, "text": "one two", "box": [50, 400, 550, 500], "words": []}],
    }


def _words() -> dict[str, Any]:
    return {
        "words": [
            {"x0": 60, "y0": 420, "x1": 160, "y1": 470, "line": 0, "baseline": 470, "waistline": 420},
            {"x0": 200, "y0": 420, "x1": 300, "y1": 470, "line": 0, "baseline": 470, "waistline": 420},
        ]
    }


def _drawn() -> str:
    """The drawn lines exactly as the old writer persists them."""
    return json.dumps(RowAdjustments.from_dict(DRAWN).to_dict(), ensure_ascii=False, indent=1) + "\n"


def _seed_page(store: Any) -> None:
    """The page as the import writes it: the reading blob carries the words
    the correction groups (the exporter derives the rows from them)."""
    with store.change(actor="import") as change:
        change.pages.save(
            PageState(
                page_id=PAGE_ID,
                image_asset_id=PAGE_ID,
                sha256="hash-1",
                revision=1,
                rotation=0,
                category="writing",
                status="rows_pending",
            ),
            reading={**_reading(), "words": _words()["words"]},
        )


def _work_files(work_dir: Path) -> None:
    """The work tree the correction reads: the reading and its words."""
    guess = work_dir / BATCH / "ocr-guess"
    guess.mkdir(parents=True, exist_ok=True)
    (guess / "p1.rows.json").write_text(json.dumps(_reading()), encoding="utf-8")
    (guess / "p1.words.json").write_text(json.dumps(_words()), encoding="utf-8")


def _registry(registry_dir: Path) -> None:
    """The batch record a drawn line requeues (the worker's queue)."""
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / f"{BATCH}.json").write_text(
        json.dumps(
            {
                "batch_id": BATCH,
                "path": str(registry_dir.parent / "scans" / BATCH),
                "status": "review",
                "arrived_at": "2026-10-27T12:00:00+00:00",
                "pages": {PAGE: "hash-1"},
                "fingerprint": ["hash-1"],
            }
        ),
        encoding="utf-8",
    )


def test_a_correction_is_one_change_and_keeps_the_reading(store: Any) -> None:
    """The reading and its rows are untouched: the correction is the drawn
    blob plus the page's revision, and the corrected rows derive from them."""
    _seed_page(store)
    reading_before = store.pages.reading(PAGE_ID)
    rows_before = store.pages.rows(PAGE_ID)
    page = PageWrites(store).correct_rows(PAGE_ID, _drawn().encode("utf-8"), actor="p-editor")
    assert page.revision == 2
    assert [event["event_type"] for event in store.events_for(PAGE_ID, entity_kind="page")] == ["created", "superseded"]
    adjustment = store.pages.adjustment(PAGE_ID)
    assert adjustment is not None
    assert store.content.get(adjustment.sha256).decode("utf-8") == _drawn()
    assert store.pages.reading(PAGE_ID) == reading_before  # the reading blob is never rewritten
    assert store.pages.rows(PAGE_ID) == rows_before  # nor its rows


def test_a_second_correction_supersedes_the_first_and_keeps_its_blob(store: Any) -> None:
    _seed_page(store)
    writes = PageWrites(store)
    writes.correct_rows(PAGE_ID, _drawn().encode("utf-8"), actor="p-editor")
    first = store.pages.adjustment(PAGE_ID)
    assert first is not None
    other = json.dumps({"lines": [[[0.1, 0.6], [0.9, 0.6]]]}) + "\n"
    page = writes.correct_rows(PAGE_ID, other.encode("utf-8"), actor="p-editor")
    assert page.revision == 3
    second = store.pages.adjustment(PAGE_ID)
    assert second is not None and second.sha256 != first.sha256
    assert store.content.get(first.sha256).decode("utf-8") == _drawn()  # the old correction stays


def test_correcting_an_unknown_page_raises(store: Any) -> None:
    with pytest.raises(NotFound):
        PageWrites(store).correct_rows(PAGE_ID, _drawn().encode("utf-8"), actor="p-editor")


def test_the_exporter_writes_the_same_files_as_the_old_writer(store: Any, tmp_path: Path) -> None:
    """The strong check: the old path and the flipped path each write the
    two work files from the same reading and drawn lines — byte-identical."""
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    _work_files(old_dir)
    _work_files(new_dir)
    _registry(tmp_path / "registry")
    adjustments = RowAdjustments.from_dict(DRAWN)
    _ = apply_row_adjustments(BATCH, PAGE, adjustments, old_dir, registry_dir=tmp_path / "registry")

    _seed_page(store)
    archive = Archive(MemoryStore())
    export = PageCompatibility(store, new_dir)
    archive.bind_page_service(PageWrites(store), export.write)
    _ = apply_row_adjustments(BATCH, PAGE, adjustments, new_dir, registry_dir=tmp_path / "registry", archive=archive)

    old = BatchReadings(old_dir, BATCH)
    new = BatchReadings(new_dir, BATCH)
    assert new.adjustments_path(PAGE).read_bytes() == old.adjustments_path(PAGE).read_bytes()
    assert new.adjusted_rows_path(PAGE).read_bytes() == old.adjusted_rows_path(PAGE).read_bytes()


def test_the_exporter_refuses_a_reading_without_words(store: Any, tmp_path: Path) -> None:
    """A reading that carries no words cannot produce the corrected rows —
    writing them anyway would silently drop every word. Fail loud."""
    with store.change(actor="import") as change:
        change.pages.save(
            PageState(
                page_id=PAGE_ID,
                image_asset_id=PAGE_ID,
                sha256="hash-1",
                revision=1,
                rotation=0,
                category="writing",
                status="rows_pending",
            ),
            reading=_reading(),
        )
    PageWrites(store).correct_rows(PAGE_ID, _drawn().encode("utf-8"), actor="p-editor")
    with pytest.raises(PageExportError, match="no words"):
        PageCompatibility(store, tmp_path).write(PAGE_ID)


def test_the_exporter_writes_nothing_for_an_uncorrected_page(store: Any, tmp_path: Path) -> None:
    _seed_page(store)
    assert PageCompatibility(store, tmp_path).write(PAGE_ID) == ()
    assert not (tmp_path / BATCH).exists()
