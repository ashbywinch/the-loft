"""A8's real-archive acceptance — the human archive and the backup.

Runs only under `make verify` (`-m archive`); CI has no archive.
"""

# lucidlint: ignore-file fakefs the export/backup read the real archive/workspace and write
# real files and a SQLite database — C-level I/O, the test standard's real-FS exception.

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from loft.live.export import HumanArchive
from loft.live.migrate import migrate
from loft.live.operational import OperationalBackup
from loft.live.store import LiveStore
from loft.live.verify import Projections, tree_digest
from tools.loft_paths import LoftPaths

ARCHIVE = LoftPaths.ARCHIVE_DIR
WORKSPACE = LoftPaths.WORKSPACE


@pytest.mark.archive
@pytest.mark.skipif(
    not (ARCHIVE / "people.json").exists() or not (WORKSPACE / "registry").is_dir(),
    reason="archive not mounted",
)
def test_the_real_human_archive_and_backup(tmp_path: Path) -> None:
    marker = tmp_path / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        migrate(store, archive_dir=ARCHIVE, workspace=WORKSPACE, backup_marker=marker)
        tree = tree_digest((ARCHIVE, WORKSPACE / "registry", WORKSPACE / "work"))

        human = tmp_path / "human"
        report = HumanArchive(store, human).write()
        assert report.counts["items"] == sum(1 for item in store.items.all() if item.status == "catalogued")
        verification = HumanArchive(store, human).verify()
        assert verification.findings == ()
        assert "sha256sum -c" in (human / "README.md").read_text(encoding="utf-8")
        assert (human / "INDEX.md").is_file() and (human / "manifest.json").is_file()
        subprocess.run(["sha256sum", "-c", "manifest.sha256"], cwd=human, check=True, capture_output=True)
        manifest = json.loads((human / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["counts"]["items"] == report.counts["items"]
        assert len(manifest["pages"]) == sum(len(store.batches.scans(batch.batch_id)) for batch in store.batches.all())

        # the walkthrough: a catalogued item's leaf, its confirmed text and its index line
        item, kind = next(
            (entry, row.kind)
            for entry in store.items.all()
            if entry.status == "catalogued"
            for row in store.items.contents(entry.id)
            if row.trust == "confirmed"
        )
        leaf = next(path.parent for path in human.rglob("item.json") if path.parent.name == item.id)
        data = json.loads((leaf / "item.json").read_text(encoding="utf-8"))
        assert data["id"] == item.id and data["schema"] == 2
        assert data[kind] == f"{kind}.txt"
        assert (leaf / data[kind]).read_bytes() == store.items.content(item.id, kind)
        assert item.title in (human / "INDEX.md").read_text(encoding="utf-8")

        backup = tmp_path / "backup"
        backup_report = OperationalBackup(store, backup).write()
        backup_check = OperationalBackup(store, backup).verify()
        assert backup_check.findings == ()
        assert backup_report.exported_through > 0
        restored = sqlite3.connect(":memory:")
        restored.row_factory = sqlite3.Row
        try:
            restored.executescript((backup / "db.sql").read_text(encoding="utf-8"))
            assert Projections.digest(restored) == Projections.digest(store.connection)
            assert int(restored.execute("SELECT COUNT(*) FROM items").fetchone()[0]) == backup_report.counts["items"]
        finally:
            restored.close()
        assert tree_digest((ARCHIVE, WORKSPACE / "registry", WORKSPACE / "work")) == tree
    finally:
        store.close()
