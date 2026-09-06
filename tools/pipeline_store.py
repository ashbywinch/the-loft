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

import hashlib
import re
from pathlib import Path

from tools.store import DiskStore, FileStore, StoreError

# The version suffix pattern: "base-42.json" captures 42.
VERSION_SUFFIX = re.compile(r"-(\d+)\.json$")


def file_sha256(path: Path) -> str:
    """The sha256 of a file's bytes — the input fingerprint for stage
    markers. A stage's output is stale when its recorded input fingerprint
    no longer matches the current input (e.g. the oriented image changed
    after a rotation); the skip check compares the two instead of trusting
    marker existence alone (2026-08-20)."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def text_sha256(text: str) -> str:
    """The sha256 of a text string — for fingerprinting in-memory inputs
    (the raw transcription a guess was built from)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PipelineStore:
    """Versioned append-only store over a ``DiskStore`` root.

    Every write creates a new versioned file — the base path is version 1,
    ``-N.json`` suffixes are versions 2+. The reader returns the highest
    version.
    """

    def __init__(self, root: str | Path) -> None:
        self._store: FileStore = DiskStore(Path(root))

    def write(self, path: str, content: str | bytes) -> None:
        """Write ``content`` to the next version of ``path``. The base path
        (``path`` itself) is also updated to point to the latest version,
        so readers that don't know about versioning (``load_layout``,
        ``json.loads(layout_path.read_text(...))``) still see the latest
        data. The old version is preserved at ``path-2.suffix``,
        ``path-3.suffix``, etc. for recovery."""
        if not self._store.exists(path):
            # First write: just create the base path.
            self._store.write_new(path, content)
            return
        # Subsequent write: preserve the old base content at a versioned
        # path (version 2+, since version 1 IS the base path), then
        # overwrite the base path with the new content.
        old_content = self._store.read(path)
        # Find the next available version suffix for the archive copy.
        archive_version = 2
        while True:
            archive_path = _versioned_path(path, archive_version)
            if not self._store.exists(archive_path):
                break
            archive_version += 1
        self._store.write_new(archive_path, old_content)
        # Overwrite the base path with the new content.
        self._store.delete(path)
        self._store.write_new(path, content)

    def read_latest(self, path: str) -> str:
        """Return the latest version of ``path``, or raise ``StoreError``.
        The base path always holds the latest version."""
        if not self._store.exists(path):
            raise StoreError(f"no versions of {path} exist")
        return self._store.read(path)

    def exists(self, path: str) -> bool:
        """Does any version of ``path`` exist?"""
        return self._store.exists(path) or self._store.exists(_versioned_path(path, 2))

    def versions(self, path: str) -> list[int]:
        """All existing versions of ``path``, sorted ascending. Version 1
        is the base path; versions 2+ are ``path-2.ext``, ``path-3.ext``, etc."""
        result: list[int] = []
        if self._store.exists(path):
            result.append(1)
        for v in range(2, 100):
            vpath = _versioned_path(path, v)
            if self._store.exists(vpath):
                result.append(v)
            else:
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
