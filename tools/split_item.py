"""An item split at the write seam: its sidecar and its primary content.

Primary content is held in files the sidecar references (a story is
story.txt, a letter's transcription is transcription.txt), never as a
sidecar JSON field — the split is the pair the archive's write seam takes
(docs/TECHSPEC.md §3), and it travels as one record rather than a
positional pair.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.records import Item


@dataclass(frozen=True)
class SplitItem:
    """One item separated into its sidecar (the metadata) and its content
    files (kind -> the primary text)."""

    sidecar: Item
    content: dict[str, str]
