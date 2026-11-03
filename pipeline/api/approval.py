"""Per-page transcript approval: one page agreed, the document assembled.

The reviewer approves a page's text on its own — a checked page must not wait
for its neighbour. Each approval is recorded beside the page
(``ocr-guess/<page>.agreed.json``: the approved text, its sha, who and when),
and the page's DOCUMENT is (re)assembled from the approved pages only: the
archive item is minted as a ``draft`` holding what has been approved, and is
promoted to ``catalogued`` when every text page of the document is approved.
A document's item id is minted once and superseded on each later approval, so
the archive keeps its supersede history and never gets a second item.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from document.document import DOCUMENT_AGREED
from pipeline.artefacts import BatchArtefacts
from pipeline.batch_record import BatchRecord
from pipeline.boundary import Boundary
from pipeline.classify import category_of
from pipeline.registry import load_batch, record_path
from pipeline.stage_table import TEXT_KINDS, classification_of
from pipeline.store import PipelineStore
from tools.archive import Archive
from tools.loft_paths import REGISTRY_DIR, WORK_DIR
from tools.store import DiskStore  # noqa: F401 — the architecture test's store-layer marker


@dataclass(frozen=True)
class ApprovalContext:
    """Where an approval is written: the archive and the batch's own trees."""

    archive: Archive
    work_dir: Path = WORK_DIR
    registry_dir: Path = REGISTRY_DIR


@dataclass(frozen=True)
class DocumentFacts:
    """The facts a document's item is minted with (the review's answers)."""

    title: str = ""
    date: str = ""
    date_precision: str = ""
    by: str = ""
    at: str | None = None


@dataclass(frozen=True)
class Approval:
    """What approving one page did: its agreement and the document's state."""

    page: str
    item_id: str
    document_complete: bool
    pages_approved: int
    pages_total: int


@dataclass(frozen=True)
class PageAgreement:
    """The approved text of one page — the marker's content."""

    page: str
    text_sha: str
    text: str
    at: str
    by: str


def approve_page(
    batch_id: str,
    page: str,
    text: str,
    *,
    context: ApprovalContext,
    facts: DocumentFacts | None = None,
) -> Approval:
    """Record one page's approval and reassemble its document's item.

    The item's status follows the document: ``draft`` while a text page is
    unapproved, ``catalogued`` once every text page is. The item id is the
    one the document already became, or a fresh one on its first approval."""
    facts = facts or DocumentFacts()
    record = load_batch(batch_id, context.registry_dir)
    document = _document_of(record, page)
    if document is None:
        raise ValueError(f"page {page!r} is not in batch {batch_id!r}")
    artefacts = BatchArtefacts(context.work_dir, batch_id)
    marker = artefacts.agreed(page)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            PageAgreement(
                page=page,
                text_sha=_sha(text),
                text=text,
                at=facts.at or datetime.now(UTC).isoformat(timespec="seconds"),
                by=facts.by,
            ).__dict__,
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    pages = _DocumentPages(record, artefacts, document)
    complete = pages.complete()
    item = context.archive.agree_document(
        title=facts.title,
        date=facts.date,
        date_precision=facts.date_precision,
        text=pages.approved_text(),
        item_id=document.item_id,
        status="catalogued" if complete else "draft",
    )
    document.item_id = item.id
    if complete:
        document.reviewed(DOCUMENT_AGREED)
    boundaries = [b for b in record.boundaries or [] if b.pages != document.pages]
    boundaries.append(document)
    record.boundaries = boundaries
    PipelineStore(context.registry_dir).write(
        record_path(batch_id, context.registry_dir).name,
        json.dumps(record.to_dict(), indent=1, ensure_ascii=False) + "\n",
    )
    return Approval(
        page=page,
        item_id=item.id,
        document_complete=complete,
        pages_approved=len(pages.approved()),
        pages_total=len(pages.text_pages()),
    )


def agreement_for(page: str, batch_id: str, work_dir: Path) -> PageAgreement | None:
    """The page's agreement, or None when it has not been approved."""
    path = BatchArtefacts(work_dir, batch_id).agreed(page)
    if not path.is_file():
        return None
    raw: Mapping[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return PageAgreement(
        page=str(raw["page"]),
        text_sha=str(raw["text_sha"]),
        text=str(raw["text"]),
        at=str(raw["at"]),
        by=str(raw["by"]),
    )


class _DocumentPages:
    """One document's pages as the approval sees them: which carry writing,
    which are approved, and the text the approved ones make."""

    def __init__(self, record: BatchRecord, artefacts: BatchArtefacts, document: Boundary) -> None:
        self.artefacts = artefacts
        self.document = document
        self.classify = classification_of(artefacts)
        self.record = record

    def text_pages(self) -> list[str]:
        if not self.classify:
            return list(self.document.pages)
        text = [
            name
            for name in self.document.pages
            if name in self.classify and category_of(self.classify[name]) in TEXT_KINDS
        ]
        return text or list(self.document.pages)

    def approved(self) -> list[str]:
        return [name for name in self.text_pages() if self.artefacts.agreed(name).is_file()]

    def complete(self) -> bool:
        return len(self.approved()) == len(self.text_pages())

    def approved_text(self) -> str:
        parts: list[str] = []
        for name in self.approved():
            raw = json.loads(self.artefacts.agreed(name).read_text(encoding="utf-8"))
            parts.append(str(raw["text"]).strip())
        return "\n\n".join(part for part in parts if part)


def _document_of(record: BatchRecord, page: str) -> Boundary | None:
    """The document a page belongs to (a page outside every boundary is its
    own document: a page is never un-approvable)."""
    for boundary in record.boundaries or []:
        if page in boundary.pages:
            return boundary
    return Boundary(pages=[page])


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
