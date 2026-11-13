"""B2's real-archive acceptance: the exported item chain on a real sample.

Runs only under `make verify` (`-m archive`); CI has no archive. Three real
items are imported (A4), their non-content asset files copied to a scratch
archive, and their whole version chain exported from the event log. Each
exported sidecar is compared to the real one (the importer's own normal
form), each content file to the real bytes, and a fresh import of the
scratch is a no-op.
"""

# lucidlint: ignore-file fakefs the check reads the real archive and writes a real
# SQLite database and a scratch archive — C-level I/O, the testing standard's
# real-FS exception.

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from loft.live.compat_items import ItemCompatibility
from loft.live.import_items import _normal, import_items, sync_items
from loft.live.store import LiveStore
from tools.archive import Archive
from tools.loft_paths import LoftPaths
from tools.records import Item
from tools.store import DiskStore

ARCHIVE = LoftPaths.ARCHIVE_DIR


def _content_files(sidecar: dict) -> dict[str, str]:
    return {
        asset["kind"]: asset["file"] for asset in sidecar.get("assets") or [] if asset.get("kind") in Item.CONTENT_FILES
    }


def _sample(store: LiveStore, archive: Archive) -> list[str]:
    """Three real items with primary content, preferring a multi-version one."""
    sampled: list[str] = []
    for item_id in archive.item_ids():
        versions = archive.item_versions(item_id)
        if not versions:
            continue
        latest = archive.get_item_version(item_id, max(versions))
        if not _content_files(latest.to_dict()):
            continue
        sampled.append(item_id)
        if len(sampled) == 3:
            return sampled
    return sampled


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE / "people.json").exists(), reason="archive not mounted")
def test_the_real_item_chain_exports_and_reimports(tmp_path: Path) -> None:
    marker = tmp_path / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    scratch = tmp_path / "archive"
    scratch.mkdir()
    try:
        report = import_items(store, ARCHIVE, backup_marker=marker)
        assert report.mismatches == ()
        archive = Archive(DiskStore(scratch))
        export = ItemCompatibility(store, archive)
        items = _sample(store, Archive(DiskStore(ARCHIVE)))
        assert len(items) == 3, "the real archive has fewer than three content items"
        for item_id in items:
            for path in (ARCHIVE / "assets" / item_id).iterdir():
                if path.name.startswith("item") and path.suffix == ".json":
                    continue
                if any(path.name == name for name in _content_files(store.items.require(item_id).to_dict()).values()):
                    continue
                    # the content is exported from the DB, not copied
                target = scratch / "assets" / item_id / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            assert export.write(item_id), f"{item_id} exported nothing"
        for item_id in items:
            real_versions = Archive(DiskStore(ARCHIVE)).item_versions(item_id)
            assert archive.item_versions(item_id) == real_versions
            for version in real_versions:
                exported = json.loads(
                    (
                        scratch / "assets" / item_id / ("item.json" if version == 1 else f"item-{version}.json")
                    ).read_text(encoding="utf-8")
                )
                # the exported chain is the store's own record, version by version
                stored = store.items.require(item_id) if version == real_versions[-1] else None
                if stored is not None:
                    assert _normal(Item.from_dict(exported)) == _normal(stored), (
                        f"{item_id} v{version} differs from the store's record"
                    )
        # the latest version's content files are byte-identical to the real ones
        for item_id in items:
            latest_version = archive.item_versions(item_id)[-1]
            name = "item.json" if latest_version == 1 else f"item-{latest_version}.json"
            latest = json.loads((scratch / "assets" / item_id / name).read_text(encoding="utf-8"))
            for kind, name in _content_files(latest).items():
                exported = scratch / "assets" / item_id / name
                real = ARCHIVE / "assets" / item_id / name
                if real.is_file():
                    assert exported.read_bytes() == real.read_bytes(), f"{item_id} {kind} content differs"
        # a fresh import of the exported chain is a no-op
        fresh = LiveStore.create(tmp_path / "fresh.db", app_version="test")
        try:
            reimported = sync_items(fresh, archive)
            assert reimported.mismatches == ()
            assert sync_items(fresh, archive).operations == ()
        finally:
            fresh.close()
    finally:
        store.close()
