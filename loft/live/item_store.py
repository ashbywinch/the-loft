"""What an item write needs beyond the identity surface — the seam's second width.

The item exporters and the item write verbs are typed against this contract;
`IdentityStore` is its floor and `PageStore` widens it further
(TECHSPEC/08 §19.7).
"""

from __future__ import annotations

from typing import Any, Protocol

from loft.live.identity_store import IdentityStore


class ItemStore(IdentityStore, Protocol):
    """What an item write needs beyond the identity surface (B2)."""

    items: Any
    content: Any
    reviews: Any

    def events_for(self, entity_id: str, *, entity_kind: str = "person") -> list[dict]: ...
