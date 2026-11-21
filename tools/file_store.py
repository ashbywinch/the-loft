"""The archive's append-only store contract, and the refusals it makes.

The archive is immutable by requirement (docs/PRD/PRD.md — append-only): a file,
once written, is never edited or deleted; a change is a new file that
supersedes it (docs/archive-durability.md). `FileStore` is the single write
path so the invariant is enforced, not hoped for; `DiskStore` and
`MemoryStore` are its two implementations (`tools/disk_store.py`,
`tools/memory_store.py`), and the two errors are the contract's own refusals.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class StoreError(RuntimeError):
    """Base class for store failures."""


class ImmutableStoreError(StoreError):
    """Raised when a write targets an existing file — the append-only rule."""


class FileStore(ABC):
    """The archive's write path: create-new only. No edits; the one delete
    is the proposed queue's reject path — primary content (items, identity
    tables, content files) never uses it: those supersede or tombstone."""

    @abstractmethod
    def write_new(self, path: str, content: str | bytes) -> None:
        """Create *path* with *content*; raise ImmutableStoreError if it exists."""

    @abstractmethod
    def delete(self, path: str) -> None:
        """Remove *path* — the proposed-queue reject path only. Raises
        StoreError when the file is missing (a double reject is a bug)."""

    @abstractmethod
    def read(self, path: str) -> str:
        """Return the file's text content."""

    @abstractmethod
    def read_bytes(self, path: str) -> bytes:
        """Return the file's raw bytes (scans and images are binary)."""

    @abstractmethod
    def read_prefix(self, path: str, limit: int) -> str:
        """The first ``limit`` BYTES decoded as text — a bounded peek for a
        cheap content filter (a name check must not read a whole
        transcription). Raises FileNotFoundError when the
        file is missing; callers check exists() first."""

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Does the file exist?"""

    @abstractmethod
    def list(self, directory: str) -> list[str]:
        """Relative paths of every file under *directory*, stable order."""
