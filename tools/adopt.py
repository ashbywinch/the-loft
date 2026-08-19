"""Adopt the user's scan folders into the registry — in place, never touching them.

Adoption (MULTI-DOC-IMPORT-PRD.md R1–R4, TECH-SPEC §16.13/§16.14): a folder
of scans — ours, the user's separate scanning, or a pre-existing pile —
is hashed where it sits and registered in Loft/registry/<batch-id>.json.
The user's folder is never written, renamed, moved, or deleted. The
registry tracks the folder by content fingerprint, so if the user
reorganises, re-adopting the folder at its new location re-associates the
record (R4: reorganising costs us work, never data).

Usage:
    python tools/adopt.py "<folder of scans>" [--label "Box 1 — Letters 1977"]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.loft_paths import REGISTRY_DIR, WORK_DIR
from tools.pipeline_store import PipelineStore
from tools.store import StoreError

_BATCH_ID = re.compile(r"^[A-Za-z0-9-]+$")

# A PipelineStore versioned copy: base-2.json, base-3.json, etc.
_VERSIONED_FILE = re.compile(r"-(\d+)\.json$")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
DEFAULT_SOURCE = "external"


class AdoptionError(RuntimeError):
    """An adoption failed; the message is the plain-language line."""


def _is_versioned_copy(path: Path) -> bool:
    """Is *path* a PipelineStore versioned copy (v2+) with a sibling base file?"""
    m = _VERSIONED_FILE.search(path.name)
    if not m:
        return False
    ver = int(m.group(1))
    if ver < 2:
        return False
    base = path.with_name(path.name[: m.start()] + ".json")
    return base.exists()


def page_files(folder: Path) -> list[Path]:
    """The folder's page images, recursively, in name order."""
    if not folder.is_dir():
        raise AdoptionError(f"no such folder: {folder}")
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)


