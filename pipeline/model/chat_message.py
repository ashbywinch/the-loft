"""One message in a chat-completions request: its role and its content.

The message is the request's wire record (``{"role", "content"}``) — the
content a plain string for a text call, a list of parts when images ride
the same message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.model.image_content import ImageContent
from pipeline.model.text_content import TextContent

Content = str | list[ImageContent | TextContent]


@dataclass(frozen=True)
class ChatMessage:
    """One message of a chat request: who speaks and what they say."""

    role: str
    content: Content

    def to_dict(self) -> dict[str, Any]:
        """The message as its wire record."""
        content: Any = self.content if isinstance(self.content, str) else [part.to_dict() for part in self.content]
        return {"role": self.role, "content": content}
