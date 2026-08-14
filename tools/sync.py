"""The two-app sync contract (TECH-SPEC §16.15, MULTI-DOC-IMPORT-PRD.md R14).

The backend owns the archive's write seam; the frontend proposes, the
backend records. This module is the shared contract:
- the confirmation payload shape (validated before anything is recorded);
- the frontend's ``Outbox`` — the catch-up backlog for real-time pushes
  that failed (the laptop was off); the backend pulls it and the website
  marks items received;
- ``draft_payloads`` — the machine drafts the review surface reads.

Nothing confirmed is ever lost to a failed push.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.atomic import atomic_write
from tools.loft_paths import REGISTRY_DIR, WORK_DIR
from tools.registry import load_batch, record_path

REQUIRED_FIELDS = ("batch_id", "doc_index", "pages", "text", "status", "confirmed_at")

_BATCH_ID = re.compile(r"^[A-Za-z0-9-]+$")

# page names from boundaries.json become path segments in the drafts read —
# a charset that excludes every separator and "..", so a hostile entry can't
# read outside the batch's guess dir (defense-in-depth, review, 2026-08-14)
_PAGE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_confirmation(payload: dict[str, Any]) -> dict[str, Any]:
    """The confirmation's required shape; raises ValueError with the reason."""
    missing = [f for f in REQUIRED_FIELDS if f not in payload]
    if missing:
        raise ValueError(f"confirmation missing fields: {missing}")
    if payload["status"] not in ("confirmed", "rejected"):
        raise ValueError(f"confirmation status must be confirmed|rejected, got {payload['status']!r}")
    if not isinstance(payload["pages"], list) or not payload["pages"]:
        raise ValueError("confirmation pages must be a non-empty list")
    if not isinstance(payload["text"], str):
        raise ValueError("confirmation text must be a string")
    return payload


class Outbox:
    """The frontend's catch-up backlog: confirmed outputs awaiting the backend.

    Append-only, atomic per item — a crash loses nothing that was added.
    The backend pulls ``pending()`` and the website marks them received.
    Item ids are validated (plain id chars only) — they become file names.
    """

    _ITEM_ID = re.compile(r"^[A-Za-z0-9-]+$")

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def add(self, payload: dict[str, Any]) -> str:
        validate_confirmation(payload)
        self.directory.mkdir(parents=True, exist_ok=True)
        item_id = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}"
        atomic_write(self.directory / f"{item_id}.json", json.dumps(payload, ensure_ascii=False) + "\n")
        return item_id

    def pending(self) -> list[tuple[str, dict[str, Any]]]:
        if not self.directory.is_dir():
            return []
        items: list[tuple[str, dict[str, Any]]] = []
        for path in sorted(self.directory.glob("*.json")):
            items.append((path.stem, json.loads(path.read_text(encoding="utf-8"))))
        return items

    def mark_received(self, item_ids: list[str]) -> None:
        for item_id in item_ids:
            if not self._ITEM_ID.match(item_id):
                raise ValueError(f"invalid outbox item id: {item_id!r}")  # path traversal guard
            (self.directory / f"{item_id}.json").unlink(missing_ok=True)


def record_confirmation(
    batch_id: str,
    doc_index: int,
    document: dict[str, Any],
    text: str | None,
    *,
    work_dir: Path = WORK_DIR,
    registry_dir: Path = REGISTRY_DIR,
) -> None:
    """The backend's single write path for a reviewed document — shared by
    the CLI review gate and the sync receiver (TECH-SPEC §16.15): the
    confirmed text lands in ocr-confirmed/<doc>.txt and the registry's
    boundaries are updated (replace-by-pages, append). ``text=None``
    records a rejection — nothing is silently dropped. The batch id is
    validated FIRST: it becomes a path segment, and the write must never
    precede the guard (2026-08-14 review: write-before-validate)."""
    if not _BATCH_ID.match(batch_id):
        raise ValueError(f"invalid batch id: {batch_id!r}")
    # load (and so validate the batch was adopted) BEFORE any write — an
    # unknown batch must fabricate nothing and raise RegistryError -> 4xx,
    # not leave a stray review-output file behind (review, 2026-08-14).
    record = load_batch(batch_id, registry_dir)
    if text is not None:
        confirmed_dir = work_dir / batch_id / "ocr-confirmed"
        confirmed_dir.mkdir(parents=True, exist_ok=True)
        atomic_write(confirmed_dir / f"doc-{doc_index:02d}.txt", text)
        entry: dict[str, Any] = {**document, "status": "confirmed"}
    else:
        entry = {**document, "status": "rejected"}
    boundaries = [b for b in record.get("boundaries") or [] if b.get("pages") != document.get("pages")]
    boundaries.append(entry)
    record["boundaries"] = boundaries
    atomic_write(record_path(batch_id, registry_dir), json.dumps(record, indent=1, ensure_ascii=False) + "\n")


def draft_payloads(batch_id: str, work_dir: Path) -> list[dict[str, Any]]:
    """The machine drafts the review surface reads: per-page guessed texts
    + the document boundaries, for one batch. The batch id is validated
    (it becomes a path segment — traversal guard, 2026-08-14 review)."""
    if not _BATCH_ID.match(batch_id):
        raise ValueError(f"invalid batch id: {batch_id!r}")
    guess_dir = work_dir / batch_id / "ocr-guess"
    boundaries_path = guess_dir / "boundaries.json"
    if not boundaries_path.exists():
        return []
    boundaries = json.loads(boundaries_path.read_text(encoding="utf-8"))
    drafts: list[dict[str, Any]] = []
    for document in boundaries:
        pages = document.get("pages", [])
        for page in pages:
            if not _PAGE_NAME.match(page) or ".." in page:
                raise ValueError(f"unsafe page name in boundaries: {page!r}")
        texts = {
            page: (guess_dir / Path(page).with_suffix(".txt")).read_text(encoding="utf-8")
            for page in pages
            if (guess_dir / Path(page).with_suffix(".txt")).exists()
        }
        drafts.append({"batch_id": batch_id, "pages": pages, "texts": texts, **document})
    return drafts
