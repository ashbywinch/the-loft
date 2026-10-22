"""One cache entry's file: the name its key hashes to, in the cache
directory it lives in.

The cache's writes are all the same move — make the directory, write a
temp file, rename it into place — so the move lives on the record and a
caller names the entry it means instead of juggling a name and a directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CacheFile:
    """One cache entry's file: its name and the directory it lives in."""

    name: str
    directory: Path

    def path(self) -> Path:
        """The entry's path."""
        return self.directory / self.name

    def temp_path(self) -> Path:
        """The temp path an atomic write lands on first."""
        return self.directory / f"{self.name}.tmp"

    def write(self, blob: str) -> None:
        """Persist the entry atomically: the temp file is renamed into place,
        so a reader never sees a half-written entry."""
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic = self.temp_path()
        atomic.write_text(blob, encoding="utf-8")
        atomic.replace(self.path())
