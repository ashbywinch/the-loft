"""A6's real-archive acceptance — the pipeline state from the Loft disk.

Runs only under `make verify` (`-m archive`); CI has no archive.
"""

# lucidlint: ignore-file fakefs the import reads a real registry/work tree and writes a real
# SQLite database — C-level I/O, the testing standard's real-FS exception.

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from loft.live.import_identity import import_identities
from loft.live.import_items import import_items
from loft.live.import_pipeline import import_pipeline
from loft.live.store import LiveStore
from pipeline.registry import list_batches
from pipeline.store import PipelineStore
from tools.loft_paths import LoftPaths

WORKSPACE = LoftPaths.WORKSPACE
REGISTRY = LoftPaths.REGISTRY_DIR
WORK = LoftPaths.WORK_DIR
ARCHIVE = LoftPaths.ARCHIVE_DIR


def _reading(batch_id: str, page: str) -> dict[str, Any] | None:
    stem = Path(page).stem
    store = PipelineStore(WORK)
    for kind in ("rows", "layout"):
        relative = f"{batch_id}/ocr-guess/{stem}.{kind}.json"
        if store.exists(relative):
            return json.loads(store.read_available(relative))
    return None


def _words(batch_id: str, page: str) -> list[dict[str, Any]]:
    store = PipelineStore(WORK)
    relative = f"{batch_id}/ocr-guess/{Path(page).stem}.words.json"
    return list(json.loads(store.read_available(relative)).get("words") or []) if store.exists(relative) else []


def _expected() -> dict[str, int]:
    counts = {
        "batches": 0,
        "scans": 0,
        "pages": 0,
        "readings": 0,
        "rows": 0,
        "adjustments": 0,
        "documents": 0,
        "document_pages": 0,
    }
    for batch in list_batches(REGISTRY):
        counts["batches"] += 1
        counts["scans"] += len(batch.pages)
        counts["pages"] += len(batch.pages)
        for page in batch.pages:
            reading = _reading(batch.batch_id, page)
            if reading is not None:
                counts["readings"] += 1
                counts["rows"] += len(reading.get("lines") or [])
            adjustment = WORK / batch.batch_id / "ocr-guess" / f"{Path(page).stem}.row-adjustments.json"
            if adjustment.is_file():
                counts["adjustments"] += 1
        for boundary in batch.boundaries or []:
            counts["documents"] += 1
            counts["document_pages"] += len(boundary.pages)
    return counts


@pytest.mark.archive
@pytest.mark.skipif(not (WORKSPACE / "registry").is_dir(), reason="archive not mounted")
def test_the_real_archive_pipeline_imports_and_replays(tmp_path: Path) -> None:
    marker = tmp_path / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    expected = _expected()
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        import_identities(store, ARCHIVE, backup_marker=marker)
        import_items(store, ARCHIVE, backup_marker=marker)
        report = import_pipeline(store, WORKSPACE, backup_marker=marker)
        assert report.counts == expected
        assert report.mismatches == ()
        assert store.verify_chain() == ()

        # every reading's blob re-hashes to its row's sha
        for row in store.connection.execute("SELECT page_id, reading_sha FROM readings"):
            assert hashlib.sha256(store.content.get(row["reading_sha"])).hexdigest() == row["reading_sha"]
            blob = store.pages.reading_blob(row["page_id"])
            assert blob is not None
            assert len(store.pages.rows(row["page_id"])) == len(blob.get("lines") or [])

        # a sample page's rows equal the work file
        batch = next(
            entry
            for entry in list_batches(REGISTRY)
            if any(_reading(entry.batch_id, page) is not None for page in entry.pages)
        )
        sample = next(page for page in sorted(batch.pages) if _reading(batch.batch_id, page) is not None)
        old = _reading(batch.batch_id, sample)
        assert old is not None
        rows = store.pages.rows(f"{batch.batch_id}/{sample}")
        assert [(row.ordinal, row.text, row.box) for row in rows] == [
            (index + 1, line.get("text", ""), json.dumps(line.get("box"), ensure_ascii=False))
            for index, line in enumerate(old.get("lines") or [])
        ]
        blob = store.pages.reading_blob(f"{batch.batch_id}/{sample}")
        assert blob is not None
        assert [line.get("text", "") for line in blob.get("lines") or []] == [
            line.get("text", "") for line in old.get("lines") or []
        ]
        assert len(blob.get("words") or []) == len(_words(batch.batch_id, sample))

        # the boundaries equal the registry's
        for entry in list_batches(REGISTRY):
            documents = store.documents.for_batch(entry.batch_id)
            boundaries = entry.boundaries or []
            assert [document.doc_index for document in documents] == list(range(1, len(boundaries) + 1))
            for document, boundary in zip(documents, boundaries, strict=True):
                assert [page.page_id for page in store.documents.pages(document.document_id)] == [
                    f"{entry.batch_id}/{page}" for page in boundary.pages
                ]
                assert (document.greeting, document.signoff) == (boundary.greeting, boundary.signoff)
                assert document.status == (boundary.status or "review")

        store.rebuild_pipeline()
        assert store.batches.require(batch.batch_id).version == 1
        assert len(store.pages.rows(f"{batch.batch_id}/{sample}")) == len(old.get("lines") or [])

        again = import_pipeline(store, WORKSPACE, backup_marker=marker)
        assert again.counts == {key: 0 for key in expected}
        assert again.skipped == {"batches": expected["batches"]}
    finally:
        store.close()
