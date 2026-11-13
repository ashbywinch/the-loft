"""A4 — import items, their content, refs and assets (TECHSPEC/11).

Every sidecar version is one event (created for v1, superseded for vN/deleted
for a tombstone), carrying the canonical sidecar, the content shas and the
asset catalog entries. The tree is read-only; a re-run skips what the store
holds; a dry run writes nothing; the verified backup marker is required.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loft.live import item_row
from loft.live.backup import check_marker
from loft.live.errors import LiveError
from loft.live.identity_map import disposition_of
from loft.live.items import ContentInput, default_trust
from loft.live.protocols import ItemStore
from loft.live.store import LiveStore
from tools.archive import Archive
from tools.records import Item, split_content
from tools.ref import Ref
from tools.split_item import SplitItem
from tools.store import DiskStore


class ItemImportError(LiveError):
    """An item record could not be imported (a missing live file, a bad chain)."""


@dataclass(frozen=True)
class PlannedVersion:
    """One sidecar version ready to import — its canonical record and bytes."""

    item: Item
    version: int
    base: int | None
    content: tuple[ContentInput, ...]
    files: dict[str, bytes]


@dataclass(frozen=True)
class ItemReport:
    """What the import did (or would do) — counts, skips, operations, result."""

    counts: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    operations: tuple[str, ...] = ()
    dry_run: bool = False
    mismatches: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()


class ItemImport:
    """The item import's content vocabulary."""

    CONTENT_KINDS: dict[str, tuple[str, ...]] = {
        "story": ("story", "transcription"),
        "letter": ("transcription",),
        "document": ("transcription",),
    }


def _content_kinds(item: Item) -> tuple[str, ...]:
    return ItemImport.CONTENT_KINDS.get(item.type, ())


def _dedupe(raw: dict[str, Any]) -> dict[str, Any]:
    """Collapse a repeated ref id — the projection's key is (item, kind, id)."""
    for plural in item_row.ItemRow.REF_KINDS:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for ref in raw.get(plural) or []:
            if ref["id"] in seen:
                continue
            seen.add(ref["id"])
            out.append(ref)
        if out:
            raw[plural] = out
    return raw


@dataclass(frozen=True)
class SidecarVersion:
    """One sidecar to read — the archive, the item, the version and the policy."""

    archive: Archive
    item_id: str
    version: int
    allow_missing: bool

    def plan(self, missing: list[str]) -> PlannedVersion:
        """Canonicalise the version, reading its content and asset files."""
        item = self._read_item()
        split = split_content(item)
        files = self._read_assets(item, missing)
        content = self._read_content(item, split.content, files)
        canonical = self._canonical(split, files)
        return PlannedVersion(
            item=canonical,
            version=self.version,
            base=None if self.version == 1 else self.version - 1,
            content=tuple(content.values()),
            files=files,
        )

    def _read_item(self) -> Item:
        try:
            return Item.from_dict(self.archive.get_item_version(self.item_id, self.version).to_dict())
        except ValueError as error:
            raise ItemImportError(f"item {self.item_id} v{self.version} is not valid: {error}") from error

    def _read_assets(self, item: Item, missing: list[str]) -> dict[str, bytes]:
        """Read every file the sidecar lists; a missing live file fails loudly."""
        files: dict[str, bytes] = {}
        for asset in item.assets:
            data = self.archive.read_file_bytes(self.item_id, asset.file)
            if data is None:
                if not self.allow_missing:
                    raise ItemImportError(f"item {self.item_id} v{self.version} references missing file {asset.file}")
                missing.append(f"{self.item_id} v{self.version}: {asset.file}")
                continue
            files[asset.file] = data
        return files

    def _read_content(self, item: Item, split: dict[str, str], files: dict[str, bytes]) -> dict[str, ContentInput]:
        """Primary content: the versioned file when listed, else the inline text."""
        content: dict[str, ContentInput] = {}
        for kind in _content_kinds(item):
            asset = next((entry for entry in item.assets if entry.kind == kind), None)
            if asset is not None and asset.file in files:
                content[kind] = ContentInput(kind=kind, data=files[asset.file], trust=default_trust(item, kind))
            elif kind in split:
                content[kind] = ContentInput(
                    kind=kind, data=split[kind].encode("utf-8"), trust=default_trust(item, kind)
                )
        return content

    def _canonical(self, split: SplitItem, files: dict[str, bytes]) -> Item:
        """The sidecar with its missing assets dropped, refs deduped and chain linked."""
        raw = _dedupe(split.sidecar.to_dict())
        raw["assets"] = [asset for asset in raw.get("assets") or [] if asset["file"] in files]
        if self.version > 1:
            previous = (
                f"assets/{self.item_id}/item.json"
                if self.version == 2
                else f"assets/{self.item_id}/item-{self.version - 1}.json"
            )
            raw["supersedes"] = str(raw.get("supersedes") or previous)
        else:
            raw.pop("supersedes", None)
        return Item.from_dict(raw)


