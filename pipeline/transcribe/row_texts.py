"""One page's reading, per row number: the writing read for each row, and the
kind the model gave that row.

The transcript sheet shows the reading beside the row it belongs to, so it needs
the page's reading indexed by row number — the text and the kind (body,
interjection, marginalia) together, because a refused or kind-less answer is
still worth showing and the two maps are always read as one. The wire this comes
from is the model's answer (`segments`), which the caller parses; the record
itself is not persisted.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RowTexts:
    """A page's reading by row number: each row's text, and each row's kind."""

    texts: dict[int, str]
    kinds: dict[int, str]
