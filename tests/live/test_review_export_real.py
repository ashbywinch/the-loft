"""B3's real-archive acceptance: the exported `imports` table.

Runs only under `make verify` (`-m archive`); CI has no archive. The real
import sessions are imported (A5), the compatibility exporter rebuilds the
old `imports.json` table, and it is compared to the real file — the sessions,
their transcripts (with the thinking text) and the decisions. A fresh import
of the exported table is a no-op.
"""

# lucidlint: ignore-file fakefs the check reads the real archive and writes a real
# SQLite database and a scratch archive — C-level I/O, the testing standard's
# real-FS exception.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loft.live.compat_reviews import ImportsCompatibility
from loft.live.import_reviews import import_reviews, sync_reviews
from loft.live.store import LiveStore
from tools.archive import Archive
from tools.loft_paths import LoftPaths
from tools.store import DiskStore

ARCHIVE = LoftPaths.ARCHIVE_DIR


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE / "people.json").exists(), reason="archive not mounted")
def test_the_real_imports_table_exports_and_reimports(tmp_path: Path) -> None:
    marker = tmp_path / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    scratch = tmp_path / "archive"
    scratch.mkdir()
    try:
        report = import_reviews(store, ARCHIVE, backup_marker=marker)
        assert report.mismatches == ()
        archive = Archive(DiskStore(scratch))
        export = ImportsCompatibility(store, archive)
        assert export.write() is True
        real = Archive(DiskStore(ARCHIVE)).get_identity("imports")
        exported = archive.get_identity("imports")
        assert exported is not None and real is not None
        assert exported.to_dict() == real.to_dict()
        assert export.write() is False  # no change, no new version
        fresh = LiveStore.create(tmp_path / "fresh.db", app_version="test")
        try:
            reimported = sync_reviews(fresh, archive)
            assert reimported.mismatches == ()
            assert sync_reviews(fresh, archive).operations == ()
        finally:
            fresh.close()
    finally:
        store.close()