def _plan(store: ItemStore, archive: Archive) -> tuple[list[PlannedVersion], dict[str, int], list[str]]:
    plans: list[PlannedVersion] = []
    skipped = {"items": 0, "versions": 0}
    missing: list[str] = []
    for item_id in archive.item_ids():
        versions = archive.item_versions(item_id)
        stored = store.items.get(item_id)
        stored_version = stored.version if stored is not None else 0
        if stored_version > len(versions):
            raise ItemImportError(
                f"item {item_id} is at v{stored_version} in the store but the archive has {len(versions)} versions"
            )
        if stored_version == len(versions):
            skipped["items"] += 1
            skipped["versions"] += len(versions)
            continue
        latest = archive.get_item_version(item_id, max(versions))
        allow_missing = latest.status == "deleted"
        for version in versions[stored_version:]:
            source = SidecarVersion(
                archive=archive,
                item_id=item_id,
                version=version,
                allow_missing=allow_missing,
            )
            plans.append(source.plan(missing))
    return plans, skipped, sorted(missing)


def _counts(plans: list[PlannedVersion]) -> dict[str, int]:
    content_shas: set[str] = set()
    asset_ids: set[str] = set()
    refs = 0
    item_ids: set[str] = set()
    for plan in plans:
        item_ids.add(plan.item.id)
        for entry in plan.content:
            content_shas.add(hashlib.sha256(entry.data).hexdigest())
        for _ref in item_row.ItemRow.refs(plan.item):
            refs += 1
        for asset in plan.item.assets:
            asset_ids.add(item_row.ItemRow.asset_id(plan.item.id, asset.file))
    return {
        "items": len(item_ids),
        "versions": len(plans),
        "content": len(content_shas),
        "refs": refs,
        "assets": len(asset_ids),
    }


def _normal(item: Item) -> dict[str, Any]:
    raw = item.to_dict()
    raw.pop("supersedes", None)
    if raw.get("sensitive") is False:
        raw.pop("sensitive")
    if raw.get("identified") is False:
        raw.pop("identified")
    for plural in item_row.ItemRow.REF_KINDS:
        if raw.get(plural):
            raw[plural] = [
                {**Ref.from_dict(ref, plural).to_dict(), "status": disposition_of(ref.get("status"))[0]}
                for ref in raw[plural]
            ]
        elif raw.get(plural) == []:
            raw.pop(plural)
    for key in ("assets", "date_mentions"):
        if raw.get(key) == []:
            raw.pop(key)
    for key in ("source", "description", "provenance", "created", "date2"):
        if raw.get(key) == "":
            raw.pop(key)
    return raw


def _compare(store: ItemStore, plans: list[PlannedVersion]) -> tuple[str, ...]:
    mismatches: list[str] = []
    last: dict[str, PlannedVersion] = {}
    for plan in plans:
        last[plan.item.id] = plan
    for plan in last.values():
        stored = store.items.get(plan.item.id)
        if stored is None:
            mismatches.append(f"item {plan.item.id} is missing after import")
            continue
        if _normal(stored) != _normal(plan.item):
            mismatches.append(f"item {plan.item.id} v{plan.version} differs from the imported record")
        for content in plan.content:
            sha = hashlib.sha256(content.data).hexdigest()
            if store.items.content_sha(plan.item.id, content.kind) != sha:
                mismatches.append(f"item {plan.item.id} {content.kind} sha differs")
        if store.items.refs(plan.item.id) != item_row.ItemRow.refs(plan.item):
            mismatches.append(f"item {plan.item.id} refs differ")
        for asset in store.items.assets(plan.item.id):
            if store.items.asset(asset.asset_id) is None:
                mismatches.append(f"item {plan.item.id} asset {asset.asset_id} has no catalog row")
    return tuple(mismatches)


def import_items(
    store: LiveStore,
    archive_root: Path,
    *,
    backup_marker: Path,
    dry_run: bool = False,
) -> ItemReport:
    """Import every item sidecar version, its content, refs and assets."""
    check_marker(backup_marker)
    return _import(store, Archive(DiskStore(archive_root)), dry_run=dry_run)


def sync_items(store: ItemStore, archive: Archive) -> ItemReport:
    """Catch the DB up with the old tree — the item flip's opening import (B2).

    The backup marker guards the first full migration, not this catch-up: the
    DB already exists and is backed up. Versions the store holds are skipped,
    so a newer DB record is never regressed.
    """
    return _import(store, archive)


def _import(store: ItemStore, archive: Archive, *, dry_run: bool = False) -> ItemReport:
    plans, skipped, missing = _plan(store, archive)
    counts = _counts(plans)
    operations = tuple(f"item {plan.item.id} v{plan.version}" for plan in plans)
    if dry_run:
        return ItemReport(counts=counts, skipped=skipped, operations=operations, dry_run=True, missing=tuple(missing))
    if plans:
        with store.change(actor="import", note="items and content") as change:
            for plan in plans:
                change.items.save(plan.item, base=plan.base, content=plan.content, files=plan.files)
    return ItemReport(
        counts=counts,
        skipped=skipped,
        operations=operations,
        dry_run=False,
        mismatches=_compare(store, plans),
        missing=tuple(missing),
    )
