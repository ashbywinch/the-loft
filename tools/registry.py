"""The registry seam — every component reads and updates batch records here,
never directly (TECH-SPEC §16.13). Owns the record path and the shared
error type, so no component imports another's internals.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.loft_paths import REGISTRY_DIR
from tools.store import DiskStore  # noqa: F401

_BATCH_ID = re.compile(r"^[A-Za-z0-9-]+$")


class RegistryError(RuntimeError):
    """A registry or batch operation failed; the message is the plain-language line."""


def record_path(batch_id: str, registry_dir: Path = REGISTRY_DIR) -> Path:
    if not _BATCH_ID.match(batch_id):
        raise RegistryError(f"invalid batch id: {batch_id!r}")
    return registry_dir / f"{batch_id}.json"


def load_batch(batch_id: str, registry_dir: Path = REGISTRY_DIR) -> dict[str, Any]:
    path = record_path(batch_id, registry_dir)
    if not path.exists():
        raise RegistryError(f"no registry record for batch {batch_id!r} — adopt it first")
    return json.loads(path.read_text(encoding="utf-8"))


def list_batches(registry_dir: Path = REGISTRY_DIR) -> list[dict[str, Any]]:
    """Every batch record, newest first — the review surface's batch list."""
    batches = []
    for path in sorted(registry_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryError(f"registry record {path.name} is unreadable: {exc}") from exc
        batches.append(record)
    return sorted(batches, key=lambda b: str(b.get("arrived_at", "")), reverse=True)
