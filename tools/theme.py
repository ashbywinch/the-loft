"""A curated theme: an arrangement of the archive's items a visitor browses.

A theme record is the CURATOR's editorial object — their subtitle, their
own note on each curated entry — so the archive carries it verbatim and
never rewrites a curator's fields (the projection reads it through the
accessors; validation checks what it can name, and the unknown fields stay
the curator's). Its wire form (``{"id": …, "title": …, "subtitle": …,
"items": [...], "seeded": …}``) is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Theme:
    """A curated theme — the record verbatim, with the fields the archive
    reads named."""

    raw: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.raw.get("id", ""))

    @property
    def title(self) -> str:
        return str(self.raw.get("title", ""))

    def item_ids(self) -> set[str]:
        """The ids of the entries the curator curated — what the published
        projection must resolve."""
        return {str(entry.get("id", "")) for entry in self.raw.get("items") or [] if entry.get("id")}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Theme:
        """A theme record — its id and title are required (the table's
        records are named things), everything else is the curator's."""
        theme = cls(dict(raw))
        if not theme.id.strip() or not theme.title.strip():
            raise ValueError(f"theme records need id and title: {raw!r}")
        return theme

    def to_dict(self) -> dict[str, Any]:
        """The theme as its wire record — exactly what the curator wrote."""
        return dict(self.raw)