def _existing_records(registry_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    records: list[tuple[Path, dict[str, Any]]] = []
    if not registry_dir.is_dir():
        return records
    store = PipelineStore(registry_dir)
    for path in sorted(registry_dir.glob("*.json")):
        if _is_versioned_copy(path):
            continue  # PipelineStore versioned copies are read via the base path
        rel = str(path.relative_to(registry_dir))
        try:
            records.append((path, json.loads(store.read_latest(rel))))
        except (OSError, json.JSONDecodeError, StoreError) as exc:
            raise AdoptionError(f"registry record unreadable: {path} ({exc})") from exc
    return records


def register_adopted(
    folder: Path,
    *,
    label: str = "",
    source: str = DEFAULT_SOURCE,
    registry_dir: Path = REGISTRY_DIR,
    work_dir: Path = WORK_DIR,
) -> tuple[Path, str]:
    """Hash ``folder`` in place and register it; returns (record_path, outcome).

    Outcome is one of ``new``, ``already-registered``, ``re-associated``
    (the folder moved and its content fingerprint matched an existing record),
    or ``content-changed`` (same pile, pages added/removed — the record is
    updated; regenerable work stages are cleared unless the pile has
    confirmed transcriptions).
    """
    files = page_files(folder)
    if not files:
        raise AdoptionError(f"no page images found in {folder}")
    pages = {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    fingerprint = sorted(pages.values())

    match = _match_fingerprint(fingerprint, folder, registry_dir)
    if match is not None:
        return match

    # content changed (pages added/removed in the SAME pile): update its
    # record rather than silently duplicate it. Confirmed transcriptions
    # are NEVER auto-cleared: the change is flagged for a manual review.
    best = _find_same_pile(fingerprint, folder, registry_dir)
    if best is not None:
        _overlap, record_path, record = best
        return _apply_content_changed(record_path, record, pages, fingerprint, folder, work_dir, registry_dir)

    return _register_new(folder, label, source, pages, fingerprint, registry_dir)


def _match_fingerprint(fingerprint: list[str], folder: Path, registry_dir: Path) -> tuple[Path, str] | None:
    """An exact fingerprint match: already-registered (same path) or
    re-associated — the folder moved and its content matched an existing
    record (R4: reorganising costs us work, never data)."""
    for record_path, record in _existing_records(registry_dir):
        if record.get("fingerprint") == fingerprint:
            old_path = str(record.get("path", ""))
            if old_path == str(folder):
                return record_path, "already-registered"
            record["path"] = str(folder)  # re-association: the folder moved
            rel = str(record_path.relative_to(registry_dir))
            PipelineStore(registry_dir).write(rel, json.dumps(record, indent=1, ensure_ascii=False) + "\n")
            return record_path, "re-associated"
    return None


def _find_same_pile(
    fingerprint: list[str], folder: Path, registry_dir: Path
) -> tuple[int, Path, dict[str, Any]] | None:
    """The content-changed candidate: a path-matching record is the same
    pile outright; a path-MISMATCHED record with a LARGE hash overlap is
    the same pile moved AND changed (a small overlap is a duplicate-scan
    case, not the same pile — never hijacked)."""
    resolved_folder = str(folder.resolve())
    fp_set = set(fingerprint)

    def _overlap(record: dict[str, Any]) -> int:
        return len(set(record.get("fingerprint") or []) & fp_set)

    best: tuple[int, Path, dict[str, Any]] | None = None
    for record_path, record in _existing_records(registry_dir):
        if str(Path(str(record.get("path", ""))).resolve()) != resolved_folder:
            continue
        overlap = _overlap(record)
        if overlap and (best is None or overlap > best[0]):
            best = (overlap, record_path, record)
    if best is None:  # moved AND changed — only a large overlap is the same pile
        for record_path, record in _existing_records(registry_dir):
            overlap = _overlap(record)
            record_fp = set(record.get("fingerprint") or [])
            same_pile = overlap >= max(1, len(fp_set) // 2) and overlap >= max(1, len(record_fp) // 2)
            if same_pile and (best is None or overlap > best[0]):
                best = (overlap, record_path, record)
    return best


# parameter object would add a type for one use
# lucidlint: ignore long-param-list a single call site — the updated record's fields are the caller's locals; a
def _apply_content_changed(
    record_path: Path,
    record: dict[str, Any],
    pages: dict[str, str],
    fingerprint: list[str],
    folder: Path,
    work_dir: Path,
    registry_dir: Path,
) -> tuple[Path, str]:
    """Update the same-pile record: the new hashes, the pile's new home,
    and the flag for a manual review. Confirmed transcriptions are NEVER
    auto-cleared — the only copy lives in the registry record (the operator
    reviews what changed before any reprocess); without them the
    regenerable work stages are cleared."""
    batch_id = str(record["batch_id"])
    if not _BATCH_ID.match(batch_id):
        raise AdoptionError(f"record has an unsafe batch id: {batch_id!r}")  # the rmtree path below
    record["pages"] = pages
    record["fingerprint"] = fingerprint
    record["path"] = str(folder)  # the pile moved — record its new home
    record["status"] = "pending"
    record["content_changed"] = True
    confirmed = [b for b in (record.get("boundaries") or []) if b.get("status") == "confirmed"]
    if confirmed:
        rel = str(record_path.relative_to(registry_dir))
        PipelineStore(registry_dir).write(rel, json.dumps(record, indent=1, ensure_ascii=False) + "\n")
        return record_path, "content-changed"
    record["boundaries"] = None
    rel = str(record_path.relative_to(registry_dir))
    PipelineStore(registry_dir).write(rel, json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    stale_work = work_dir / batch_id
    if stale_work.exists():
        shutil.rmtree(stale_work)  # our workspace, no confirmed content — the stages regenerate
    return record_path, "content-changed"


# object would add a type for one use
# lucidlint: ignore long-param-list a single call site — the new record's fields are the caller's locals; a parameter
def _register_new(
    folder: Path, label: str, source: str, pages: dict[str, str], fingerprint: list[str], registry_dir: Path
) -> tuple[Path, str]:
    """A fresh record for an unknown pile — new batch id, registered in
    place, nothing of the user's folder touched."""
    record = {
        "batch_id": f"adopt-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}",
        "path": str(folder),
        "label": label,
        "source": source,
        "status": "pending",
        "arrived_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pages": pages,
        "fingerprint": fingerprint,
        "boundaries": None,
    }
    registry_dir.mkdir(parents=True, exist_ok=True)
    record_path = registry_dir / f"{record['batch_id']}.json"
    PipelineStore(registry_dir).write(
        f"{record['batch_id']}.json", json.dumps(record, indent=1, ensure_ascii=False) + "\n"
    )
    return record_path, "new"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="adopt", description="Register a user scan folder in the loft registry, in place"
    )
    parser.add_argument("folder", type=Path, help="the user's scan folder (never modified)")
    parser.add_argument("--label", default="", help="the envelope/pile label, if known")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="where the scans came from")
    args = parser.parse_args(argv)

    try:
        record_path, outcome = register_adopted(args.folder, label=args.label, source=args.source)
    except AdoptionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    record = json.loads(record_path.read_text(encoding="utf-8"))
    print(f"{outcome}: {len(record['pages'])} page(s) from {args.folder}")
    print(f"registry: {record_path}" + (f" (label: {args.label})" if args.label else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
