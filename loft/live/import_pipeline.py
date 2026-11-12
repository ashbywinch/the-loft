"""A6 — import the pipeline state from the registry and the work tree.

The registry's base records become `batches`/`scans`/`pages`; the work tree's
latest reading (rows or the strip-era layout) becomes `readings` and
`page_rows`, the drawn lines `row_adjustments`, and the registry's boundaries
`documents`/`document_pages`. The work files are read once and are not carried;
the reading blob is content-addressed, so a rebuild replays the event, not the
tree. A re-run skips a batch the store holds; a dry run writes nothing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loft.live.backup import check_marker
from loft.live.batch_row import BatchState, ScanState, page_id_of, scan_state
from loft.live.document_row import DocumentPage, DocumentState
from loft.live.errors import LiveError
from loft.live.identity_map import date_value
from loft.live.page_row import PageRow, PageState, reading_blob, reading_rows
from loft.live.store import LiveStore
from pipeline.api.sync import BatchReadings
from pipeline.batch_record import BatchRecord
from pipeline.registry import list_batches
from pipeline.store import PipelineStore


class PipelineImportError(LiveError):
    """A batch's work files could not be read."""


@dataclass(frozen=True)
class PagePlan:
    """One page's registry image, reading and correction, ready to import."""

    page: PageState
    scan: ScanState
    reading: dict[str, Any] | None
    adjustment: bytes | None
    adjustment_at: str


@dataclass(frozen=True)
class DocumentPlan:
    """One registry boundary, ready to import."""

    document: DocumentState
    pages: tuple[str, ...]
    text: str | None


@dataclass(frozen=True)
class BatchPlan:
    """One batch's whole pipeline state."""

    batch: BatchState
    scans: tuple[ScanState, ...]
    pages: tuple[PagePlan, ...]
    documents: tuple[DocumentPlan, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "scans": len(self.scans),
            "pages": len(self.pages),
            "readings": sum(1 for page in self.pages if page.reading is not None),
            "rows": sum(len((page.reading or {}).get("lines") or []) for page in self.pages),
            "adjustments": sum(1 for page in self.pages if page.adjustment is not None),
            "documents": len(self.documents),
            "document_pages": sum(len(document.pages) for document in self.documents),
        }


@dataclass(frozen=True)
class PipelineReport:
    """What the import did (or would do) — counts, skips, operations, result."""

    counts: dict[str, int] = field(default_factory=dict)
    per_batch: dict[str, dict[str, int]] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    operations: tuple[str, ...] = ()
    dry_run: bool = False
    mismatches: tuple[str, ...] = ()


class PipelineImport:
    """The pipeline import's vocabulary."""

    COUNT_KEYS: tuple[str, ...] = (
        "batches",
        "scans",
        "pages",
        "readings",
        "rows",
        "adjustments",
        "documents",
        "document_pages",
    )
    ROW_READING = "rows"
    LAYOUT_READING = "layout"


def _batch_state(record: BatchRecord) -> BatchState:
    return BatchState(
        batch_id=record.batch_id,
        label=record.label,
        source=record.source,
        path=str(record.path),
        status=record.status,
        arrived_at=record.arrived_at,
        started_at=record.started_at,
        started_pid=record.started_pid,
        started_host=record.started_host,
        fingerprint=list(record.fingerprint),
        content_changed=record.content_changed,
    )


def _latest_json(store: PipelineStore, relative: str) -> Any | None:
    if not store.exists(relative):
        return None
    try:
        return json.loads(store.read_available(relative))
    except (ValueError, OSError) as error:
        raise PipelineImportError(f"{relative} is unreadable: {error}") from error


def _revision(reading: dict[str, Any] | None) -> int:
    return int((reading or {}).get("revision", 1))


