"""Adopt the user's scan folders into the registry — in place, never touching them.

Adoption (MULTI-DOC-IMPORT-PRD.md R1–R4, TECHSPEC §16.13/§16.14): a folder
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

from pipeline.adoption_result import AdoptionResult
from pipeline.batch_record import BatchRecord
from pipeline.pile_candidate import PileCandidate
from pipeline.registry_entry import RegistryEntry
from pipeline.store import PipelineStore
from tools.loft_paths import REGISTRY_DIR, WORK_DIR
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


class _Adoption:
    """One scan folder's adoption: the content fingerprint it hashes to
    and the registry it registers into — the shared vocabulary of the
    match/recover/register steps (a folder moved, changed content, or
    arrived fresh all resolve against the same pair; R4: reorganising
    costs us work, never data)."""

    def __init__(
        self,
        folder: Path,
        *,
        label: str = "",
        source: str = DEFAULT_SOURCE,
        registry_dir: Path = REGISTRY_DIR,
        work_dir: Path = WORK_DIR,
    ) -> None:
        self.folder = folder
        files = self.page_files()
        if not files:
            raise AdoptionError(f"no page images found in {folder}")
        self.label = label
        self.source = source
        self.registry_dir = registry_dir
        self.work_dir = work_dir
        self.pages = {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        self.fingerprint = sorted(self.pages.values())

    def page_files(self) -> list[Path]:
        """The adoption's folder's page images, recursively, in name order."""
        folder = self.folder
        if not folder.is_dir():
            raise AdoptionError(f"no such folder: {folder}")
        return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)

    def _existing_records(self) -> list[RegistryEntry]:
        """The registry's records — the match and same-pile candidates."""
        registry_dir = self.registry_dir
        entries: list[RegistryEntry] = []
        if not registry_dir.is_dir():
            return entries
        store = PipelineStore(registry_dir)
        for path in sorted(registry_dir.glob("*.json")):
            if _is_versioned_copy(path):
                continue  # PipelineStore versioned copies are read via the base path
            rel = str(path.relative_to(registry_dir))
            try:
                entries.append(RegistryEntry(path, BatchRecord.from_dict(json.loads(store.read_latest(rel)))))
            except (OSError, json.JSONDecodeError, StoreError, KeyError, TypeError, ValueError) as exc:
                raise AdoptionError(f"registry record unreadable: {path} ({exc})") from exc
        return entries

    def _save(self, entry: RegistryEntry) -> None:
        """Write the entry's record back where it came from."""
        rel = str(entry.path.relative_to(self.registry_dir))
        PipelineStore(self.registry_dir).write(
            rel, json.dumps(entry.record.to_dict(), indent=1, ensure_ascii=False) + "\n"
        )

    def match_fingerprint(self) -> AdoptionResult | None:
        """An exact fingerprint match: already-registered (same path) or
        re-associated — the folder moved and its content matched an existing
        record (R4: reorganising costs us work, never data)."""
        for entry in self._existing_records():
            if entry.record.fingerprint != self.fingerprint:
                continue
            if entry.record.path == self.folder:
                return AdoptionResult(entry.path, "already-registered")
            entry.record.re_home(self.folder)  # re-association: the folder moved
            self._save(entry)
            return AdoptionResult(entry.path, "re-associated")
        return None

    def find_same_pile(self) -> PileCandidate | None:
        """The content-changed candidate: a path-matching record is the same
        pile outright; a path-MISMATCHED record with a LARGE hash overlap is
        the same pile moved AND changed (a small overlap is a duplicate-scan
        case, not the same pile — never hijacked)."""
        resolved_folder = str(self.folder.resolve())
        fp_set = set(self.fingerprint)

        def _overlap(record: BatchRecord) -> int:
            return len(set(record.fingerprint) & fp_set)

        best: PileCandidate | None = None
        for entry in self._existing_records():
            if str(entry.record.path.resolve()) != resolved_folder:
                continue
            overlap = _overlap(entry.record)
            if overlap and (best is None or overlap > best.overlap):
                best = PileCandidate(overlap, entry.path, entry.record)
        if best is None:  # moved AND changed — only a large overlap is the same pile
            for entry in self._existing_records():
                record = entry.record
                overlap = _overlap(record)
                record_fp = set(record.fingerprint)
                same_pile = overlap >= max(1, len(fp_set) // 2) and overlap >= max(1, len(record_fp) // 2)
                if same_pile and (best is None or overlap > best.overlap):
                    best = PileCandidate(overlap, entry.path, record)
        return best

    def apply_content_changed(self, candidate: PileCandidate) -> AdoptionResult:
        """Update the same-pile record: the new hashes, the pile's new home,
        and the flag for a manual review. Confirmed transcriptions are NEVER
        auto-cleared — the only copy lives in the registry record (the
        operator reviews what changed before any reprocess); without them the
        regenerable work stages are cleared."""
        entry = RegistryEntry(candidate.path, candidate.record)
        record = entry.record
        if not _BATCH_ID.match(record.batch_id):
            raise AdoptionError(f"record has an unsafe batch id: {record.batch_id!r}")  # the rmtree path below
        confirmed = record.confirmed_boundaries()
        record.apply_content_changed(self.folder, self.pages, self.fingerprint)
        self._save(entry)
        if not confirmed:
            stale_work = self.work_dir / record.batch_id
            if stale_work.exists():
                shutil.rmtree(stale_work)  # our workspace, no confirmed content — the stages regenerate
        return AdoptionResult(entry.path, "content-changed")

    def register_new(self) -> AdoptionResult:
        """A fresh record for an unknown pile — new batch id, registered in
        place, nothing of the user's folder touched."""
        record = BatchRecord(
            batch_id=f"adopt-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}",
            path=self.folder,
            label=self.label,
            source=self.source,
            arrived_at=datetime.now(UTC).isoformat(timespec="seconds"),
            pages=self.pages,
            fingerprint=self.fingerprint,
        )
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        record_path = self.registry_dir / f"{record.batch_id}.json"
        PipelineStore(self.registry_dir).write(
            f"{record.batch_id}.json", json.dumps(record.to_dict(), indent=1, ensure_ascii=False) + "\n"
        )
        return AdoptionResult(record_path, "new")


def register_adopted(
    folder: Path,
    *,
    label: str = "",
    source: str = DEFAULT_SOURCE,
    registry_dir: Path = REGISTRY_DIR,
    work_dir: Path = WORK_DIR,
) -> AdoptionResult:
    """Hash ``folder`` in place and register it; returns where the record
    landed and the outcome.

    Outcome is one of ``new``, ``already-registered``, ``re-associated``
    (the folder moved and its content fingerprint matched an existing record),
    or ``content-changed`` (same pile, pages added/removed — the record is
    updated; regenerable work stages are cleared unless the pile has
    confirmed transcriptions).
    """
    adoption = _Adoption(folder, label=label, source=source, registry_dir=registry_dir, work_dir=work_dir)
    match = adoption.match_fingerprint()
    if match is not None:
        return match

    # content changed (pages added/removed in the SAME pile): update its
    # record rather than silently duplicate it. Confirmed transcriptions
    # are NEVER auto-cleared: the change is flagged for a manual review.
    best = adoption.find_same_pile()
    if best is not None:
        return adoption.apply_content_changed(best)

    return adoption.register_new()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="adopt", description="Register a user scan folder in the loft registry, in place"
    )
    parser.add_argument("folder", type=Path, help="the user's scan folder (never modified)")
    parser.add_argument("--label", default="", help="the envelope/pile label, if known")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="where the scans came from")
    args = parser.parse_args(argv)

    try:
        result = register_adopted(args.folder, label=args.label, source=args.source)
    except AdoptionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    record = BatchRecord.from_dict(json.loads(result.path.read_text(encoding="utf-8")))
    print(f"{result.outcome}: {len(record.pages)} page(s) from {args.folder}")
    print(f"registry: {result.path}" + (f" (label: {args.label})" if args.label else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
