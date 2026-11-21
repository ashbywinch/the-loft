"""The store double: the same contract, held in a dict.

Tests inject `MemoryStore`, which fails on any write to an existing path — an
accidental in-place edit fails the test that caused it (docs/testing-standards.md).
"""

from __future__ import annotations

from typing import override

from tools.file_store import FileStore, ImmutableStoreError, StoreError


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
