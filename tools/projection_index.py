"""The projection's index: the items a reader browses, and the day they were made.

The index is the projection's entry point (index.json): every live item,
sorted by date then id so the same archive always publishes the same index,
with the generation date of the publish. Its wire form (``{"generated": …,
"items": [...]}``) is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.records import Item


@dataclass(frozen=True)
class ProjectionIndex:
    """The published index — the day it was generated, the items it lists."""

    generated: str
    items: tuple[Item, ...]

    @classmethod
    def build(cls, items: list[Item]) -> ProjectionIndex:
        """The index of *items*, generated today: sorted by date then id —
        deterministic, so the same archive always publishes the same
        projection."""
        return cls(
            generated=date.today().isoformat(),
            items=tuple(sorted(items, key=lambda item: (item.date, item.id))),
        )

    def to_dict(self) -> dict[str, Any]:
        """The index as its wire record — index.json."""
        return {"generated": self.generated, "items": [item.to_dict() for item in self.items]}
