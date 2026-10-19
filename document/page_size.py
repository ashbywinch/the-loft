"""The page's size: the pixel dimensions every measure on it is relative to.

A page's size is its own record — the words, the rows and the drawn lines all
measure against it, and its wire shape (`boxes.json`'s ``page`` record) is this
class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PageSize:
    """The page's pixel dimensions."""

    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"a page has a positive size, got {self.width}x{self.height}")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PageSize:
        """The size a wire record states (``{"width": w, "height": h}``)."""
        return cls(int(raw["width"]), int(raw["height"]))

    def to_dict(self) -> dict[str, Any]:
        """The size as its wire record."""
        return {"width": self.width, "height": self.height}
