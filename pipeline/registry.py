"""The registry seam — every component reads and updates batch records here,
never directly (TECHSPEC §16.13). Owns the record path and the shared
error type, so no component imports another's internals.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pipeline.batch_record import BatchRecord
from pipeline.store import VERSION_SUFFIX, PipelineStore
from tools.loft_paths import REGISTRY_DIR
from tools.store import StoreError

_BATCH_ID = re.compile(r"^[A-Za-z0-9-]+$")


class RegistryError(RuntimeError):
    """A registry or batch operation failed; the message is the plain-language line."""


# the registry's vocabulary is the one pair (batch_id, registry_dir): every
# seam function takes it, and a Registry class would wrap plain file reads
# lucidlint: ignore latent-class the pair is this module's seam shape; a class is the Phase 6 restructure
def record_path(batch_id: str, registry_dir: Path = REGISTRY_DIR) -> Path:
    if not _BATCH_ID.match(batch_id):
        raise RegistryError(f"invalid batch id: {batch_id!r}")
    return registry_dir / f"{batch_id}.json"


def load_batch(batch_id: str, registry_dir: Path = REGISTRY_DIR) -> BatchRecord:
    name = f"{batch_id}.json"
    store = PipelineStore(registry_dir)
    if not store.exists(name):
        raise RegistryError(f"no registry record for batch {batch_id!r} — adopt it first")
    return _read_record(name, store)


def set_status(batch_id: str, status: str, registry_dir: Path = REGISTRY_DIR) -> BatchRecord:
    """Move one batch's queue state and persist it — the write path for an
    explicit requeue. The record is re-read first, so every other field
    survives; the processing stamp is cleared because no pass holds it now."""
    record = load_batch(batch_id, registry_dir)
    record.status = status
    record.started_at = ""
    store = PipelineStore(registry_dir)
    store.write(f"{batch_id}.json", json.dumps(record.to_dict(), indent=1, ensure_ascii=False) + "\n")
    return record


def list_batches(registry_dir: Path = REGISTRY_DIR) -> list[BatchRecord]:
    """Every batch record, newest first — the review surface's batch list."""
    store = PipelineStore(registry_dir)
    batches = []
    for path in sorted(registry_dir.glob("*.json")):
        name = path.name
        # Skip PipelineStore versioned copies (N >= 2) if the base exists
        m = VERSION_SUFFIX.search(name)
        if m and int(m.group(1)) >= 2:
            base = name[: m.start()] + ".json"
            if store.exists(base):
                continue
        batches.append(_read_record(name, store))
    return sorted(batches, key=lambda batch: batch.arrived_at, reverse=True)


def _read_record(name: str, store: PipelineStore) -> BatchRecord:
    """The record a registry file holds; an unreadable file is a RegistryError,
    never a half-read record."""
    try:
        return BatchRecord.from_dict(json.loads(store.read_latest(name)))
    except (StoreError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RegistryError(f"registry record {name} is unreadable: {exc}") from exc
