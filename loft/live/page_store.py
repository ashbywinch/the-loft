"""What a page write needs beyond the item surface — the seam's widest width.

The page work write path and its projection compat are typed against this
contract; it extends `ItemStore`, which extends `IdentityStore`
(TECHSPEC/08 §19.7).
"""

from __future__ import annotations

from typing import Any, Protocol

from loft.live.item_store import ItemStore


class PageStore(ItemStore, Protocol):
    """What a page work write needs beyond the item surface (B4)."""

    pages: Any
