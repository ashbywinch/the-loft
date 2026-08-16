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
from pathlib import Path

# Temp-sibling naming: retry a few times with fresh entropy — a collision
# means another writer grabbed the name (O_EXCL makes it visible, never
# dangerous); a new file is created 0o666 so the kernel applies the process
# umask at creation (see atomic_write's note below).
TEMP_NAME_ATTEMPTS = 8
TEMP_NAME_RANDOM_BYTES = 8
NEW_FILE_MODE = 0o666


def atomic_write(path: Path, content: str | bytes) -> None:
    """Write ``content`` to ``path`` atomically (temp sibling + fsync + rename)."""
    data = content.encode("utf-8") if isinstance(content, str) else content
    path.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL + 0o666: the kernel applies the current umask atomically at
    # creation, so the published file keeps the umask-derived mode WITHOUT
    # the process-global os.umask() dance — which zeroed the process umask
    # for a window, letting a concurrent file creation publish 0o666
    # (world-readable) in an archive of intimate family letters (review,
    # 2026-08-14/15: two bots flagged the race).
    tmp = None
    fd = -1
    for _ in range(TEMP_NAME_ATTEMPTS):
        candidate = path.parent / f".{path.name}.{os.urandom(TEMP_NAME_RANDOM_BYTES).hex()}.tmp"
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, NEW_FILE_MODE)
            tmp = candidate
            break
        except FileExistsError:
            continue
    if tmp is None or fd < 0:
        raise FileExistsError(f"could not create a unique temp sibling for {path}")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    # then re-raises
    # lucidlint: ignore broad-except BaseException guarantees temp cleanup on EVERY exit path (incl. KeyboardInterrupt),
    except BaseException:
        _ = tmp.unlink(missing_ok=True)
        raise