class WorkPage:
    """One page's work-tree files: its reading, words, orientation, correction."""

    def __init__(self, work_dir: Path, batch_id: str, page: str) -> None:
        self.work_dir = work_dir
        self.batch_id = batch_id
        self.page = page
        self.store = PipelineStore(work_dir)

    def reading(self) -> dict[str, Any] | None:
        stem = Path(self.page).stem
        for kind in (PipelineImport.ROW_READING, PipelineImport.LAYOUT_READING):
            raw = _latest_json(self.store, f"{self.batch_id}/ocr-guess/{stem}.{kind}.json")
            if raw is not None:
                return raw
        return None

    def words(self) -> list[dict[str, Any]]:
        raw = _latest_json(self.store, f"{self.batch_id}/ocr-guess/{Path(self.page).stem}.words.json")
        return list(raw.get("words") or []) if raw else []

    def rotation(self, reading: dict[str, Any] | None) -> int:
        path = self.work_dir / self.batch_id / "oriented" / "rotations.json"
        if not path.is_file():
            return int((reading or {}).get("rotation") or 0)
        try:
            entry = json.loads(path.read_text(encoding="utf-8")).get(self.page) or {}
        except (ValueError, OSError) as error:
            raise PipelineImportError(f"{path} is unreadable: {error}") from error
        return int(entry.get("degrees") or (reading or {}).get("rotation") or 0)

    def adjustment(self) -> tuple[bytes | None, str]:
        path = self.work_dir / self.batch_id / "ocr-guess" / f"{Path(self.page).stem}.row-adjustments.json"
        if not path.is_file():
            return None, ""
        return path.read_bytes(), datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()

    def plan(
        self,
        batch: BatchState,
        sha: str,
        ordinal: int,
        classify: dict[str, Any],
        readings: BatchReadings,
    ) -> PagePlan:
        raw = self.reading()
        words = self.words()
        rotation = self.rotation(raw)
        revision = _revision(raw)
        page_id = page_id_of(self.batch_id, self.page)
        blob = reading_blob(page_id, raw, words, rotation=rotation, revision=revision) if raw is not None else None
        adjustment, adjustment_at = self.adjustment()
        return PagePlan(
            page=PageState(
                page_id=page_id,
                image_asset_id=page_id,
                sha256=sha,
                revision=revision,
                rotation=rotation,
                category=str((classify.get(self.page) or {}).get("kind", "")),
                status=readings.page_status(self.page).value,
            ),
            scan=scan_state(batch, self.page, sha, ordinal),
            reading=blob,
            adjustment=adjustment,
            adjustment_at=adjustment_at,
        )


@dataclass(frozen=True)
class DocumentEvidence:
    """The item facts a boundary's document inherits (empty when it has no item)."""

    title: str | None = None
    date_json: str | None = None
    date: str | None = None
    date2: str | None = None
    date_precision: str | None = None


