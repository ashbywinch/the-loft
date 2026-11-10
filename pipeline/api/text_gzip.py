"""GZip for text responses; binary assets are already compressed.

The phone pays for the projection and the module graph on every cold load;
compressing them is the single largest saving. JPEG/PNG scans, fonts and
media gain nothing from a second compression, so they pass through.
"""

from __future__ import annotations

from pathlib import Path

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import Receive, Scope, Send

_BINARY_SUFFIXES = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".avif",
        ".heic",
        ".pdf",
        ".zip",
        ".gz",
        ".woff",
        ".woff2",
        ".mp3",
        ".mp4",
        ".mov",
    }
)


class TextGZipMiddleware(GZipMiddleware):
    """The stock gzip middleware, skipping binary assets."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and Path(scope["path"]).suffix.lower() in _BINARY_SUFFIXES:
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)
