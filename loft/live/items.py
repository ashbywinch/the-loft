"""The items collection — the repository both the store and a change expose.

TECHSPEC/08 §19.4: `store.items` reads current state; `change.items` writes
inside the change. One item is one aggregate: its event carries the sidecar,
the content shas and the asset catalog entries, and the projection writes the
item row plus its refs, assets and content in the same transaction.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from loft.live import item_row
from loft.live.content import ContentStore
from loft.live.errors import Conflict, NotFound, StaleVersion
from loft.live.item_row import AssetRecord, ItemAsset, ItemContent, ItemProjection, ItemRef, ItemState, RowPosition
from tools.records import Item, split_content

if TYPE_CHECKING:
    from loft.live.change import Change


@dataclass(frozen=True)
class ContentInput:
    """One primary-content blob a save supplies: its kind, bytes and trust."""

    kind: str
    data: bytes
    trust: str


class Items:
    """The item collection: read through the store, write through a change."""

    def __init__(self, connection: sqlite3.Connection, content: ContentStore, change: Change | None = None) -> None:
        self.connection = connection
        self.content_store = content
        self.projection = ItemProjection(connection)
        self.change = change

    # -- reads -------------------------------------------------------------

    def get(self, item_id: str) -> Item | None:
        return self.projection.get(item_id)

    def require(self, item_id: str) -> Item:
        item = self.get(item_id)
        if item is None:
            raise NotFound(f"no item {item_id}")
        return item

    def refs(self, item_id: str) -> tuple[ItemRef, ...]:
        return self.projection.refs(item_id)

    def assets(self, item_id: str) -> tuple[ItemAsset, ...]:
        return self.projection.assets(item_id)

    def asset(self, asset_id: str) -> AssetRecord | None:
        return self.projection.asset(asset_id)

    def contents(self, item_id: str) -> tuple[ItemContent, ...]:
        return self.projection.contents(item_id)

    def content_sha(self, item_id: str, kind: str) -> str | None:
        for content in self.contents(item_id):
            if content.kind == kind:
                return content.sha256
        return None

    def content(self, item_id: str, kind: str) -> bytes | None:
        sha = self.content_sha(item_id, kind)
        return None if sha is None else self.content_store.get(sha)

    # -- writes ------------------------------------------------------------

    def save(
        self,
        item: Item,
        *,
        base: int | None = None,
        content: tuple[ContentInput, ...] = (),
        files: dict[str, bytes] | None = None,
    ) -> Item:
        """Write a create (base None) or a supersede, version-checked.

        `files` supplies the bytes of every asset the sidecar lists; `content`
        supplies primary text the sidecar no longer carries. An inline
        `story`/`transcription` field is split out first (the write seam's
        rule), so the sidecar keeps metadata only.
        """
        if self.change is None:
            raise Conflict("items.save needs a change")
        split = split_content(item)
        sidecar = split.sidecar
        current = self.get(sidecar.id)
        if base is None:
            if current is not None:
                raise Conflict(f"item {sidecar.id} exists")
            event_type = "deleted" if sidecar.status == "deleted" else "created"
            version = 1
        else:
            if current is None:
                raise NotFound(f"no item {sidecar.id}")
            if current.version != base:
                raise StaleVersion(current=current, base=base)
            event_type = "deleted" if sidecar.status == "deleted" else "superseded"
            version = base + 1
        contents = self._content_rows(sidecar, split.content, content)
        supplied = files or {}
        catalog: list[AssetRecord] = []
        for asset in sidecar.assets:
            data = supplied.get(asset.file)
            if data is None:
                raise Conflict(f"item {sidecar.id} has no bytes for asset {asset.file}")
            catalog.append(item_row.ItemRow.catalog_entry(sidecar.id, asset, data, 0))
        payload = item_payload(sidecar, contents, tuple(catalog))
        event = self.change.append(
            entity_kind="item",
            entity_id=sidecar.id,
            event_type=event_type,
            entity_version=version,
            payload=payload,
        )
        positioned = tuple(replace(record, event_seq=event["seq"]) for record in catalog)
        saved = replace(sidecar, version=version)
        self.projection.write(
            ItemState(
                item=saved,
                position=RowPosition(
                    version=version,
                    event_no=event["event_no"],
                    event_seq=event["seq"],
                    updated_at=event["recorded_at"],
                ),
                refs=item_row.ItemRow.refs(sidecar),
                assets=item_row.ItemRow.assets(sidecar, positioned),
                contents=contents,
                catalog=positioned,
            ),
            base=base,
        )
        return saved

    def _content_rows(
        self, item: Item, split: dict[str, str], supplied: tuple[ContentInput, ...]
    ) -> tuple[ItemContent, ...]:
        """Merge the split content with the caller's, put the bytes, return rows."""
        change = self.change
        if change is None:
            raise Conflict("items.save needs a change")
        return build_contents(change.content, item, split, supplied)


def build_contents(
    content_store: Any, item: Item, split: dict[str, str], supplied: tuple[ContentInput, ...]
) -> tuple[ItemContent, ...]:
    """Put every primary-content blob and return its projection rows."""
    inputs: dict[str, ContentInput] = {
        kind: ContentInput(kind=kind, data=text.encode("utf-8"), trust=default_trust(item, kind))
        for kind, text in split.items()
    }
    for supplied_row in supplied:
        inputs[supplied_row.kind] = supplied_row
    out: list[ItemContent] = []
    for kind, entry in inputs.items():
        sha = content_store.put(entry.data, mime="text/plain")
        out.append(ItemContent(kind=kind, sha256=sha, trust=entry.trust))
    return tuple(out)


def item_payload(item: Item, contents: tuple[ItemContent, ...], catalog: tuple[AssetRecord, ...]) -> str:
    """The event payload: the sidecar, its content shas and its asset catalog."""
    return json.dumps(
        {
            "item": item.to_dict(),
            "content": {row.kind: row.to_dict() for row in contents},
            "assets": [record.to_dict() for record in catalog],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def default_trust(item: Item, kind: str) -> str:
    """The old archive's only draft marker is `transcription_status`, plus the
    item's own draft status; everything else was treated as verified."""
    if item.status == "draft":
        return "draft"
    if kind == "transcription" and item.raw.get("transcription_status") == "draft":
        return "draft"
    return "confirmed"


def payload_assets(payload: dict[str, Any]) -> tuple[AssetRecord, ...]:
    """The catalog entries an item event carries."""
    return tuple(AssetRecord.from_dict(entry) for entry in payload.get("assets") or [])


def payload_contents(payload: dict[str, Any]) -> tuple[ItemContent, ...]:
    """The content rows an item event carries."""
    return tuple(ItemContent.from_dict(kind, entry) for kind, entry in (payload.get("content") or {}).items())
