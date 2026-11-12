"""A7's real-archive acceptance — the whole migration gate on the Loft disk.

Runs only under `make verify` (`-m archive`); CI has no archive.
"""

# lucidlint: ignore-file fakefs the migration reads the real archive/workspace and writes a
# real SQLite database — C-level I/O, the testing standard's real-FS exception.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loft.live.migrate import VerificationInputs, migrate, verify
from loft.live.store import LiveStore
from loft.live.verify import tree_digest
from tools.loft_paths import LoftPaths

ARCHIVE = LoftPaths.ARCHIVE_DIR
WORKSPACE = LoftPaths.WORKSPACE


@pytest.mark.archive
@pytest.mark.skipif(
    not (ARCHIVE / "people.json").exists() or not (WORKSPACE / "registry").is_dir(),
    reason="archive not mounted",
)
def test_the_real_archive_migration_gate_passes(tmp_path: Path) -> None:
    marker = tmp_path / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        tree_before = tree_digest((ARCHIVE, WORKSPACE / "registry", WORKSPACE / "work"))
        dry = migrate(store, archive_dir=ARCHIVE, workspace=WORKSPACE, backup_marker=marker, dry_run=True)
        run = migrate(store, archive_dir=ARCHIVE, workspace=WORKSPACE, backup_marker=marker)
        assert dry.operations == run.operations
        assert run.mismatches == ()
        report = verify(
            store,
            run,
            VerificationInputs(
                archive_dir=ARCHIVE,
                workspace=WORKSPACE,
                dry_operations=dry.operations,
                tree_before=tree_before,
            ),
        )
        assert report.findings == ()
        assert report.ok
        assert report.counts["people"] > 0
        assert report.counts["items"] > 0
        assert report.counts["documents"] > 0
        assert report.digest_before == report.digest_after
        assert store.verify_chain() == ()
    finally:
        store.close()
