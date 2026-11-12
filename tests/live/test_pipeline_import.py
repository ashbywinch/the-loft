# lucidlint: ignore-file fakefs the import reads a real registry/work tree and writes a real
# SQLite database — C-level I/O, the testing standard's real-FS exception.
"""A6 — the pipeline import: counts, readings, rows, boundaries, replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from loft.live.errors import LiveError
from loft.live.import_pipeline import import_pipeline
from loft.live.store import LiveStore
from tools.records import Item


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(json.dumps(value, indent=1), encoding="utf-8")


def _batch() -> dict[str, Any]:
    return {
        "batch_id": "batch-1",
        "path": "/scans/pile",
        "label": "A pile",
        "source": "external",
        "status": "review",
        "arrived_at": "2026-01-01T00:00:00+00:00",
        "started_at": "",
        "started_pid": 0,
        "started_host": "",
        "pages": {"page-01.jpg": "sha-01", "page-02.jpg": "sha-02"},
        "fingerprint": ["sha-01", "sha-02"],
        "boundaries": [
            {
                "pages": ["page-01.jpg", "page-02.jpg"],
                "greeting": "Dear family",
                "signoff": None,
            },
            {
                "pages": ["page-02.jpg"],
                "greeting": None,
                "signoff": None,
                "status": "confirmed",
                "item_id": "item-1",
                "batch_id": "batch-1",
                "doc_index": 2,
                "text": "The confirmed words.",
                "confirmed_at": "2026-01-02T00:00:00+00:00",
            },
        ],
    }


def _workspace(root: Path) -> Path:
    _write(root / "registry" / "batch-1.json", _batch())
    _write(root / "work" / "batch-1" / "classify.json", {"page-01.jpg": {"kind": "text"}})
    _write(
        root / "work" / "batch-1" / "oriented" / "rotations.json",
        {"page-01.jpg": {"degrees": 180, "strong": 42, "scores": {"180": 42}}},
    )
    _write(
        root / "work" / "batch-1" / "ocr-guess" / "page-01.rows.json",
        {
            "page": "page-01.jpg",
            "width": 100,
            "height": 200,
            "rotation": 0,
            "revision": 1,
            "corrected": "abc123",
            "lines": [
                {
                    "index": 0,
                    "text": "Hello",
                    "box": [1, 2, 3, 4],
                    "orientation": 0,
                    "box_source": "reader",
                    "words": [],
                },
                {
                    "index": 1,
                    "text": "World",
                    "box": [5, 6, 7, 8],
                    "orientation": 0,
                    "box_source": "reader",
                    "words": [],
                },
            ],
        },
    )
    _write(
        root / "work" / "batch-1" / "ocr-guess" / "page-01.words.json",
        {"words": [{"x0": 1, "y0": 2, "x1": 3, "y1": 4, "line": 0, "baseline": 3, "waistline": 2}]},
    )
    _write(root / "work" / "batch-1" / "ocr-guess" / "page-01.row-adjustments.json", b'{"lines":[]}')
    _write(root / "work" / "batch-1" / "ocr-guess" / "page-01.rows-adjusted.json", b'{"rows":[]}')
    marker = root / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    return marker


def _item() -> Item:
    return Item.from_dict(
        {
            "id": "item-1",
            "type": "document",
            "title": "The letter",
            "date": "1960",
            "date_precision": "year",
            "status": "catalogued",
            "assets": [],
            "people": [],
            "places": [],
            "themes": [],
        }
    )


def _imported(tmp_path: Path) -> tuple[LiveStore, Any]:
    root = tmp_path / "workspace"
    marker = _workspace(root)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    with store.change(actor="import") as change:
        change.items.save(_item())
    report = import_pipeline(store, root, backup_marker=marker)
    return store, report


def test_the_pipeline_import_counts_batches_pages_readings_rows_and_boundaries(tmp_path: Path) -> None:
    store, report = _imported(tmp_path)
    try:
        assert report.counts == {
            "batches": 1,
            "scans": 2,
            "pages": 2,
            "readings": 1,
            "rows": 2,
            "adjustments": 1,
            "documents": 2,
            "document_pages": 3,
        }
        assert report.per_batch["batch-1"]["pages"] == 2
        assert report.skipped == {"batches": 0}
        assert report.mismatches == ()
        assert store.verify_chain() == ()
    finally:
        store.close()


def test_the_batch_pages_and_scans_read_back(tmp_path: Path) -> None:
    store, _report = _imported(tmp_path)
    try:
        batch = store.batches.require("batch-1")
        assert (batch.label, batch.status, batch.content_changed) == ("A pile", "review", False)
        assert [scan.ordinal for scan in store.batches.scans("batch-1")] == [0, 1]
        page = store.pages.require("batch-1/page-01.jpg")
        assert (page.rotation, page.category, page.status, page.revision) == (180, "text", "rows_adjusted", 1)
        other = store.pages.require("batch-1/page-02.jpg")
        assert (other.category, other.status) == ("", "new")
        assert store.pages.reading("batch-1/page-02.jpg") is None
    finally:
        store.close()


def test_the_reading_and_rows_equal_the_work_file(tmp_path: Path) -> None:
    store, _report = _imported(tmp_path)
    try:
        reading = store.pages.reading("batch-1/page-01.jpg")
        assert reading is not None
        assert (reading.rows, reading.words, reading.corrected_sha) == (2, 1, "abc123")
        assert hashlib.sha256(store.content.get(reading.reading_sha)).hexdigest() == reading.reading_sha
        rows = store.pages.rows("batch-1/page-01.jpg")
        assert [(row.ordinal, row.text, row.source, row.trust) for row in rows] == [
            (1, "Hello", "human", "guess"),
            (2, "World", "human", "guess"),
        ]
        assert rows[0].box == "[1, 2, 3, 4]"
        blob = store.pages.reading_blob("batch-1/page-01.jpg")
        assert blob is not None
        assert [line["text"] for line in blob["lines"]] == ["Hello", "World"]
        assert len(blob["words"]) == 1
        assert store.pages.adjustment("batch-1/page-01.jpg") is not None
    finally:
        store.close()


def test_the_boundaries_become_documents_with_the_item_link(tmp_path: Path) -> None:
    store, _report = _imported(tmp_path)
    try:
        documents = store.documents.for_batch("batch-1")
        assert [document.doc_index for document in documents] == [1, 2]
        assert [document.status for document in documents] == ["review", "confirmed"]
        first, second = documents
        assert [page.page_id for page in store.documents.pages(first.document_id)] == [
            "batch-1/page-01.jpg",
            "batch-1/page-02.jpg",
        ]
        assert first.greeting == "Dear family"
        assert second.item_id == "item-1"
        assert (second.title, second.date, second.date_precision) == ("The letter", "1960", "year")
        assert second.text_sha == hashlib.sha256(b"The confirmed words.").hexdigest()
        assert second.text_sha is not None
        assert store.content.get(second.text_sha) == b"The confirmed words."
    finally:
        store.close()


def test_a_dry_run_writes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    marker = _workspace(root)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        report = import_pipeline(store, root, backup_marker=marker, dry_run=True)
        assert report.dry_run is True
        assert report.counts["pages"] == 2
        assert store.batches.get("batch-1") is None
        assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert store.connection.execute("SELECT COUNT(*) FROM content").fetchone()[0] == 0
    finally:
        store.close()


def test_a_rerun_is_a_no_op(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    marker = _workspace(root)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        import_pipeline(store, root, backup_marker=marker)
        second = import_pipeline(store, root, backup_marker=marker)
        assert second.counts == {key: 0 for key in second.counts}
        assert second.skipped == {"batches": 1}
        assert second.operations == ()
        assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 5
    finally:
        store.close()


def test_a_rebuild_replays_the_pipeline(tmp_path: Path) -> None:
    store, _report = _imported(tmp_path)
    try:
        store.rebuild_pipeline()
        assert store.batches.require("batch-1").version == 1
        assert len(store.batches.scans("batch-1")) == 2
        assert [row.text for row in store.pages.rows("batch-1/page-01.jpg")] == ["Hello", "World"]
        reading = store.pages.reading("batch-1/page-01.jpg")
        assert reading is not None and reading.rows == 2
        assert len(store.documents.for_batch("batch-1")) == 2
        assert store.documents.require("batch-1/doc-2").text_sha is not None
    finally:
        store.close()


def test_the_import_refuses_without_a_verified_marker(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _workspace(root)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        with pytest.raises(LiveError):
            import_pipeline(store, root, backup_marker=tmp_path / "missing.json")
    finally:
        store.close()
