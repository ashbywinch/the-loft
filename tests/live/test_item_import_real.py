"""A4's real-archive acceptance — items, content, refs and assets from the Loft disk.

Runs only under `make verify` (`-m archive`); CI has no archive.
"""

# lucidlint: ignore-file fakefs the import reads a real archive tree and writes a real
# SQLite database — C-level I/O, the testing standard's real-FS exception.

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from loft.live.identity_map import disposition_of
from loft.live.import_identity import import_identities
from loft.live.import_items import import_items
from loft.live.store import LiveStore
from tools.archive import Archive
from tools.loft_paths import LoftPaths
from tools.records import Item, split_content
from tools.ref import Ref
from tools.store import DiskStore

ARCHIVE = LoftPaths.ARCHIVE_DIR


def _content_kinds(item: Item) -> tuple[str, ...]:
    if item.type == "story":
        return ("story", "transcription")
    return ("transcription",) if item.type in ("letter", "document") else ()


def _content(archive: Archive, item: Item) -> dict[str, str]:
    content = dict(split_content(item).content)
    for asset in item.assets:
        if asset.kind in _content_kinds(item):
            path = archive.content_path(item.id, asset.file)
            if (ARCHIVE / path).exists():
                content[asset.kind] = (ARCHIVE / path).read_text(encoding="utf-8")
    return content


def _unique_refs(refs: Iterable[Ref]) -> list[Ref]:
    seen: set[str] = set()
    out: list[Ref] = []
    for ref in refs:
        if ref.id not in seen:
            seen.add(ref.id)
            out.append(ref)
    return out


def _ref_facts(refs: Iterable[Ref]) -> list[tuple[str, str, dict[str, Any] | None]]:
    return [
        (ref.id, disposition_of(ref.status)[0], ref.date.to_dict() if ref.date else None) for ref in _unique_refs(refs)
    ]


def _facts(item: Item) -> dict[str, Any]:
    return {
        "id": item.id,
        "type": item.type,
        "title": item.title,
        "date": item.date,
        "date2": item.raw.get("date2") or None,
        "date_precision": item.date_precision,
        "status": item.status,
        "source": item.raw.get("source") or None,
        "description": item.raw.get("description") or None,
        "provenance": item.raw.get("provenance") or None,
        "sensitive": item.sensitive,
        "created": item.raw.get("created") or None,
        "identified": item.identified,
        "date_mentions": list(item.raw.get("date_mentions") or []),
        "people": _ref_facts(item.people_refs),
        "places": _ref_facts(item.place_refs),
        "orgs": _ref_facts(item.org_refs),
        "themes": _ref_facts(item.theme_refs),
        "items": _ref_facts(item.item_refs),
        "assets": [(asset.kind, asset.file, asset.caption) for asset in item.assets],
    }


def _has_duplicate_refs(item: Item) -> bool:
    return any(
        len(refs) != len({ref.id for ref in refs})
        for refs in (item.people_refs, item.place_refs, item.org_refs, item.theme_refs, item.item_refs)
    )


def _archive_facts() -> tuple[dict[str, int], Any]:
    archive = Archive(DiskStore(ARCHIVE))
    item_ids = archive.item_ids()
    versions = 0
    refs = 0
    assets: set[str] = set()
    content_shas: set[str] = set()
    missing = 0
    for item_id in item_ids:
        sidecar_versions = archive.item_versions(item_id)
        versions += len(sidecar_versions)
        latest = Item.from_dict(archive.get_item_version(item_id, max(sidecar_versions)).to_dict())
        allow_missing = latest.status == "deleted"
        for version in sidecar_versions:
            item = Item.from_dict(archive.get_item_version(item_id, version).to_dict())
            refs += sum(
                len(_unique_refs(getattr(item, attribute)))
                for attribute in ("people_refs", "place_refs", "org_refs", "theme_refs", "item_refs")
            )
            for asset in item.assets:
                if (ARCHIVE / archive.content_path(item.id, asset.file)).exists():
                    assets.add(f"{item.id}/{asset.file}")
                elif allow_missing:
                    missing += 1
                else:
                    raise AssertionError(f"live item {item.id} references a missing {asset.file}")
            for text in _content(archive, item).values():
                content_shas.add(hashlib.sha256(text.encode("utf-8")).hexdigest())
    counts = {
        "items": len(item_ids),
        "versions": versions,
        "content": len(content_shas),
        "refs": refs,
        "assets": len(assets),
    }
    return counts, archive


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE / "assets").is_dir(), reason="archive not mounted")
def test_the_real_archive_items_import_and_read_back(tmp_path: Path) -> None:
    marker = tmp_path / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    expected, archive = _archive_facts()
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        import_identities(store, ARCHIVE, backup_marker=marker)
        report = import_items(store, ARCHIVE, backup_marker=marker)
        assert report.counts == expected
        assert report.mismatches == ()
        assert store.verify_chain() == ()

        item_ids = archive.item_ids()
        live: list[str] = []
        for item_id in item_ids:
            versions = archive.item_versions(item_id)
            old = Item.from_dict(archive.get_item_version(item_id, max(versions)).to_dict())
            if not _has_duplicate_refs(old):
                live.append(item_id)
            if len(live) == 10:
                break
        for item_id in live:
            versions = archive.item_versions(item_id)
            old = Item.from_dict(archive.get_item_version(item_id, max(versions)).to_dict())
            new = store.items.require(item_id)
            assert _facts(new) == _facts(old), item_id
            assert new.version == max(versions)
            for kind, text in _content(archive, old).items():
                assert store.items.content(item_id, kind) == text.encode("utf-8"), (item_id, kind)

        for row in store.connection.execute("SELECT sha256, bytes FROM content"):
            assert hashlib.sha256(bytes(row["bytes"])).hexdigest() == row["sha256"]
        for row in store.connection.execute("SELECT sha256, path FROM assets"):
            assert hashlib.sha256((ARCHIVE / row["path"]).read_bytes()).hexdigest() == row["sha256"], row["path"]

        for item_id in item_ids:
            for ref in store.items.refs(item_id):
                target = {
                    "person": store.people.get,
                    "place": store.places.get,
                    "org": store.orgs.get,
                    "theme": store.themes.get,
                    "item": store.items.get,
                }[ref.kind](ref.ref_id)
                assert target is not None, (item_id, ref.kind, ref.ref_id)

        again = import_items(store, ARCHIVE, backup_marker=marker)
        assert again.counts == {kind: 0 for kind in expected}
        assert again.skipped == {"items": expected["items"], "versions": expected["versions"]}
    finally:
        store.close()
