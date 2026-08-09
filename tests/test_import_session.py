"""The import session (2026-08-07, user): the document import records the
session it leaves behind — 'the document import' stays pending until the
proposed people it proposed are confirmed or dismissed. The import code
never wrote this (the miss the user flagged); this pins it."""

from __future__ import annotations

import glob
import pathlib
import shutil
from pathlib import Path

import pytest

from tools.archive import Archive
from tools.store import DiskStore

REPO = Path(__file__).resolve().parent.parent


def _seeded_scratch(scratch: pathlib.Path) -> Archive:
    """A scratch archive seeded with the live identity tables — the import's
    production base — so the merge path runs idempotently."""
    archive = Archive(DiskStore(scratch))
    for f in glob.glob("archive/*.json"):
        if pathlib.Path(f).name.startswith("imports"):
            continue  # the point: the import writes the session table (all versions — the table may have superseded)
        shutil.copy(f, scratch / pathlib.Path(f).name)
    return archive


@pytest.mark.skipif(not (REPO / "archive" / "people.json").exists(), reason="archive not bootstrapped yet")
def test_capture_document_records_the_pending_import_session(tmp_path: pathlib.Path) -> None:
    archive = _seeded_scratch(tmp_path)
    # the seeded scratch has no imports table yet — the import must write it
    assert archive.get_identity("imports") is None
    archive.capture_document(tmp_path / "no-scans")
    imports = archive.get_identity("imports")
    assert imports is not None
    pending = [s for s in imports["imports"] if s.get("status") == "pending"]
    assert len(pending) == 1
    assert pending[0]["id"] == "import-documents"
    assert pending[0]["title"] == "The document import"


@pytest.mark.skipif(not (REPO / "archive" / "people.json").exists(), reason="archive not bootstrapped yet")
def test_capture_document_is_idempotent_about_the_session(tmp_path: pathlib.Path) -> None:
    archive = _seeded_scratch(tmp_path)
    archive.capture_document(tmp_path / "no-scans")
    archive.capture_document(tmp_path / "no-scans")  # a second run adds nothing
    imports = archive.get_identity("imports")
    assert imports is not None
    assert len(imports["imports"]) == 1
