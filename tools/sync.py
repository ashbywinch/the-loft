"""The confirmation write path — the one place a reviewed document lands.

`record_confirmation` is the single write seam for the review gate (CLI
and, later, the two-app sync receiver): the confirmed text goes to
work/<batch>/ocr-confirmed/<doc>.txt and the registry's boundaries update
(replace-by-pages, append). The batch id is validated FIRST — it becomes
a path segment, and the write must never precede the guard.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.atomic import atomic_write
from tools.loft_paths import REGISTRY_DIR, WORK_DIR
from tools.registry import load_batch, record_path

_BATCH_ID = re.compile(r"^[A-Za-z0-9-]+$")


def record_confirmation(
    batch_id: str,
    doc_index: int,
    document: dict[str, Any],
    text: str | None,
    *,
    work_dir: Path = WORK_DIR,
    registry_dir: Path = REGISTRY_DIR,
) -> None:
    """The single write path for a reviewed document: the confirmed text
    lands in ocr-confirmed/<doc>.txt and the registry's boundaries are
    updated (replace-by-pages, append). ``text=None`` records a rejection —
    nothing is silently dropped. The batch id is validated FIRST
    (write-before-validate)."""
    if not _BATCH_ID.match(batch_id):
        raise ValueError(f"invalid batch id: {batch_id!r}")
    if text is not None:
        confirmed_dir = work_dir / batch_id / "ocr-confirmed"
        confirmed_dir.mkdir(parents=True, exist_ok=True)
        atomic_write(confirmed_dir / f"doc-{doc_index:02d}.txt", text)
        entry: dict[str, Any] = {**document, "status": "confirmed"}
    else:
        entry = {**document, "status": "rejected"}
    record = load_batch(batch_id, registry_dir)
    boundaries = [b for b in record.get("boundaries") or [] if b.get("pages") != document.get("pages")]
    boundaries.append(entry)
    record["boundaries"] = boundaries
    atomic_write(record_path(batch_id, registry_dir), json.dumps(record, indent=1, ensure_ascii=False) + "\n")
