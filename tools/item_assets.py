"""One item's asset files as publish writes them.

Publish copies every asset an item's sidecar references into the projection's
assets/<item id>/ folder — the real scan's bytes when it is in the archive,
else a generated placeholder. The item and its files travel as one record
rather than a two-level dict.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ItemAssets:
    """One item's asset files: filename -> content (a real scan's bytes, the
    placeholder's text otherwise)."""

    item_id: str
    files: dict[str, str | bytes]
