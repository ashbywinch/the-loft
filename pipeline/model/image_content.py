"""One image a chat request carries, as the API's content part.

The part is the request's wire record (``{"type": "image_url", "image_url":
{"url": ...}}``), so it is its own type: the image travels as a data URL and
the class builds the nesting the API demands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ImageContent:
    """One image in a chat message: the data URL the API fetches it from."""

    url: str

    def to_dict(self) -> dict[str, Any]:
        """The part as its wire record."""
        return {"type": "image_url", "image_url": {"url": self.url}}
