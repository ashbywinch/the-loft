"""What an identity write needs from a live store — the seam's first width.

`LiveStore` and `MemoryLiveStore` both implement it, so the identity service is
typed against the contract rather than one implementation (TECHSPEC/08 §19.7).
The members are `Any` on purpose: each repository's concrete type is the one the
store exposes, and the contract suite pins the behaviour on both stores.

The seam widens one write path at a time: `ItemStore` adds the item surface,
`PageStore` the page one, each in its own module named after it.
"""

from __future__ import annotations

from typing import Any, Protocol


class IdentityStore(Protocol):
    """What an identity write needs from a live store."""

    lock: Any
    people: Any
    places: Any
    orgs: Any
    themes: Any
    relationships: Any
    aliases: Any
    identities: Any

    def change(self, *, actor: str, note: str = "", command_id: str | None = None) -> Any: ...
