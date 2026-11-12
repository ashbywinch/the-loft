"""The ingest chain driver: classify → orient → read → review.
The user's confirmation, per registered batch (TECHSPEC §16.13/§16.14).

`process` runs the machine stages and leaves the batch awaiting review. The
page's CATEGORY decides its read (docs/PLAN/page-categories.md): a photograph
or a drawing is not read; printed writing takes one direct VLM transcription;
a form is read as structure; handwriting (and a handwritten postcard face)
takes the row pipeline — orient, rows, the human row check, then the
transcription review. A pile's pages form one document; `review` is the user's
confirmation gate: each document's text is accepted, edited, or rejected, and
an accepted document becomes an archive item: its transcription is the item's own content file

Usage:
    python tools/pipeline.py process <batch-id>
    python tools/pipeline.py review  <batch-id>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from document.document import Document
from document.page_size import PageSize
from document.row import Row
from document.row_adjustments import RowAdjustments
from document.words import Words
from pipeline.api.sync import BatchReadings, record_confirmation
from pipeline.artefacts import BatchArtefacts
from pipeline.batch_record import BatchRecord
from pipeline.boundary import Boundary
from pipeline.classify import PageKinds, run_classify
from pipeline.detect.reader import Reading, reading_for_page
from pipeline.grouping import score_boundaries
from pipeline.model.ai_client import AIClient, AIClientError
from pipeline.model.config import ModelConfig
from pipeline.orient import PageOrientation
from pipeline.page_flag import PageFlag
from pipeline.page_text import PageText
from pipeline.registry import RegistryError as PipelineError
from pipeline.registry import load_batch, record_path
from pipeline.rows.rows import Rows
from pipeline.rows_reading import RowsReading
from pipeline.stage_table import EngineView, StageInputs, run_plan
from pipeline.standing_knowledge import StandingKnowledge
from pipeline.store import PipelineStore
from pipeline.transcribe.printed import printed_transcript, structured_transcript
from pipeline.transcribe.transcripts import Transcriber, row_transcripts
from tools.archive import Archive
from tools.atomic import atomic_write
from tools.loft_paths import LoftPaths
from tools.store import DiskStore, StoreError  # noqa: F401 — the architecture test's store-layer marker


def _standing_names(records: list[dict[str, Any]], with_aliases: bool = False) -> list[str]:
    """The names the standing-knowledge records carry — people's aliases too."""
    out: list[str] = []
    for record in records:
        name = str(record.get("name", "")).strip()
        if name:
            out.append(name)
        if with_aliases:
            out += [str(alias) for alias in record.get("aliases", []) if str(alias).strip()]
    return out


def _boundary_prompt(page_texts: list[PageText], label: str, people: list[str], places: list[str]) -> tuple[str, str]:
    """The system + user prompt for the document-boundary judgement.

    The reads own the text — this call does not transcribe; it decides where a
    document STARTS (a greeting, an address block, a date opening a letter) and
    ENDS (a sign-off, a signature). The grouping scorer then weighs that against
    the physical evidence (duplex sides, paper size, page numbers)."""
    system = (
        "You group scanned family pages into documents. Each page's text has been read "
        "already; do not correct or rewrite it.\n"
        '- A page STARTS a document when it opens a letter (a greeting such as "Dear X", '
        "an address block, a date beginning a new letter); a page ENDS one at a sign-off "
        '("Yours, X", a signature, the close of a letter).\n'
        "- A page that continues a letter starts and ends nothing.\n"
        f"Context — known family people: {', '.join(people) or 'none'}. "
        f"Known places: {', '.join(places) or 'none'}. Batch: {label or 'unlabelled'}.\n"
        'Output JSON only: {"pages": [{"page": "<filename>", "text": "", '
        '"starts_document": true/false, "ends_document": true/false, '
        '"greeting": "<text or null>", "signoff": "<text or null>"}]}'
    )
    blocks = "\n\n".join(f"Page {one.page}:\n{one.text}" for one in page_texts)
    user = f"Here is the vision model's reading of each page.\n\n{blocks}"
    return system, user


