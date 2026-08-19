"""Versioned pipeline store: append-only writes for the pipeline's working
data (layouts, guess text, orientation reports, registry records). Wraps
``DiskStore`` with versioned paths so a re-run never overwrites existing
data — the bad page-02 overwrite is mechanically impossible.

The versioning pattern matches the archive's ``_versioned_path``: path
``ocr-guess/page-02.layout.json`` is version 1, subsequent versions are
``ocr-guess/page-02.layout-2.json``, ``-3.json``, etc. The reader reads the
highest existing version.

Usage::

    store = PipelineStore(WORK_DIR)
    store.write("ocr-guess/page-02.layout.json", content)  # v1
    store.write("ocr-guess/page-02.layout.json", content)  # v2 (new file)
    layout = store.read_latest("ocr-guess/page-02.layout.json")  # v2
"""

from __future__ import annotations

import re
from pathlib import Path

from tools.store import DiskStore, FileStore, StoreError

# The version suffix pattern: "base-42.json" captures 42.
_VERSION_SUFFIX = re.compile(r"-(\d+)\.json$")


class PipelineStore:
    """Versioned append-only store over a ``DiskStore`` root.

    Every write creates a new versioned file — the base path is version 1,
    ``-N.json`` suffixes are versions 2+. The reader returns the highest
    version.
    """

    def __init__(self, root: str | Path) -> None:
        self._store: FileStore = DiskStore(Path(root))

    def write(self, path: str, content: str | bytes) -> None:
        """Write ``content`` to the next version of ``path``."""
        version = self._next_version(path)
        vpath = _versioned_path(path, version)
        self._store.write_new(vpath, content)

    def read_latest(self, path: str) -> str:
        """Return the latest version of ``path``, or raise ``StoreError``."""
        version = self._next_version(path) - 1
        if version < 1:
            raise StoreError(f"no versions of {path} exist")
        vpath = _versioned_path(path, version)
        return self._store.read(vpath)

    def exists(self, path: str) -> bool:
        """Does any version of ``path`` exist?"""
        return self._store.exists(path) or self._store.exists(_versioned_path(path, 2))

    def versions(self, path: str) -> list[int]:
        """All existing versions of ``path``, sorted ascending."""
        result: list[int] = []
        for v in range(1, self._next_version(path)):
            try:
                self._store.read(_versioned_path(path, v))
                result.append(v)
            except FileNotFoundError:
                break
        return result

    def _next_version(self, path: str) -> int:
        """The next unused version number for ``path``."""
        version = 1
        while True:
            vpath = _versioned_path(path, version)
            if not self._store.exists(vpath):
                return version
            version += 1

    # -- raw store access (for list and delete operations the store already supports) --

    @property
    def store(self) -> FileStore:
        return self._store


def _versioned_path(path: str, version: int) -> str:
    """One versioned path in the chain: version 1 is the bare path, version
    2+ inserts ``-N`` before the suffix."""
    if version < 1:
        raise ValueError(f"version must be >= 1, got {version}")
    if version == 1:
        return path
    stem, ext = _split_suffix(path)
    return f"{stem}-{version}{ext}"


def _split_suffix(path: str) -> tuple[str, str]:
    """Split into (stem, ext) — the last ``.json`` or ``.txt`` suffix."""
    dot = path.rfind(".")
    if dot == -1:
        return path, ""
    return path[:dot], path[dot:]
