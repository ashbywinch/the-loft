"""The store surface the identity service and its exporter need.

`LiveStore` and `MemoryLiveStore` both implement it, so the service is typed
against the contract rather than one implementation (TECHSPEC/08 §19.7). The
members are `Any` on purpose: each repository's concrete type is the one the
store exposes, and the contract suite pins the behaviour on both stores.
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