def page_flags(
    page_texts: list[PageText],
    label: str,
    people: list[str],
    places: list[str],
    client: Callable[[str, str], str],
) -> list[PageFlag]:
    """One model call: the document-boundary flags per page.

    ``client`` is the chat seam (AIClient.chat shape); injectable for tests."""
    if len(page_texts) > Batch.PAGE_LIMIT:
        raise PipelineError(
            f"batch has {len(page_texts)} pages — the boundary call handles up to {Batch.PAGE_LIMIT} per call; "
            "chunking is future work"
        )
    system, user = _boundary_prompt(page_texts, label, people, places)
    try:
        raw = client(system, user)
    except AIClientError as exc:
        raise PipelineError(f"the boundary call failed: {exc}") from exc
    try:
        payload = json.loads(raw)
        pages = payload["pages"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PipelineError(f"model returned unparseable JSON: {raw[:200]!r}") from exc
    out: list[PageFlag] = []
    for entry in pages:
        try:
            out.append(PageFlag.from_dict(entry))
        except ValueError as exc:
            raise PipelineError(f"model returned a malformed page entry: {entry!r}") from exc
    return out


@dataclass(frozen=True)
class Classification:
    """The per-page photo/text classification of a batch, with the page
    lists it implies: photos/drawings skip orientation + OCR entirely."""

    classify: dict[str, Any]
    text_pages: list[str]
    image_pages: list[str]


class Batch:
    """One registered batch's shared context: its id, its machine-stage
    paths, the standing knowledge, and its registry status writes — the
    state the run stages (BatchRun) and the confirmation gate (ReviewGate)
    both work from."""

    PAGE_LIMIT = 30  # one boundary call per batch; beyond this the context is too big

    def __init__(
        self,
        batch_id: str,
        *,
        work_dir: Path = LoftPaths.WORK_DIR,
        registry_dir: Path = LoftPaths.REGISTRY_DIR,
        archive_dir: Path = LoftPaths.ARCHIVE_DIR,
    ) -> None:
        self.batch_id = batch_id
        self.work_dir = work_dir
        self.registry_dir = registry_dir
        self.archive_dir = archive_dir
        self.artefacts = BatchArtefacts(work_dir, batch_id)

    def update_status(self, record: BatchRecord, status: str) -> None:
        """Stamp the registry record's status and persist it. A processing pass
        stamps when it started, its pid and its host — the worker's sweep uses
        that to tell a live pass from one that was killed."""
        record.status = status
        if status == BatchRecord.STATUS_PROCESSING:
            record.started_at = datetime.now(UTC).isoformat(timespec="seconds")
            record.started_pid = os.getpid()
            record.started_host = socket.gethostname()
        store = PipelineStore(self.registry_dir)
        store.write(f"{self.batch_id}.json", json.dumps(record.to_dict(), indent=1, ensure_ascii=False) + "\n")

    def standing_knowledge(self) -> StandingKnowledge:
        """The archive's people and places names — the context a read
        works from (the batch's archive_dir is its own state here)."""
        store = PipelineStore(self.archive_dir)
        people = (
            _standing_names(json.loads(store.read_latest("people.json")).get("people", []), with_aliases=True)
            if store.exists("people.json")
            else []
        )
        places = (
            _standing_names(json.loads(store.read_latest("places.json")).get("places", []))
            if store.exists("places.json")
            else []
        )
        return StandingKnowledge(sorted(set(people)), sorted(set(places)))


class BatchRun(Batch):
    """The machine stages of one batch's ingest — classify → orient (text
    pages) → read — the reader is the vision model, and the page text is its rows'
    read and its per-page row check. The record, stage paths and DI seams the
    module functions threaded are this object's state; process is the thin
    entry point."""

    BOUNDARY_MODEL = ModelConfig.BOUNDARY_MODEL  # judges document boundaries (<provider>/<model>)
    GUESS_PAGE_CHUNK = 5  # pages per boundary call (the answer echoes each page's flags)

    def clear_stale_stages(self, record: BatchRecord) -> None:
        """A content-changed pile (pages added/removed after adoption): the
        regenerable stages are stale — clear them (never the agreed items) and
        consume the flag so this run reprocesses the full current page set."""
        stale_stages = (
            self.artefacts.classify,
            self.artefacts.oriented_dir,
            self.artefacts.raw_dir,
            self.artefacts.guess_dir,
        )
        for stale in stale_stages:
            if stale.is_file():
                stale.unlink(missing_ok=True)
            elif stale.is_dir():
                shutil.rmtree(stale)
        record.content_changed = False
        self.update_status(record, BatchRecord.STATUS_PROCESSING)
        print("content changed since adoption — regenerable stages cleared; confirmed transcriptions preserved")

    def classify_pages(self, pages: list[Path], *, reclassify: Sequence[str] = ()) -> Classification:
        """The per-page category classification — run when absent, and for the
        named pages whose record is stale (a pre-category spelling); a pile's
        photos/drawings skip orientation and the read entirely."""
        store = PipelineStore(self.work_dir)
        rel_classify = f"{self.batch_id}/classify.json"
        if store.exists(rel_classify) and not reclassify:
            print("classification already present — reusing")
        else:
            run_classify(self.batch_id, registry_dir=self.registry_dir, work_dir=self.work_dir, reclassify=reclassify)
            print(f"classified {len(pages)} page(s) -> {self.artefacts.classify}")
        classify = json.loads(store.read_latest(rel_classify))
        text_pages = [name for name, entry in classify.items() if PageKinds.category_of(entry) in PageKinds.TEXT_KINDS]
        image_pages = [
            name for name, entry in classify.items() if PageKinds.category_of(entry) not in PageKinds.TEXT_KINDS
        ]
        if image_pages:
            print(f"{len(image_pages)} page(s) carry no writing — no transcription")
        return Classification(classify, text_pages, image_pages)

    def rows_pages(self, classification: Classification) -> list[str]:
        """The pages that take the row pipeline: the category routes them to
        rows, and they have not been read directly already (a printed or
        structured marker is the page's stage-5 completion — re-reading it
        through the row chain would undo it)."""
        return [
            name
            for name in classification.text_pages
            if PageKinds.read_route(classification.classify[name]) == "rows"
            and not (self.artefacts.guess_dir / f"{Path(name).stem}.printed.json").is_file()
            and not (self.artefacts.guess_dir / f"{Path(name).stem}.structured.json").is_file()
        ]

    def orient_pages(self, text_pages: list[str], folder: Path) -> None:
        """Turn the text pages' writing upright into ``oriented/`` — the vision
        model names each page's rotation (pipeline/orient.py). Nothing else is
        measured here: the reader is the VLM's."""
        if all((self.artefacts.oriented_dir / name).is_file() for name in text_pages):
            print("orientation already present — reusing")
            return
        written = PageOrientation.pages([folder / name for name in text_pages], self.artefacts.oriented_dir)
        print(f"oriented: {len(written)} page(s) -> {self.artefacts.oriented_dir}")

    def read_all(
        self,
        classification: Classification,
        _printed: Callable[[Path], tuple[str, Any]] | None = None,
    ) -> list[str]:
        """Read every page the category says has writing: printed pages take
        the direct read, forms the structured read, and the rest the row
        pipeline (auto rows, then the human check). A page already read
        directly is never re-read through the row chain."""
        direct = [n for n in classification.text_pages if PageKinds.read_route(classification.classify[n]) == "direct"]
        structured = [
            n for n in classification.text_pages if PageKinds.read_route(classification.classify[n]) == "structured"
        ]
        if direct:
            self.printed_pages(
                pages=direct,
                _transcribe=_printed or printed_transcript,
                provisional_boundary=False,
            )
        if structured:
            self.structured_pages(pages=structured, provisional_boundary=False)
        kept = self.rows_pages(classification)
        if kept:
            self.read_pages(kept)
        return kept

    def write_boundaries(
        self,
        classification: Classification,
        record: BatchRecord,
        client: Callable[[str, str], str] | None = None,
    ) -> None:
        """Group the FULL page sequence (photos included) into documents: the
        model's boundary judgement over each page's reading, then the grouping
        scorer's evidence hierarchy — duplex sides, paper size, page numbers,
        the model's flags. The text is the reads' own: this stage decides
        boundaries, never text."""
        store = PipelineStore(self.work_dir)
        reg_store = PipelineStore(self.registry_dir)
        texts: dict[str, str | None] = {}
        for name in sorted(record.pages):
            if name not in classification.text_pages:
                texts[name] = None
                continue
            rel = self.artefacts.relative(self.artefacts.text(name))
            # a marker without its text is a damaged read, not a reason to
            # crash the pass: the grouping works from what is there
            texts[name] = store.read_latest(rel) if store.exists(rel) else ""

        knowledge = self.standing_knowledge()
        chat = (
            client
            if client is not None
            else AIClient(model=BatchRun.BOUNDARY_MODEL, max_tokens=12000, timeout=900.0).chat
        )
        page_texts = [PageText(name, texts[name] or "") for name in classification.text_pages]
        flags: list[PageFlag] = []
        # each iteration calls page_flags — a model inference with side effects — and extends
        # with its result; a comprehension would bury the side-effecting call inside an expression
        # lucidlint: ignore loop-pipeline side-effecting model call per iteration, not a pure build
        for start in range(0, len(page_texts), BatchRun.GUESS_PAGE_CHUNK):
            flags.extend(
                page_flags(
                    page_texts[start : start + BatchRun.GUESS_PAGE_CHUNK],
                    record.label,
                    knowledge.people,
                    knowledge.places,
                    chat,
                )
            )
        known_flags = [flag for flag in flags if flag.page in classification.text_pages]
        for flag in flags:
            if flag.page not in classification.text_pages:
                print(f"the boundary call returned an unknown page {flag.page!r} — dropped")
        folder = record.path
        dims: dict[str, PageSize] = {}
        for rel in sorted(record.pages):
            with Image.open(folder / rel) as im:
                dims[rel] = PageSize(im.width, im.height)
        boundaries = score_boundaries(
            sorted(record.pages),
            {page: PageKinds.category_of(entry) for page, entry in classification.classify.items()},
            dims,
            texts,
            {flag.page: flag for flag in known_flags},
        )
        self.artefacts.guess_dir.mkdir(parents=True, exist_ok=True)
        store.write(
            self.artefacts.relative(self.artefacts.boundaries),
            json.dumps([boundary.to_dict() for boundary in boundaries], indent=1, ensure_ascii=False) + "\n",
        )
        record.boundaries = boundaries
        reg_store.write(f"{self.batch_id}.json", json.dumps(record.to_dict(), indent=1, ensure_ascii=False) + "\n")
        print(f"boundaries: {len(boundaries)} document(s) from {len(record.pages)} page(s)")

    def printed_pages(
        self,
        pages: list[str] | None = None,
        _transcribe: Callable[[Path], tuple[str, Any]] = printed_transcript,
        *,
        provisional_boundary: bool = True,
    ) -> None:
        """Read PRINTED pages: one vision call per page, no rows, no marks.

        A printed page is already lines; the row pipeline's ink measurement is
        for handwriting and its bars would only invent geometry. Each page's
        text lands as ``ocr-guess/<page>.txt`` beside a ``<page>.printed.json``
        marker; the marker makes a re-run idempotent."""
        self._direct_read(pages, "printed", _transcribe, provisional_boundary=provisional_boundary)

    def structured_pages(
        self,
        pages: list[str] | None = None,
        _transcribe: Callable[[Path], tuple[str, Any]] = structured_transcript,
        *,
        provisional_boundary: bool = True,
    ) -> None:
        """Read FORM pages: one structured vision call per page (labels and
        their values, as a markdown table) — a form's meaning is the pairing,
        so a prose read would lose it. Marker: ``<page>.structured.json``."""
        self._direct_read(pages, "structured", _transcribe, provisional_boundary=provisional_boundary)

    def _direct_read(
        self,
        pages: list[str] | None,
        read: str,
        transcribe: Callable[[Path], tuple[str, Any]],
        *,
        provisional_boundary: bool,
    ) -> None:
        """The direct-read stages' one loop: a page read in a single vision call
        (printed prose, or a form's structure), its text and marker written, and
        one document boundary over the pages read. Idempotent per page — a page
        whose marker exists is never paid for twice."""
        record = load_batch(self.batch_id, self.registry_dir)
        work_pages = pages or list(record.pages or {})
        if not work_pages:
            raise PipelineError(f"no pages to read in batch {self.batch_id}")
        self.update_status(record, BatchRecord.STATUS_PROCESSING)
        store = PipelineStore(self.work_dir)
        read_pages: list[str] = []
        for page in work_pages:
            marker = self.artefacts.marker(page, read)
            if self.artefacts.is_read(page, "direct"):
                print(f"{read}: {page} already read — skipped")
                continue
            image = self.artefacts.oriented_dir / page
            if not image.is_file():
                image = Path(record.path) / page
            if not image.is_file():
                print(f"{read}: {page} has no image — skipped", file=sys.stderr)
                continue
            text, answer = transcribe(image)
            store.write(self.artefacts.relative(self.artefacts.text(page)), text + "\n")
            store.write(
                self.artefacts.relative(marker),
                json.dumps({"page": page, "chars": len(text), **answer.to_dict()}, ensure_ascii=False) + "\n",
            )
            read_pages.append(page)
            print(f"{read}: {page} -> {len(text)} chars")
        if read_pages and provisional_boundary:
            # a standalone printed read still needs a document to review; the
            # full pass leaves grouping to the group stage, and the flag says
            # this boundary is a placeholder, not a grouping
            boundary = Boundary(pages=read_pages)
            store.write(
                self.artefacts.relative(self.artefacts.boundaries),
                json.dumps([{**boundary.to_dict(), "provisional": True}], indent=1, ensure_ascii=False) + "\n",
            )
            record = load_batch(self.batch_id, self.registry_dir)
            record.boundaries = [boundary]
            PipelineStore(self.registry_dir).write(
                f"{self.batch_id}.json", json.dumps(record.to_dict(), indent=1, ensure_ascii=False) + "\n"
            )
        self.update_status(load_batch(self.batch_id, self.registry_dir), BatchRecord.STATUS_REVIEW)
        print(f"{read}: {len(read_pages)} page(s) read — batch {self.batch_id} awaiting review")

    def read_pages(
        self,
        text_pages: list[str],
        _reading: Callable[[Image.Image], Reading] = reading_for_page,
        _rows_text: Callable[[Path, Path], dict[int, str]] = row_transcripts,
        _corrected_text: Callable[[Path, list[Row], Path], dict[int, str]] | None = None,
    ) -> None:
        """The reading stage: each text page's rows (line boxes from the
        fitted-lines chain), each row's writing READ from the model, and the
        reading's WORDS beside them (``<page>.words.json``).

        The row's text is its own reading — the row is numbered and the model
        answers for that number — not the page guess's text indexed onto the rows
        in order, which put a sentence one row out wherever the page's rows and its
        text lines ran differently.

        **A page the reviewer corrected is re-read.** The drawn lines persist in
        ``<page>.row-adjustments.json``; when the reading does not carry their
        sha, the page's rows are rebuilt from them, read row by row again, and
        written as the reading's lines — so the transcript gate shows the text
        the corrected rows produce, not the draft the geometry proposed. A page
        whose reading is current is skipped; an empty correction ("rows are
        right") is not a re-read. A page the reading returns NOTHING for is left
        unwritten (its marker absent) and named on stderr: the marker rule — an
        artifact that looks done but is empty is worse than a page to re-run."""
        store = PipelineStore(self.work_dir)
        corrected_text = _corrected_text or _transcribe_rows
        for page in text_pages:
            stem = Path(page).stem
            rows_path = self.artefacts.guess_dir / f"{stem}.rows.json"
            existing = (
                RowsReading.from_dict(json.loads(rows_path.read_text(encoding="utf-8"))) if rows_path.exists() else None
            )
            image_path = self.artefacts.oriented_dir / page
            if not image_path.is_file():
                continue
            correction = self._pending_correction(page, existing)
            if correction is not None:
                self._read_corrected(page, image_path, existing, correction, corrected_text)
                continue
            if existing is not None:
                continue
            reading = _reading(Image.open(image_path))
            rows = Rows.from_words(list(reading.words), PageSize(reading.width, reading.height)).rows()
            transcripts = _rows_text(image_path, self.artefacts.guess_dir) if rows else {}
            if rows and not transcripts:
                print(f"read: {page} SKIPPED — the reading returned nothing (re-run to retry)")
                continue
            # each reader line carries the reading of the row that owns its words
            for row in rows:
                index = _reader_line(row)
                if index is not None and 0 <= index < len(reading.lines):
                    reading.lines[index]["text"] = transcripts.get(row.number, "")
            store.write(
                self.artefacts.relative(self.artefacts.marker(page, "rows")),
                json.dumps(
                    RowsReading(
                        page=page,
                        width=reading.width,
                        height=reading.height,
                        lines=reading.lines,
                    ).to_dict(),
                    indent=1,
                    ensure_ascii=False,
                )
                + "\n",
            )
            store.write(
                self.artefacts.relative(self.artefacts.marker(page, "words")),
                json.dumps(Words(reading.words).to_dict(), indent=1, ensure_ascii=False) + "\n",
            )
            # the page's TEXT is its rows' reading, in order — the review
            # surface's drafts read this file (the guess stage, which used to
            # write it, is gone)
            store.write(self.artefacts.relative(self.artefacts.text(page)), _page_text(reading.lines) + "\n")
            print(f"read: {page} -> {len(reading.lines)} rows, {len(reading.words)} words, {len(transcripts)} read")

    def _pending_correction(self, page: str, reading: RowsReading | None) -> RowAdjustments | None:
        """The drawn lines the page's current reading does not carry yet.

        None when there is no correction, when the correction is empty ("rows
        are right" — nothing to re-read), or when the reading already carries
        the same lines' sha. A corrupt correction file fails loudly: a page
        silently read against lines nobody can parse is worse than a rerun."""
        adjustments_path = BatchReadings(self.work_dir, self.batch_id).adjustments_path(page)
        if not adjustments_path.is_file():
            return None
        try:
            adjustments = RowAdjustments.from_dict(json.loads(adjustments_path.read_text(encoding="utf-8")))
        except ValueError as exc:
            raise PipelineError(f"{page}: unreadable row-adjustments: {exc}") from exc
        if not adjustments.lines:
            return None
        if reading is not None and reading.corrected == _file_sha(adjustments_path):
            return None
        return adjustments

    def _read_corrected(
        self,
        page: str,
        image_path: Path,
        existing: RowsReading | None,
        adjustments: RowAdjustments,
        corrected_text: Callable[[Path, list[Row], Path], dict[int, str]],
    ) -> None:
        """Read the reviewer's corrected rows and make them the page's reading.

        The rows come from the persisted words + the drawn lines (the same
        builder the app's live merge runs), each row is read as itself, and the
        reading's lines ARE the corrected rows — so the transcript gate shows
        their text and boxes. The correction's artefact carries the same text
        and the drawn-lines sha, and the reading carries that sha too, so the
        next pass does not read the page again."""
        readings = BatchReadings(self.work_dir, self.batch_id)
        words_path = readings.words_path(page)
        if not words_path.is_file():
            raise PipelineError(f"{page}: no words to re-read against — the read stage must write them first")
        words = Words.from_dict(json.loads(words_path.read_text(encoding="utf-8")))
        image = Image.open(image_path)
        width, height = (existing.width, existing.height) if existing else (image.width, image.height)
        rotation = existing.rotation if existing else 0
        revision = (existing.revision if existing else 0) + 1
        builder = Rows.from_words(list(words), PageSize(width, height))
        rows = builder.adjust(adjustments)
        texts = corrected_text(image_path, rows, self.artefacts.guess_dir)
        filled = [replace(row, text=texts.get(row.number, ""), stage="raw") for row in rows]
        reading = RowsReading(
            page=page,
            width=width,
            height=height,
            rotation=rotation,
            revision=revision,
            corrected=_file_sha(readings.adjustments_path(page)),
            lines=[_row_line(index, row) for index, row in enumerate(filled)],
        )
        store = PipelineStore(self.work_dir)
        store.write(
            self.artefacts.relative(self.artefacts.marker(page, "rows")),
            json.dumps(reading.to_dict(), indent=1, ensure_ascii=False) + "\n",
        )
        store.write(self.artefacts.relative(self.artefacts.text(page)), _page_text(reading.lines) + "\n")
        atomic_write(
            readings.adjusted_rows_path(page),
            json.dumps(Rows.to_dict(filled), ensure_ascii=False, indent=1) + "\n",
        )
        print(f"read: {page} re-read against {len(adjustments.lines)} drawn line(s) -> {len(filled)} rows")

    def process(
        self,
        client: Callable[[str, str], str] | None = None,
        _printed: Callable[[Path], tuple[str, Any]] | None = None,
    ) -> None:
        """Classify → orient → read (the category decides: the direct read, the
        structured read, or the page's rows) → review.

        A pass that dies half-way puts the registry record back to `pending`:
        the batch is work again, not stranded in `importing` where the queue
        (which is the records) never looks for it."""
        record = load_batch(self.batch_id, self.registry_dir)
        folder = record.path
        if not folder.is_dir():
            raise PipelineError(f"batch folder missing: {folder} (did the user move it? re-adopt)")
        pages = [folder / rel for rel in sorted(record.pages)]
        if not pages:
            raise PipelineError(f"batch {self.batch_id} has no registered pages")

        self.update_status(record, BatchRecord.STATUS_PROCESSING)
        try:
            self._run_stages(record, pages, client, _printed=_printed)
        except Exception:
            self.update_status(record, BatchRecord.STATUS_PENDING)  # a failed pass is work again
            raise

    def _run_stages(
        self,
        record: BatchRecord,
        pages: list[Path],
        client: Callable[[str, str], str] | None,
        _printed: Callable[[Path], tuple[str, Any]] | None = None,
    ) -> None:
        """The machine stages. Stops at the review gate: the draft rows exist
        and each page waits on its row check (the derived `rows_pending`)."""
        # a content-changed pile (pages added/removed after adoption): the
        # regenerable stages are stale — clear them (never the agreed items) and
        # consume the flag so this run reprocesses the full current page set
        if record.content_changed:
            self.clear_stale_stages(record)

        # the stage order and the gap checks are pipeline/stage_table.py's: this
        # pass runs every stage whose artefact says it is missing, and the
        # reconciler's gap run is the same loop.
        ran = run_plan(self, record, inputs=StageInputs(client=client, printed=_printed))
        view = EngineView.of(record, self.work_dir)
        if not view.text_pages():
            # reload: the stages write the registry record themselves (grouping
            # records the boundaries); a stale object would clobber that write
            self.update_status(load_batch(self.batch_id, self.registry_dir), BatchRecord.STATUS_REVIEW)
            print(
                f"batch {self.batch_id}: no text pages — review the classification "
                "(make confirm will show nothing to transcribe)"
            )
            return
        if not ran:
            print(f"batch {self.batch_id}: every stage current — nothing re-run")
        self.update_status(load_batch(self.batch_id, self.registry_dir), BatchRecord.STATUS_REVIEW)
        print(f"batch {self.batch_id} awaiting review (make confirm ARGS={self.batch_id!r})")


def process(
    batch_id: str,
    *,
    registry_dir: Path = LoftPaths.REGISTRY_DIR,
    work_dir: Path = LoftPaths.WORK_DIR,
    archive_dir: Path = LoftPaths.ARCHIVE_DIR,
    client: Callable[[str, str], str] | None = None,
) -> None:
    """Classify → orient → read (the category decides: direct read, structured
    read, or the page's rows) → review."""
    BatchRun(batch_id, work_dir=work_dir, registry_dir=registry_dir, archive_dir=archive_dir).process(client)


def _page_text(lines: Sequence[Mapping[str, Any]]) -> str:
    """The page's text as its rows read it: each line's own reading, in the
    reading's order, blank lines dropped."""
    return "\n".join(str(line.get("text", "")).strip() for line in lines if str(line.get("text", "")).strip())


def _reader_line(row: Row) -> int | None:
    """The fitted line a row's words came from — the row builder groups by it,
    so a row of one line names it exactly; a row spanning several is ambiguous
    and names none (its reading has nowhere to land in the draft)."""
    lines = {word.line for word in row.word_boxes if word.line is not None}
    return lines.pop() if len(lines) == 1 else None


def _file_sha(path: Path) -> str:
    """The sha256 of an artefact's bytes — the correction's identity, so a
    reading can say which drawn lines it was built from."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row_line(index: int, row: Row) -> dict[str, Any]:
    """A corrected row as the reading's line record — the reader's own fields
    (index, text, box, orientation, box_source, words), so the review surface
    renders a corrected reading exactly like a draft one."""
    return {
        "index": index,
        "text": row.text,
        "box": [row.band.x0, row.band.y0, row.band.x1, row.band.y1],
        "orientation": 0,
        "box_source": "rows-adjusted",
        "words": [],
    }


def _transcribe_rows(image_path: Path, rows: list[Row], out_dir: Path) -> dict[int, str]:
    """The corrected rows' text: the same transcriber the draft rows use, over
    the rows the reviewer's lines made."""
    report = Transcriber(image_path=image_path, rows=rows, out_dir=out_dir).transcribe()
    return {int(number): text for number, text in report.transcripts.items()}


# a single call site — the stage paths and DI seams are the caller's locals
# lucidlint: ignore long-param-list a parameter object would be ceremony for one entry point
def _read_pages(
    text_pages: list[str],
    guess_dir: Path,
    oriented_dir: Path,
    work_dir: Path,
    batch_id: str,
    _reading: Callable[[Image.Image], Reading] = reading_for_page,
    _rows_text: Callable[[Path, Path], dict[int, str]] = row_transcripts,
    _corrected_text: Callable[[Path, list[Row], Path], dict[int, str]] | None = None,
) -> None:
    """The reading stage's test-seam entry — the stage itself lives on
    BatchRun.read_pages (the batch's stage paths derive from work_dir +
    batch_id inside the run; guess_dir/oriented_dir are the seam's view)."""
    BatchRun(batch_id, work_dir=work_dir).read_pages(
        text_pages, _reading=_reading, _rows_text=_rows_text, _corrected_text=_corrected_text
    )


def _read_multiline(prompt: str, readline: Callable[[str], str]) -> str:
    print(prompt, end="", flush=True)
    lines: list[str] = []
    while True:
        line = readline("")
        if line.strip() == ".":
            break
        if line == "":  # EOF (Ctrl-D) — stop, don't hang
            break
        lines.append(line)
    return "\n".join(lines)


class ReviewGate(Batch):
    """The user's confirmation gate: accept, edit, or reject each document
    of a guessed batch. An accepted document becomes an archive item (its
    transcription is the item's content file); review is the thin entry
    point, and the batch's paths and registry writes come from Batch."""

    def run(
        self,
        readline: Callable[[str], str] | None = None,
        write_line: Callable[[str], None] = print,
    ) -> None:
        """The user's confirmation gate: accept, edit, or reject each document."""
        record_path(self.batch_id, self.registry_dir)  # the batch id is a path segment — validate before any mkdir
        boundaries = self.load_boundaries(write_line)
        if boundaries is None:
            return
        line = readline if readline is not None else lambda _prompt: sys.stdin.readline()
        self.confirm_documents(boundaries, line, write_line)

        record = load_batch(self.batch_id, self.registry_dir)
        self.update_status(record, BatchRecord.STATUS_CONFIRMED)
        confirmed = [b for b in record.boundaries or [] if b.status == Document.AGREED]
        write_line(f"\nbatch {self.batch_id} confirmed ({len(confirmed)} document(s))")

    def load_boundaries(self, write_line: Callable[[str], None]) -> list[Boundary] | None:
        """The guess stage's documents, or None after reporting a photo-only
        batch — nothing to transcribe (2026-08-14 final review: `make confirm`
        must not error on it). A missing guess raises."""
        store = PipelineStore(self.work_dir)
        if not store.exists(self.artefacts.relative(self.artefacts.boundaries)):
            if store.exists(f"{self.batch_id}/classify.json"):
                classify = json.loads(store.read_latest(f"{self.batch_id}/classify.json"))
                if not any(entry.get("kind") == "text" for entry in classify.values()):
                    write_line(f"batch {self.batch_id}: no text pages — nothing to confirm")
                    return None
            raise PipelineError(f"no guess for batch {self.batch_id} — run process first")
        entries = json.loads(store.read_latest(self.artefacts.relative(self.artefacts.boundaries)))
        return [Boundary.from_dict(entry) for entry in entries]

    def confirm_documents(
        self,
        boundaries: list[Boundary],
        line: Callable[[str], str],
        write_line: Callable[[str], None],
    ) -> None:
        """The user's accept/edit/reject gate per document. An accepted
        document becomes an archive item: the gate asks for the document's own
        facts (a title and a date — an item cannot exist without them), and
        the agreed text lands as that item's transcription."""
        store = PipelineStore(self.work_dir)
        archive = Archive(DiskStore(self.archive_dir))
        for index, document in enumerate(boundaries, start=1):
            text_pages = [p for p in document.pages if store.exists(self.artefacts.relative(self.artefacts.text(p)))]
            if not text_pages:
                # a photo-only item — nothing to transcribe; its people/places
                # identification is a separate flow (user, 2026-08-17)
                write_line(f"=== Document {index} — {len(document.pages)} photo page(s), no text to check")
                continue
            write_line(f"\n=== Document {index} — pages {', '.join(document.pages)} ===")
            if document.greeting:
                write_line(f"greeting: {document.greeting}")
            for page in text_pages:
                txt_rel = self.artefacts.relative(self.artefacts.text(page))
                if store.exists(txt_rel):
                    write_line(f"--- {page} ---\n{store.read_latest(txt_rel)}")
            answer = line("accept (Enter) / edit (e) / reject (r): ").strip().lower()
            if answer == "r":
                record_confirmation(
                    self.batch_id,
                    index,
                    document,
                    None,
                    archive=archive,
                    registry_dir=self.registry_dir,
                )
                write_line(f"document {index} rejected")
                continue
            text = "\n".join(
                store.read_latest(self.artefacts.relative(self.artefacts.text(p)))
                if store.exists(self.artefacts.relative(self.artefacts.text(p)))
                else ""
                for p in text_pages
            )
            if answer == "e":
                text = _read_multiline("paste the corrected text, '.' alone ends:\n", line)
            title = line("title for this document: ").strip() or document.greeting or f"Document {index}"
            date = line("date (YYYY-MM-DD): ").strip()
            item_id = record_confirmation(
                self.batch_id,
                index,
                document,
                text,
                archive=archive,
                title=title,
                date=date,
                date_precision="exact" if len(date) == 10 else "year",
                registry_dir=self.registry_dir,
            )
            write_line(f"document {index} confirmed -> archive item {item_id}")


def review(
    batch_id: str,
    *,
    paths: LoftPaths | None = None,
    readline: Callable[[str], str] | None = None,
    write_line: Callable[[str], None] = print,
) -> None:
    """The user's confirmation gate: accept, edit, or reject each document.
    An accepted document becomes an item in the paths' archive."""
    locations = paths or LoftPaths()
    ReviewGate(
        batch_id,
        work_dir=locations.work_dir,
        registry_dir=locations.registry_dir,
        archive_dir=locations.archive_dir,
    ).run(readline=readline, write_line=write_line)


def cmd_printed(batch_id: str) -> int:
    """Read a printed pile: the VLM transcribes each page directly — no rows,
    no ink measurement (handwriting's machinery, which printed text defeats)."""
    BatchRun(batch_id).printed_pages()
    return 0


def _add_batch_command(sub, name: str, help_text: str, fn: Callable[..., Any]) -> Any:
    """A subcommand taking one ``batch_id`` and dispatching to an entry point."""
    p = sub.add_parser(name, help=help_text)
    p.add_argument("batch_id")
    p.set_defaults(fn=fn)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline", description="The ingest chain per batch")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_batch_command(sub, name="process", help_text="orient + raw OCR + model guess + boundaries", fn=process)
    _add_batch_command(sub, name="review", help_text="user confirmation gate for the guessed text", fn=review)
    _add_batch_command(
        sub,
        name="printed",
        help_text="read a PRINTED pile: one VLM transcription per page, no rows",
        fn=cmd_printed,
    )
    args = parser.parse_args(argv)
    try:
        args.fn(args.batch_id)
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
