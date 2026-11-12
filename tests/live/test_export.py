# lucidlint: ignore-file fakefs the export reads a real archive/workspace and writes real
# files — C-level I/O, the testing standard's real-FS exception.
"""A8 — the human archive and the operational backup, on the migrated fixture."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from loft.live.export import DateTree, ExportError, HumanArchive, date_text
from loft.live.identity_map import date_value
from loft.live.items import ContentInput
from loft.live.migrate import migrate
from loft.live.operational import BackupError, OperationalBackup
from loft.live.store import LiveStore
from loft.live.verify import Projections, tree_digest
from tests.live.test_migrate import _fixture
from tools.loft_paths import LoftPaths
from tools.records import Item


def _migrated(tmp_path: Path) -> tuple[LiveStore, Path, Path, Path]:
    archive, workspace, marker = _fixture(tmp_path)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker)
    return store, archive, workspace, marker


def _add_pending_item(store: LiveStore) -> None:
    item = Item.from_dict(
        {
            "id": "item-2",
            "type": "letter",
            "title": "A draft letter",
            "date": "1961",
            "date_precision": "year",
            "status": "catalogued",
            "transcription_status": "draft",
            "assets": [{"kind": "transcription", "file": "transcription.txt", "caption": "The transcription"}],
            "people": [],
            "places": [],
            "themes": [],
        }
    )
    with store.change(actor="import") as change:
        change.items.save(
            item,
            content=(ContentInput(kind="transcription", data=b"Draft words\n", trust="draft"),),
            files={"transcription.txt": b"Draft words\n"},
        )


def _add_draft_item(store: LiveStore) -> None:
    item = Item.from_dict(
        {
            "id": "item-3",
            "type": "story",
            "title": "An unfinished story",
            "date": "1962",
            "date_precision": "year",
            "status": "draft",
            "story": "The words of a draft.",
            "assets": [],
            "people": [],
            "places": [],
            "themes": [],
        }
    )
    with store.change(actor="import") as change:
        change.items.save(item)


def test_the_human_archive_writes_the_document_leg_and_its_views(tmp_path: Path) -> None:
    store, archive, workspace, _marker = _migrated(tmp_path)
    _add_pending_item(store)
    _add_draft_item(store)
    try:
        tree = tree_digest((archive, workspace / "registry", workspace / "work"))
        out = tmp_path / "human"
        report = HumanArchive(store, out).write()
        assert report.counts["items"] == 2  # item-1 and item-2; the draft item-3 is not browsable
        leaf = out / "documents" / "All Time" / "item-1"
        data = json.loads((leaf / "item.json").read_text(encoding="utf-8"))
        assert data["schema"] == 2
        assert (data["id"], data["type"], data["title"]) == ("item-1", "document", "The letter")
        assert data["date"]["from"] == {"year": 1960}
        assert data["date_text"] == "1960"
        assert data["transcription"] == "transcription.txt"
        assert (leaf / "transcription.txt").read_bytes() == b"Dear friend,\n\nThe words.\n"
        assert data["people"][0]["id"] == "p-1" and data["people"][0]["name"] == "Person One"
        assert data["assets"][0]["kind"] == "page"
        assert data["assets"][0]["sha256"] == hashlib.sha256(b"<svg xmlns='http://www.w3.org/2000/svg'/>").hexdigest()

        pending = json.loads((out / "documents" / "All Time" / "item-2" / "item.json").read_text(encoding="utf-8"))
        assert pending["transcription"] == "pending"
        assert not (out / "documents" / "All Time" / "item-2" / "transcription.txt").exists()
        assert not (out / "documents" / "All Time" / "item-3").exists()

        assert "Person One" in (out / "PEOPLE.md").read_text(encoding="utf-8")
        assert "The letter" in (out / "INDEX.md").read_text(encoding="utf-8")
        assert "The Loft" in (out / "README.md").read_text(encoding="utf-8")
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["counts"]["items"] == 2
        assert manifest["pages"][0]["batch"] == "batch-1"
        assert manifest["assets"][0]["kind"] == "page"

        subprocess.run(["sha256sum", "-c", "manifest.sha256"], cwd=out, check=True, capture_output=True)
        assert HumanArchive(store, out).verify().ok
        assert tree_digest((archive, workspace / "registry", workspace / "work")) == tree
    finally:
        store.close()


def test_the_export_refuses_the_live_tree(tmp_path: Path) -> None:
    store, _archive, _workspace, _marker = _migrated(tmp_path)
    try:
        with pytest.raises(ExportError):
            HumanArchive(store, LoftPaths.ARCHIVE_DIR).write()
        with pytest.raises(ExportError):
            HumanArchive(store, LoftPaths.WORKSPACE / "archive").write()
    finally:
        store.close()


def test_the_date_tree_splits_at_the_document_count() -> None:
    items = tuple(
        Item.from_dict(
            {
                "id": f"item-{index:03d}",
                "type": "document",
                "title": f"Item {index}",
                "date": f"1963-{(index % 12) + 1:02d}-01",
                "date_precision": "exact",
                "status": "catalogued",
                "assets": [],
                "people": [],
                "places": [],
                "themes": [],
            }
        )
        for index in range(201)
    )
    tree = DateTree(items)
    leaves = Counter(tree.leaf(item) for item in items)
    assert len(leaves) == 2
    assert all(count >= int(201 * 0.4) for count in leaves.values())
    assert any("Before" in leaf for leaf in leaves)
    assert any("On or after" in leaf for leaf in leaves)


def test_date_text_renders_every_qualifier() -> None:
    assert date_text(date_value("1963-05-14", "exact")) == "14 May 1963"
    assert date_text(date_value("1963", "year")) == "1963"
    assert date_text(date_value("1963-05", "month")) == "May 1963"
    assert date_text(date_value("1963", "approx")) == "about 1963"
    assert date_text(date_value("1881", "before")) == "before 1881"
    assert date_text(date_value("1880", "between", "1881")) == "between 1880 and 1881"


def test_the_operational_backup_restores_an_equal_database(tmp_path: Path) -> None:
    store, archive, workspace, _marker = _migrated(tmp_path)
    _add_pending_item(store)
    _add_draft_item(store)
    try:
        tree = tree_digest((archive, workspace / "registry", workspace / "work"))
        out = tmp_path / "backup"
        report = OperationalBackup(store, out).write()
        assert (out / "db.sql").is_file()
        assert (out / "README.md").is_file()
        assert (out / "schema" / "truth.sql").is_file()
        assert (out / "migrations" / "0001.sql").is_file()
        assert (out / "vocabulary.json").is_file()
        assert (out / "db-manifest.json").is_file()
        assert report.counts["items"] == 3  # the backup keeps the draft too
        assert list((out / "content").rglob("*"))
        assert list((out / "events").glob("*.jsonl"))

        verification = OperationalBackup(store, out).verify()
        assert verification.ok
        assert verification.counts["items"] == 3
        restored = sqlite3.connect(":memory:")
        restored.row_factory = sqlite3.Row
        try:
            restored.executescript((out / "db.sql").read_text(encoding="utf-8"))
            assert Projections.digest(restored) == Projections.digest(store.connection)
        finally:
            restored.close()
        assert tree_digest((archive, workspace / "registry", workspace / "work")) == tree
    finally:
        store.close()


def test_the_backup_refuses_the_live_tree(tmp_path: Path) -> None:
    store, _archive, _workspace, _marker = _migrated(tmp_path)
    try:
        with pytest.raises(BackupError):
            OperationalBackup(store, LoftPaths.WORKSPACE / "backup").write()
        with pytest.raises(BackupError):
            OperationalBackup(store, LoftPaths.ARCHIVE_DIR).write()
    finally:
        store.close()
