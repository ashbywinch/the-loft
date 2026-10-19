"""One text block a chat request carries, as the API's content part.

The part is the request's wire record (``{"type": "text", "text": ...}``) —
the prompt that rides beside an image in the same message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TextContent:
    """One text block in a chat message."""

    text: str

    def to_dict(self) -> dict[str, Any]:
        """The part as its wire record."""
        return {"type": "text", "text": self.text}
