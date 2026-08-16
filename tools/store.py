"""Append-only file store for the archive.

The archive is immutable by requirement (docs/prd/PRD.md — append-only): a file,
once written, is never edited or deleted; a change is a new file that
supersedes it (docs/TECH-SPEC.md §3). This module is the single write path so
the invariant is enforced, not hoped for. Tests inject ``MemoryStore``, which
fails on any write to an existing path — an accidental in-place edit fails the
test that caused it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import override

from tools.atomic import atomic_write


class StoreError(RuntimeError):
    """Base class for store failures."""


class ImmutableStoreError(StoreError):
    """Raised when a write targets an existing file — the append-only rule."""


class FileStore(ABC):
    """The archive's write path: create-new only. No edits; the one delete
    is the proposed queue's reject path — primary content (items, identity
    tables, content files) never uses it: those supersede or tombstone."""

    @abstractmethod  # lucidlint: ignore detached-method abstract interface declaration; concrete stores use self
    def write_new(self, path: str, content: str | bytes) -> None:
        """Create *path* with *content*; raise ImmutableStoreError if it exists."""

    @abstractmethod  # lucidlint: ignore detached-method abstract interface declaration; concrete stores use self
    def delete(self, path: str) -> None:
        """Remove *path* — the proposed-queue reject path only. Raises
        StoreError when the file is missing (a double reject is a bug)."""

    @abstractmethod  # lucidlint: ignore detached-method abstract interface declaration; concrete stores use self
    def read(self, path: str) -> str:
        """Return the file's text content."""

    @abstractmethod  # lucidlint: ignore detached-method abstract interface declaration; concrete stores use self
    def read_bytes(self, path: str) -> bytes:
        """Return the file's raw bytes (scans and images are binary)."""

    @abstractmethod  # lucidlint: ignore detached-method abstract interface declaration; concrete stores use self
    def read_prefix(self, path: str, limit: int) -> str:
        """The first ``limit`` BYTES decoded as text — a bounded peek for a
        cheap content filter (2026-08-11 review: a name check must not
        read a whole transcription). Raises FileNotFoundError when the
        file is missing; callers check exists() first."""

    @abstractmethod  # lucidlint: ignore detached-method abstract interface declaration; concrete stores use self
    def exists(self, path: str) -> bool:
        """Does the file exist?"""

    @abstractmethod  # lucidlint: ignore detached-method abstract interface declaration; concrete stores use self
    def list(self, directory: str) -> list[str]:
        """Relative paths of every file under *directory*, stable order."""


class DiskStore(FileStore):
    """Real store: a directory on disk (the archive folder)."""

    def __init__(self, root: Path) -> None:
        # resolve once: _resolve() returns absolute paths, so a relative root
        # made list() compare absolute paths against a relative root
        self.root: Path = Path(root).resolve()

    def _resolve(self, path: str) -> Path:
        resolved = (self.root / path).resolve()
        root = self.root.resolve()
        if not resolved.is_relative_to(root):
            raise StoreError(f"path escapes the store: {path}")
        return resolved

    @override
    def write_new(self, path: str, content: str | bytes) -> None:
        target = self._resolve(path)
        if target.exists():
            raise ImmutableStoreError(f"refusing to edit existing file: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, content)  # temp + rename: readers never see a half-written file

    @override
    def delete(self, path: str) -> None:
        target = self._resolve(path)
        if not target.exists():
            raise StoreError(f"cannot delete missing file: {path}")
        target.unlink()

    @override
    def read(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    def read_bytes(self, path: str) -> bytes:
        """Raw bytes — for scans and page images (never decode them as text)."""
        return self._resolve(path).read_bytes()

    @override
    def read_prefix(self, path: str, limit: int) -> str:
        """A bounded peek: the file's first ``limit`` bytes, decoded. The
        chunk may cut a multibyte character — errors="replace" is fine for
        a filter that only checks substring presence."""
        with self._resolve(path).open("rb") as fh:
            return fh.read(limit).decode("utf-8", errors="replace")

    @override
    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    @override
    def list(self, directory: str) -> list[str]:
        base = self._resolve(directory)
        if not base.is_dir():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())


class MemoryStore(FileStore):
    """Test double: in-memory, and any write to an existing path fails the
    test — the append-only rule is enforced in every test that uses it."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    @override
    def write_new(self, path: str, content: str | bytes) -> None:
        if path in self.files:
            raise ImmutableStoreError(f"edit detected — append-only violated: {path}")
        self.files[path] = content if isinstance(content, bytes) else content.encode("utf-8")

    @override
    def delete(self, path: str) -> None:
        if path not in self.files:
            raise StoreError(f"cannot delete missing file: {path}")
        del self.files[path]

    @override
    def read(self, path: str) -> str:
        try:
            return self.files[path].decode("utf-8")
        except KeyError as exc:
            raise FileNotFoundError(path) from exc

    @override
    def read_bytes(self, path: str) -> bytes:
        try:
            return self.files[path]
        except KeyError as exc:
            raise FileNotFoundError(path) from exc

    @override
    def read_prefix(self, path: str, limit: int) -> str:
        try:
            return self.files[path][:limit].decode("utf-8", errors="replace")
        except KeyError as exc:
            raise FileNotFoundError(path) from exc

    @override
    def exists(self, path: str) -> bool:
        return path in self.files

    @override
    def list(self, directory: str) -> list[str]:
        prefix = "" if directory in ("", ".") else directory.rstrip("/") + "/"
        return sorted(p for p in self.files if p.startswith(prefix))
