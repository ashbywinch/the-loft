"""The content store: text and JSON blobs keyed by sha256, create-if-absent.

TECHSPEC/05 §18.3: the sha is computed from the bytes before insert; an
existing sha is re-hashed and compared, never overwritten. A2 keeps blobs
inline; the path-backed large-blob form is the same seam later.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime

from loft.live.errors import Conflict, NotFound


class ContentStore:
    """One connection's view of the `content` table."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def put(self, data: bytes, *, mime: str = "application/octet-stream") -> str:
        """Store the bytes and return their sha; an existing sha is verified."""
        sha = hashlib.sha256(data).hexdigest()
        existing = self.connection.execute("SELECT bytes, size FROM content WHERE sha256 = ?", (sha,)).fetchone()
        if existing is not None:
            stored = bytes(existing["bytes"]) if existing["bytes"] is not None else b""
            if stored != data:
                raise Conflict(f"content {sha} exists with different bytes")
            return sha
        self.connection.execute(
            "INSERT INTO content (sha256, mime, size, bytes, path, created_at) VALUES (?, ?, ?, ?, NULL, ?)",
            (sha, mime, len(data), data, datetime.now(UTC).isoformat()),
        )
        return sha

    def get(self, sha: str) -> bytes:
        """The bytes behind a sha; a missing sha is NotFound."""
        row = self.connection.execute("SELECT bytes FROM content WHERE sha256 = ?", (sha,)).fetchone()
        if row is None:
            raise NotFound(f"no content {sha}")
        return bytes(row["bytes"])

    def has(self, sha: str) -> bool:
        return self.connection.execute("SELECT 1 FROM content WHERE sha256 = ?", (sha,)).fetchone() is not None
