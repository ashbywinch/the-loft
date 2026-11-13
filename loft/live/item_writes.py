"""The item write service — one change per save (TECHSPEC/08 §19.4, B2).

The archive facade's item writes move here: a save, a tombstone and a
document agreement each open exactly one `Change`, so the event, the item
row, its refs/assets/content and the content blobs commit together. The
caller (the archive) builds the canonical sidecar and supplies the bytes; the
service owns the transaction and the base-version check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loft.live.items import ContentInput
from tools.records import Item

if TYPE_CHECKING:
    from loft.live.protocols import ItemStore


class ItemWrites:
    """The item write surface: the archive's save/delete/agreement verbs."""

    def __init__(self, store: ItemStore) -> None:
        self.store = store

    def get(self, item_id: str) -> Item | None:
        with self.store.lock:
            return self.store.items.get(item_id)

    def save(
        self,
        item: Item,
        *,
        content: tuple[ContentInput, ...] = (),
        files: dict[str, bytes] | None = None,
        base: int | None,
        actor: str,
    ) -> Item:
        """Write one item version: the event, the row and its children."""
        with self.store.change(actor=actor, note=f"save item {item.id}") as change:
            return change.items.save(item, base=base, content=content, files=files)

    def version(self, item_id: str) -> int:
        """The item's current version, 0 when the store does not hold it."""
        current = self.get(item_id)
        return current.version if current is not None else 0
