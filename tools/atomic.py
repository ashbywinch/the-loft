"""Atomic file publication — write-then-rename, the house rule for every
component that produces a file another component may read.

A consumer must never observe a half-written file: content is written to a
temporary sibling, flushed to disk, then renamed over the target — rename
within a filesystem is atomic (POSIX). Callers keep their own invariants
(append-only checks, locking) before calling; this helper guarantees only
that the target appears complete or not at all.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: str | bytes) -> None:
    """Write ``content`` to ``path`` atomically (temp sibling + fsync + rename)."""
    data = content.encode("utf-8") if isinstance(content, str) else content
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        _ = tmp.unlink(missing_ok=True)
        raise