def _evidence(item: Any) -> DocumentEvidence:
    if item is None:
        return DocumentEvidence()
    return DocumentEvidence(
        title=item.title,
        date_json=(
            json.dumps(
                date_value(item.date, item.date_precision, item.raw.get("date2")),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            if item.date
            else None
        ),
        date=item.date or None,
        date2=str(item.raw.get("date2") or "") or None,
        date_precision=item.date_precision or None,
    )


def _document_state(
    store: LiveStore, batch_id: str, index: int, boundary: Any
) -> tuple[DocumentState, tuple[str, ...], str | None]:
    item = store.items.get(boundary.item_id) if boundary.item_id else None
    evidence = _evidence(item)
    text = boundary.confirmation.text if boundary.confirmation else None
    document = DocumentState(
        document_id=f"{batch_id}/doc-{index + 1}",
        item_id=boundary.item_id or None,
        batch_id=batch_id,
        doc_index=index + 1,
        title=evidence.title,
        date_json=evidence.date_json,
        date=evidence.date,
        date2=evidence.date2,
        date_precision=evidence.date_precision,
        status=str(boundary.status or "review"),
        greeting=boundary.greeting,
        signoff=boundary.signoff,
        text_sha=hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None,
        confirmed_at=boundary.confirmation.confirmed_at if boundary.confirmation else None,
    )
    pages = tuple(page_id_of(batch_id, page) for page in boundary.pages)
    return document, pages, text


def _plan_documents(store: LiveStore, record: BatchRecord) -> tuple[DocumentPlan, ...]:
    documents: list[DocumentPlan] = []
    for index, boundary in enumerate(record.boundaries or []):
        document, document_pages, text = _document_state(store, record.batch_id, index, boundary)
        documents.append(DocumentPlan(document=document, pages=document_pages, text=text))
    return tuple(documents)


def _plan_batch(record: BatchRecord, store: LiveStore, work_dir: Path) -> BatchPlan:
    batch = _batch_state(record)
    work = PipelineStore(work_dir)
    classify = _latest_json(work, f"{record.batch_id}/classify.json") or {}
    readings = BatchReadings(work_dir, record.batch_id)
    pages = tuple(
        WorkPage(work_dir, record.batch_id, page).plan(batch, record.pages[page], ordinal, classify, readings)
        for ordinal, page in enumerate(sorted(record.pages))
    )
    return BatchPlan(
        batch=batch,
        scans=tuple(page.scan for page in pages),
        pages=pages,
        documents=_plan_documents(store, record),
    )


def _plan(store: LiveStore, registry_dir: Path, work_dir: Path) -> tuple[list[BatchPlan], dict[str, int]]:
    plans: list[BatchPlan] = []
    skipped = {"batches": 0}
    for record in sorted(list_batches(registry_dir), key=lambda entry: entry.batch_id):
        if store.batches.get(record.batch_id) is not None:
            skipped["batches"] += 1
            continue
        plans.append(_plan_batch(record, store, work_dir))
    return plans, skipped


def _counts(plans: list[BatchPlan]) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    counts = {key: 0 for key in PipelineImport.COUNT_KEYS}
    per_batch: dict[str, dict[str, int]] = {}
    for plan in plans:
        batch_counts = plan.counts
        per_batch[plan.batch.batch_id] = batch_counts
        counts["batches"] += 1
        for key, value in batch_counts.items():
            counts[key] += value
    return counts, per_batch


def _expected_rows(plan: PagePlan) -> tuple[PageRow, ...]:
    if plan.reading is None:
        return ()
    corrected = bool(str(plan.reading.get("corrected", "")))
    return reading_rows(plan.page.page_id, plan.reading, revision=plan.page.revision, corrected=corrected)


def _compare_batch(store: LiveStore, plan: BatchPlan) -> list[str]:
    stored = store.batches.get(plan.batch.batch_id)
    if stored is None:
        return [f"batch {plan.batch.batch_id} is missing after import"]
    findings: list[str] = []
    if replace(stored, version=0) != plan.batch:
        findings.append(f"batch {plan.batch.batch_id} differs from the registry record")
    if store.batches.scans(plan.batch.batch_id) != plan.scans:
        findings.append(f"batch {plan.batch.batch_id} scans differ")
    return findings


def _compare_page(store: LiveStore, plan: PagePlan) -> list[str]:
    stored = store.pages.get(plan.page.page_id)
    if stored is None or replace(stored, event_seq=0) != plan.page:
        return [f"page {plan.page.page_id} differs from the registry record"]
    findings: list[str] = []
    stored_reading = store.pages.reading(plan.page.page_id)
    if plan.reading is None:
        if stored_reading is not None:
            findings.append(f"page {plan.page.page_id} has an unexpected reading")
    elif stored_reading is None:
        findings.append(f"page {plan.page.page_id} reading is missing")
    else:
        if store.pages.reading_blob(plan.page.page_id) != plan.reading:
            findings.append(f"page {plan.page.page_id} reading differs")
        if stored_reading.corrected_sha != str(plan.reading.get("corrected", "")):
            findings.append(f"page {plan.page.page_id} corrected sha differs")
    if tuple(replace(row, event_seq=0) for row in store.pages.rows(plan.page.page_id)) != _expected_rows(plan):
        findings.append(f"page {plan.page.page_id} rows differ")
    stored_adjustment = store.pages.adjustment(plan.page.page_id)
    if plan.adjustment is None:
        if stored_adjustment is not None:
            findings.append(f"page {plan.page.page_id} has an unexpected adjustment")
    elif stored_adjustment is None:
        findings.append(f"page {plan.page.page_id} adjustment is missing")
    elif stored_adjustment.sha256 != hashlib.sha256(plan.adjustment).hexdigest():
        findings.append(f"page {plan.page.page_id} adjustment sha differs")
    return findings


def _compare_document(store: LiveStore, plan: DocumentPlan) -> list[str]:
    stored = store.documents.get(plan.document.document_id)
    if stored is None or replace(stored, version=0) != plan.document:
        return [f"document {plan.document.document_id} differs from the boundary"]
    expected_pages = tuple(
        DocumentPage(document_id=plan.document.document_id, page_id=page_id, ordinal=index)
        for index, page_id in enumerate(plan.pages)
    )
    if store.documents.pages(plan.document.document_id) != expected_pages:
        return [f"document {plan.document.document_id} pages differ"]
    return []


def _compare(store: LiveStore, plans: list[BatchPlan]) -> tuple[str, ...]:
    findings: list[str] = []
    for plan in plans:
        findings.extend(_compare_batch(store, plan))
        for page in plan.pages:
            findings.extend(_compare_page(store, page))
        for document in plan.documents:
            findings.extend(_compare_document(store, document))
    return tuple(findings)


def import_pipeline(
    store: LiveStore,
    workspace: Path,
    *,
    backup_marker: Path,
    dry_run: bool = False,
) -> PipelineReport:
    """Import every registry batch, its pages/readings and its boundaries."""
    check_marker(backup_marker)
    registry_dir = workspace / "registry"
    work_dir = workspace / "work"
    plans, skipped = _plan(store, registry_dir, work_dir)
    counts, per_batch = _counts(plans)
    operations_list: list[str] = []
    for plan in plans:
        operations_list.append(f"batch {plan.batch.batch_id}")
        operations_list.extend(f"page {page.page.page_id}" for page in plan.pages)
        operations_list.extend(f"document {document.document.document_id}" for document in plan.documents)
    operations = tuple(operations_list)
    if dry_run:
        return PipelineReport(
            counts=counts,
            per_batch=per_batch,
            skipped=skipped,
            operations=operations,
            dry_run=True,
        )
    if plans:
        with store.change(actor="import", note="pipeline state") as change:
            for plan in plans:
                change.batches.save(plan.batch, plan.scans)
                for page in plan.pages:
                    change.pages.save(
                        page.page,
                        reading=page.reading,
                        adjustment=page.adjustment,
                        adjustment_at=page.adjustment_at,
                    )
                for document in plan.documents:
                    change.documents.save(document.document, document.pages, text=document.text)
    return PipelineReport(
        counts=counts,
        per_batch=per_batch,
        skipped=skipped,
        operations=operations,
        dry_run=False,
        mismatches=_compare(store, plans),
    )
