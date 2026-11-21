"""The real store: the archive folder on disk.

`DiskStore` is the `FileStore` the running app writes through; its own
concerns are the filesystem's — resolving a path inside the root, and writing
a new file atomically so no reader sees half of it (docs/archive-durability.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import override

from tools.atomic import atomic_write
from tools.file_store import FileStore, ImmutableStoreError, StoreError


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

    @override
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
