"""The item compatibility exporter — the old sidecar chain from the DB.

TECHSPEC/08 §19.4 and REWRITE-PLAN B2: after an item write the old readers
must see the same versioned tree — `assets/<id>/item.json`, `item-2.json`, …
with the content files (`story.txt`, `transcription-2.txt`, …) beside them.
The exporter replays the item's events for every version the old tree does
not hold yet, so a crash between the commit and the export leaves no gap in
the append-only chain. A version already on disk writes nothing.
"""

from __future__ import annotations

import json
from typing import Any

from loft.live.errors import LiveError
from loft.live.protocols import ItemStore
from tools.archive import Archive
from tools.records import Item


class ItemExportError(LiveError):
    """The item's tree cannot be reproduced from the event log."""


class ItemCompatibility:
    """Replay an item's events into the old sidecar/content tree."""

    CONTENT_KINDS: tuple[str, ...] = ("story", "transcription")

    def __init__(self, store: ItemStore, archive: Archive) -> None:
        self.store = store
        self.archive = archive

    def write(self, item_id: str) -> tuple[int, ...]:
        """Write the versions the tree is missing; return the versions written.

        The latest version is also repaired: a crash can leave its sidecar on
        disk and a content file missing (the old writer's sidecar-first rule),
        and a reader must never meet a sidecar that names an absent file."""
        item = self.store.items.get(item_id)
        if item is None:
            return ()
        versions = self.archive.item_versions(item_id)
        last = versions[-1] if versions else 0
        events = {int(event["entity_version"]): event for event in self.store.events_for(item_id, entity_kind="item")}
        written: list[int] = []
        for version in range(last + 1, item.version + 1):
            event = events.get(version)
            if event is None:
                raise ItemExportError(f"item {item_id} v{version} has no event to export")
            self._write_version(item_id, version, json.loads(event["payload"]))
            written.append(version)
        if not written and last == item.version:
            event = events.get(item.version)
            if event is not None:
                self._repair_content(item_id, item.version, json.loads(event["payload"]))
        return tuple(written)

    def write_all(self) -> tuple[str, ...]:
        """Catch up every item — the startup pass after a crash or a restart."""
        written: list[str] = []
        for item in self.store.items.all():
            if self.write(item.id):
                written.append(item.id)
        return tuple(written)

    def _write_version(self, item_id: str, version: int, payload: dict[str, Any]) -> None:
        sidecar = dict(payload["item"])
        if version > 1:
            sidecar.setdefault("supersedes", self.archive.item_sidecar_path(item_id, version - 1))
        else:
            sidecar.pop("supersedes", None)
        item = Item.from_dict(sidecar)
        path = self.archive.item_sidecar_path(item_id, version)
        if not self.archive.store.exists(path):
            self.archive.store.write_new(
                path,
                json.dumps(sidecar, indent=1, ensure_ascii=False),
            )
        self._write_content(item_id, version, item, payload.get("content") or {})

    def _repair_content(self, item_id: str, version: int, payload: dict[str, Any]) -> None:
        """A missing content file for a version already on disk."""
        item = Item.from_dict(payload["item"])
        self._write_content(item_id, version, item, payload.get("content") or {})

    def _write_content(self, item_id: str, version: int, item: Item, contents: dict[str, Any]) -> None:
        """Write the content files a version names, skipping any that exist."""
        for filename, sha in self._content_files(item, version, contents):
            path = self.archive.content_path(item_id, filename)
            if not self.archive.store.exists(path):
                self.archive.store.write_new(path, self.store.content.get(sha))

    def _content_files(self, item: Item, version: int, contents: dict[str, Any]) -> list[tuple[str, str]]:
        """The content asset's filename and sha for each content kind — the
        sidecar names the file, the payload carries the sha."""
        out: list[tuple[str, str]] = []
        for kind, entry in contents.items():
            asset = next((record for record in item.assets if record.kind == kind), None)
            if asset is None:
                bare = Item.CONTENT_FILES.get(kind)
                if bare is None:
                    raise ItemExportError(f"item {item.id} has unknown content kind {kind!r}")
                filename = bare if version == 1 else f"{bare[:-4]}-{version}.txt"
            else:
                filename = asset.file
            out.append((filename, str(entry["sha256"])))
        return out
