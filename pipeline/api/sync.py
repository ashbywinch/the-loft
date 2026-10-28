"""The two-app sync contract (TECHSPEC §16.15, MULTI-DOC-IMPORT-PRD.md R14).

The backend owns the archive's write seam; the frontend proposes, the
backend records. This module is the shared contract:
- the confirmation payload shape (validated before anything is recorded);
- the frontend's ``Outbox`` — the catch-up backlog for real-time pushes
  that failed (the laptop was off); the backend pulls it and the website
  marks items received;

Nothing confirmed is ever lost to a failed push.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from document.document import DOCUMENT_AGREED, DOCUMENT_REJECTED
from document.page_size import PageSize
from document.rectangle import Rectangle
from document.row_adjustments import RowAdjustments
from document.stages import PageStatus
from document.traces import Traces
from document.words import Words
from pipeline.api.row_correction import RowCorrection
from pipeline.boundary import Boundary
from pipeline.detect.reader import reading_for_page
from pipeline.htr import htr_pages_vlm
from pipeline.layout import (
    Layout,
    build_layout,
    load_layout_store,
    rotate_detections,
)
from pipeline.model.unsure_word import UnsureWord
from pipeline.model.vlm import orientation_report, selfreport_words
from pipeline.page_image import PageImage
from pipeline.registry import load_batch, record_path
from pipeline.rows.rows import Rows
from pipeline.rows_reading import RowsReading
from pipeline.store import PipelineStore
from tools.archive import Archive
from tools.atomic import atomic_write
from tools.dated_fact import PRECISIONS
from tools.loft_paths import REGISTRY_DIR
from tools.store import DiskStore  # noqa: F401 — the architecture test's store-layer marker

ROWS_JSON = "rows.json"  # the reading's rows file beside the guess (object-model Phase 1)
WORDS_JSON = "words.json"  # the reading's words, written beside the rows
ADJUSTMENTS_JSON = "row-adjustments.json"  # the reviewer's drawn row lines
ADJUSTED_ROWS_JSON = "rows-adjusted.json"  # the correction's rows (the wire contract)


def pages_pending(readings: BatchReadings, pages: list[str]) -> list[str]:
    """The batch's pages waiting in the "Check the rows" queue, in page order.

    A page waits when it has draft rows and no recorded row check — the derived
    `PageStatus.ROWS_PENDING` (`BatchReadings.page_status`). A page the read
    stage has not reached is the machine's, not a person's, and a page whose
    check is recorded has left the queue. The list, not a count: the portal's
    door opens the first one."""
    return [page for page in pages if readings.page_status(page) is PageStatus.ROWS_PENDING]


@dataclass(frozen=True)
class BatchReadings:
    """One batch's reading files on disk — the one place the ocr-guess
    path algebra lives. The read stage writes them, the review reads and
    corrects them, a rotation remaps them: they travel together, so they
    are one thing."""

    work_dir: Path
    batch_id: str

    @property
    def guess_dir(self) -> Path:
        return self.work_dir / self.batch_id / "ocr-guess"

    def rows_path(self, page: str) -> Path:
        """The reading's rows file (the proposal)."""
        return self.guess_dir / Path(page).with_suffix(f".{ROWS_JSON}")

    def words_path(self, page: str) -> Path:
        """The reading's words (what the drawn-lines correction groups)."""
        return self.guess_dir / f"{Path(page).stem}.{WORDS_JSON}"

    def adjustments_path(self, page: str) -> Path:
        """The reviewer's drawn row lines."""
        return self.guess_dir / Path(page).with_suffix(f".{ADJUSTMENTS_JSON}")

    def adjusted_rows_path(self, page: str) -> Path:
        """The correction's rows (the wire contract)."""
        return self.guess_dir / Path(page).with_suffix(f".{ADJUSTED_ROWS_JSON}")

    def oriented_path(self, page: str) -> Path:
        """The oriented page image (the orient stage's marker)."""
        return self.work_dir / self.batch_id / "oriented" / page

    def checked(self, page: str) -> bool:
        """Whether the reviewer's row check is recorded — the drawn lines AND
        the rows they made. Both: a write that fails between the two leaves
        the check half-recorded, and the review refuses that state too."""
        return self.adjustments_path(page).is_file() and self.adjusted_rows_path(page).is_file()

    def page_status(self, page: str) -> PageStatus:
        """Where the page has got to, read from the artefacts that mark its
        stages (TECHSPEC §16.14.2's marker rule) rather than kept in a field
        that could go stale. `rows_draft` and `marks` are transient — the
        marks are never persisted and the draft rows are the reading's own
        write — so no page is ever read back in either."""
        if self.checked(page):
            return PageStatus.ROWS_ADJUSTED
        if self.rows_path(page).is_file():
            return PageStatus.ROWS_PENDING
        if self.words_path(page).is_file():
            return PageStatus.WORDS
        if self.oriented_path(page).is_file():
            return PageStatus.ORIENTED
        return PageStatus.NEW

    def rebuild_rotated_layout(
        self,
        reading: RowsReading | Layout,
        page: str,
        steps: int,
        image: Image.Image,
        rotated: Image.Image,
    ) -> Layout:
        """The strip-era reading's rotation: rotate the layout's detections
        in the PRE-turn frame (the stale boxes live in the pre-turn dims,
        not the current image's) and rebuild the layout at the rotated
        image's size, so the boxes never misalign with the pixels."""
        layout = _as_layout(reading)
        detections = rotate_detections(layout.detections(), steps, image.width, image.height)
        selfreport_path = self.guess_dir / Path(page).with_suffix(".selfreport.json")
        selfreport = (
            [UnsureWord.from_dict(entry) for entry in json.loads(selfreport_path.read_text(encoding="utf-8"))]
            if selfreport_path.exists()
            else None
        )
        vlm_text = "\n".join(line.text for line in layout.lines)
        rebuilt = build_layout(
            layout.page or page,
            rotated.width,
            rotated.height,
            vlm_text,
            detections,
            selfreport=selfreport,
        )
        rebuilt.lines.sort(key=lambda line: line.index)
        return rebuilt

    def load_reading(self, page: str, journal_path: Path, image_path: Path) -> RowsReading | Layout:
        """The page's reading for a rotate — the rows reading where one
        exists, else the strip-era layout — with any half-rotated crash
        completed FIRST. A rows recovery that is abandoned (an unreadable
        journal) REFUSES the rotate: the image's rotation is unknown, and
        a delta computed from the stale reading would silently misalign
        the boxes — the journal stays for the operator to resolve. A
        layout recovery abandons logged and the stale layout stands (the
        caller computes the delta from it)."""
        rows_path = self.rows_path(page)
        layout_path = self.guess_dir / Path(page).with_suffix(".layout.json")
        if rows_path.is_file():
            reading = RowsReading.from_dict(json.loads(rows_path.read_text(encoding="utf-8")))
            if journal_path.exists() and not _recover_crashed_rows(journal_path, reading, image_path, rows_path):
                raise ValueError(
                    f"rotation recovery failed: the journal {journal_path.name} is unreadable — "
                    "the reading may be misaligned with the image; resolve the journal before retrying"
                )
            return reading
        layout = load_layout_store(PipelineStore(self.work_dir), str(layout_path.relative_to(self.work_dir)))
        if journal_path.exists():
            layout = _recover_crashed_layout(
                journal_path, layout, layout_path, image_path, page, self.work_dir, self.batch_id
            )
        return layout


def _as_layout(reading: RowsReading | Layout) -> Layout:
    """A reading as the layout record the layout tools take — a rows reading
    carries the same lines, so the conversion loses nothing (its rotation and
    revision ride the layout's carried-through keys)."""
    return reading if isinstance(reading, Layout) else Layout.from_dict(reading.to_dict())


def _rotation_of(reading: RowsReading | Layout) -> int:
    """The rotation a reading records — the rows reading's own field, or the
    strip-era layout's carried-through wire key."""
    return reading.rotation if isinstance(reading, RowsReading) else int(reading.extra.get("rotation", 0))


logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("batch_id", "doc_index", "pages", "text", "status", "confirmed_at")

BATCH_ID = re.compile(r"^[A-Za-z0-9-]+$")

# page names from boundaries.json become path segments in the drafts read —
# a charset that excludes every separator and "..", so a hostile entry can't
# read outside the batch's guess dir (defense-in-depth).
# `~` is allowed: phone export duplicates arrive as "name~2.jpg" — the
# guard must not reject real scans.
_PAGE_NAME = re.compile(r"^[A-Za-z0-9._~-]+$")

# Rotation degrees — the reviewer's orientation corrections are quarter
# turns of the page; layouts record the cumulative rotation in degrees CW,
# so the recovery/delta arithmetic works in degrees.
FULL_ROTATION_DEGREES = 360
QUARTER_TURN_DEGREES = 90
QUARTERS_PER_TURN = FULL_ROTATION_DEGREES // QUARTER_TURN_DEGREES  # 4 quarter-turns per full rotation


def validate_confirmation(payload: dict[str, Any]) -> dict[str, Any]:
    """The confirmation's required shape; raises ValueError with the reason."""
    missing = [f for f in REQUIRED_FIELDS if f not in payload]
    if missing:
        raise ValueError(f"confirmation missing fields: {missing}")
    if payload["status"] not in ("confirmed", "rejected"):
        raise ValueError(f"confirmation status must be confirmed|rejected, got {payload['status']!r}")
    if not isinstance(payload["pages"], list) or not payload["pages"]:
        raise ValueError("confirmation pages must be a non-empty list")
    # doc_index becomes a registry boundary index and a file name — a float
    # (1e309 -> OverflowError) or bool would slip past the server's int()
    # and 500 instead of 400 (the receiver's "client errors are 4xx, never
    # 500" contract)
    doc_index = payload["doc_index"]
    if isinstance(doc_index, bool) or not isinstance(doc_index, int) or doc_index < 1:
        raise ValueError(f"confirmation doc_index must be a positive integer, got {doc_index!r}")
    _check_agreement(payload)
    return payload


def _check_agreement(payload: dict[str, Any]) -> None:
    """What an AGREED document needs beyond the shape: its text and its own
    facts (a title and a date — an item cannot exist without them). A
    rejection carries none of them."""
    if payload["status"] == "confirmed":
        if not isinstance(payload["text"], str):
            raise ValueError("confirmation text must be a string")
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("an agreed document needs a title")
        if not isinstance(payload.get("date"), str) or not payload["date"].strip():
            raise ValueError("an agreed document needs a date")
        if payload.get("date_precision") not in PRECISIONS:
            raise ValueError(
                f"confirmation date_precision must be one of {sorted(PRECISIONS)}, "
                f"got {payload.get('date_precision')!r}"
            )


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
        return [
            (path.stem, json.loads(path.read_text(encoding="utf-8"))) for path in sorted(self.directory.glob("*.json"))
        ]

    def mark_received(self, item_ids: list[str]) -> None:
        for item_id in item_ids:
            if not self._ITEM_ID.match(item_id):
                raise ValueError(f"invalid outbox item id: {item_id!r}")  # path traversal guard
            (self.directory / f"{item_id}.json").unlink(missing_ok=True)


# The sync write seam's identity + optional dirs — a single call site,
def record_confirmation(
    batch_id: str,
    doc_index: int,
    document: Boundary,
    text: str | None,
    *,
    archive: Archive,
    title: str = "",
    date: str = "",
    date_precision: str = "",
    registry_dir: Path = REGISTRY_DIR,
) -> str:
    """The backend's single write path for a reviewed document — shared by
    the CLI review gate and the sync receiver (TECHSPEC §16.15).

    An agreed document becomes an archive item: the review's facts (title,
    date) mint it, or supersede the item the document already became
    (``document.item_id``), with the corrected text as the item's
    transcription. The registry's boundary records the item and the review's
    state (replace-by-pages, append) — the archive holds the agreed text, the
    registry holds which page set it came from. ``text=None`` records a
    rejection: nothing is minted and nothing is silently dropped. Returns the
    item id (empty for a rejection). The batch id is validated FIRST: it
    becomes a path segment, and no write precedes the guard."""
    if not BATCH_ID.match(batch_id):
        raise ValueError(f"invalid batch id: {batch_id!r}")
    # load (and so validate the batch was adopted) BEFORE any write — an
    # unknown batch must fabricate nothing and raise RegistryError -> 4xx,
    # not leave a stray archive item behind.
    record = load_batch(batch_id, registry_dir)
    # the registry knows which item this document already became — a
    # re-agreement supersedes it, never mints a second (the request carries
    # the boundary as the reviewer re-sent it, without the id)
    previous = next((b for b in record.boundaries or [] if b.pages == document.pages), None)
    if previous is not None and not document.item_id:
        document.item_id = previous.item_id
    item_id = ""
    if text is not None:
        item = archive.agree_document(
            title=title,
            date=date,
            date_precision=date_precision,
            text=text,
            item_id=document.item_id,
        )
        item_id = item.id
        document.item_id = item.id
        document.reviewed(DOCUMENT_AGREED)
    else:
        document.reviewed(DOCUMENT_REJECTED)
    boundaries = [b for b in record.boundaries or [] if b.pages != document.pages]
    boundaries.append(document)
    record.boundaries = boundaries
    atomic_write(record_path(batch_id, registry_dir), json.dumps(record.to_dict(), indent=1, ensure_ascii=False) + "\n")
    return item_id


# the review seam's functions all take (batch_id, page, work_dir) — they are the
# module's one vocabulary, each a thin file operation over the same batch tree; a
# carrier class would be the object-model Phase 6 package restructure, not this change
# lucidlint: ignore latent-class the batch-path vocabulary is this module's shape; the restructure is Phase 6
def apply_row_adjustments(batch_id: str, page: str, adjustments: RowAdjustments, work_dir: Path) -> RowCorrection:
    """The reviewer's drawn row lines -> the page's rows
    (`rows.adjust` over the words the read stage persisted, each with
    its own reading line, so an incomplete set of lines merges with the
    draft rows), persisted beside the reading:

    - ``<page>.row-adjustments.json`` — the drawn lines, as drawn;
    - ``<page>.rows-adjusted.json`` — the correction's rows, the artefact
      `Rows.to_dict` writes.

    The same traces are validated (`Rows.validate`) in the same pass, so the
    answer can name a drawing that caught no writing or a word it left out.

    A page whose words were never persisted (read before the read stage
    wrote them) cannot be corrected — ValueError, never a silent empty
    build."""
    if not BATCH_ID.match(batch_id) or not safe_page_name(page):
        raise ValueError("invalid batch or page name")
    readings = BatchReadings(work_dir, batch_id)
    rows_path = readings.rows_path(page)
    words_path = readings.words_path(page)
    if not rows_path.is_file():
        raise ValueError(f"no reading for {page} — the read stage must run first")
    if not words_path.is_file():
        raise ValueError(f"no words for {page} — re-read the page, then draw its rows")
    words = Words.from_dict(json.loads(words_path.read_text(encoding="utf-8")))
    reading = RowsReading.from_dict(json.loads(rows_path.read_text(encoding="utf-8")))
    traces = Traces(
        words=tuple(words),
        adjustments=adjustments,
        page_size=PageSize(reading.width, reading.height),
    )
    builder = Rows.from_traces(traces)
    rows = builder.adjust(adjustments)
    violations = tuple(builder.validate(traces))
    adjustments_json = json.dumps(adjustments.to_dict(), ensure_ascii=False, indent=1)
    atomic_write(readings.adjustments_path(page), adjustments_json + "\n")
    atomic_write(readings.adjusted_rows_path(page), json.dumps(Rows.to_dict(rows), ensure_ascii=False, indent=1) + "\n")
    return RowCorrection(rows=rows, violations=violations)


def safe_page_name(page: str) -> bool:
    """A page name that is safe as a path segment (charset excludes every
    separator and "..") — the drafts read and the review surface's image
    route share this one guard (defense-in-depth, review, 2026-08-14)."""
    return bool(_PAGE_NAME.match(page)) and ".." not in page


@dataclass(frozen=True)
class PageReviewState:
    """A batch's persisted per-page review data: the reviewer's drawn
    corrections and the validated reading layouts, each keyed by page."""

    layouts: dict[str, Any]
    layout_errors: dict[str, Any]
    adjustments: dict[str, Any]
    adjusted_rows: dict[str, Any]


def _page_review_state(readings: BatchReadings, pages: list[str]) -> PageReviewState:
    """The review surface's persisted per-page state. The reviewer's
    corrections are the drawn lines and the rows they made — a reopened
    page shows what was drawn and the correction, not the proposal it
    replaced. The page's layout is the rows reading where one exists,
    else the strip-era layout.json — validated BEFORE serving (fail-fast,
    2026-08-17: a degenerate or out-of-image box must NEVER reach the
    review surface — the page gets no layout, its text still shows, and
    a loud marker instead of wrong boxes)."""
    guess_dir = readings.guess_dir
    layouts: dict[str, Any] = {}
    layout_errors: dict[str, Any] = {}
    adjustments: dict[str, Any] = {}
    adjusted_rows: dict[str, Any] = {}
    for page in pages:
        drawn_path = readings.adjustments_path(page)
        corrected_path = readings.adjusted_rows_path(page)
        if drawn_path.exists() and corrected_path.exists():
            adjustments[page] = json.loads(drawn_path.read_text(encoding="utf-8"))
            adjusted_rows[page] = json.loads(corrected_path.read_text(encoding="utf-8"))
        rows_path = guess_dir / Path(page).with_suffix(f".{ROWS_JSON}")
        if rows_path.exists():
            # the reading's rows — the object-model Phase-1 source;
            # already the shape the review surface consumes
            layouts[page] = json.loads(rows_path.read_text(encoding="utf-8"))
            continue
        # strip-era fallback: batches read before the rows redirect
        # keep their layout.json, still validated before serving
        layout_path = guess_dir / Path(page).with_suffix(".layout.json")
        if not layout_path.exists():
            continue
        layout = load_layout_store(PipelineStore(readings.work_dir), str(layout_path.relative_to(readings.work_dir)))
        violations = layout.validate()
        if violations:
            layout_errors[page] = violations
            continue
        layouts[page] = layout.to_dict()
    return PageReviewState(
        layouts=layouts,
        layout_errors=layout_errors,
        adjustments=adjustments,
        adjusted_rows=adjusted_rows,
    )


def draft_payloads(batch_id: str, work_dir: Path) -> list[dict[str, Any]]:
    """The machine drafts the review surface reads: per-page guessed texts
    + the document boundaries + the per-page layout (TECHSPEC §16.16:
    line boxes + per-word confidence, when the layout pass has run), for
    one batch. The batch id is validated (it becomes a path segment —
    traversal guard, 2026-08-14 review)."""
    if not BATCH_ID.match(batch_id):
        raise ValueError(f"invalid batch id: {batch_id!r}")
    readings = BatchReadings(work_dir, batch_id)
    guess_dir = readings.guess_dir
    boundaries_path = guess_dir / "boundaries.json"
    if not boundaries_path.exists():
        return []
    # the registry's own boundary records: the document's artefact fields plus
    # the transport's keys, which the drafts payload carries through as they are
    entries: list[dict[str, Any]] = json.loads(boundaries_path.read_text(encoding="utf-8"))
    drafts: list[dict[str, Any]] = []
    for boundary in (Boundary.from_dict(entry) for entry in entries):
        pages = boundary.pages
        for page in pages:
            if not safe_page_name(page):
                raise ValueError(f"unsafe page name in boundaries: {page!r}")
        texts = {
            page: (guess_dir / Path(page).with_suffix(".txt")).read_text(encoding="utf-8")
            for page in pages
            if (guess_dir / Path(page).with_suffix(".txt")).exists()
        }
        state = _page_review_state(readings, pages)
        # the orientations the pipeline already read on each page (VR15,
        # 2026-08-17): the distinct per-line orientations from the layout.
        # The reviewer's rotate to a covered orientation is view-only — no
        # queued re-read. A page with a layout but no per-line orientations
        # was read at the image's upright (0); a page with no layout has
        # nothing covered (any rotate queues the old path).
        orientations = {
            page: sorted({int(line.get("orientation", 0)) for line in state.layouts[page].get("lines", [])})
            for page in pages
            if page in state.layouts
        }
        drafts.append(
            {
                "batch_id": batch_id,
                "pages": pages,
                "texts": texts,
                "layouts": state.layouts,
                "layout_errors": state.layout_errors,
                "orientations": orientations,
                "row_adjustments": state.adjustments,
                "adjusted_rows": state.adjusted_rows,
                **boundary.to_dict(),
            }
        )
    return drafts


def _recover_crashed_layout(
    journal_path: Path,
    layout: Layout,
    layout_path: Path,
    image_path: Path,
    page: str,
    work_dir: Path,
    batch_id: str,
) -> Layout:
    """Complete a half-rotated crash from the journal — rebuild the layout to
    the recorded intent so the boxes never silently misalign. An unreadable
    journal abandons recovery (logged) and the stale layout stands; the
    caller computes the delta from it."""
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        intended = int(journal.get("rotation", 0)) % FULL_ROTATION_DEGREES
        stale = int(journal.get("from", 0)) % FULL_ROTATION_DEGREES
        if int(layout.extra.get("rotation", 0)) % FULL_ROTATION_DEGREES == stale:
            swapped = journal.get("swapped")
            if swapped is None:
                image = ImageOps.exif_transpose(Image.open(image_path))
                swapped = image.width != layout.width or image.height != layout.height
            if not swapped:
                # the crash happened BEFORE the image swap — the layout is
                # still consistent with the current image
                journal_path.unlink(missing_ok=True)
            else:
                # the image IS rotated — recover the layout to the intent
                image = ImageOps.exif_transpose(Image.open(image_path))
                recovery = (intended - stale) % FULL_ROTATION_DEGREES
                if recovery:
                    steps = recovery // QUARTER_TURN_DEGREES
                    # the stale boxes live in the PRE-turn frame — rotate
                    # them by the STALE LAYOUT's recorded dims, not the
                    # current image's
                    detections = rotate_detections(
                        layout.detections(),
                        steps,
                        int(layout.width or image.width),
                        int(layout.height or image.height),
                    )
                    vlm_text = "\n".join(line.text for line in layout.lines)
                    selfreport_path = work_dir / batch_id / "ocr-guess" / Path(page).with_suffix(".selfreport.json")
                    selfreport = (
                        [UnsureWord.from_dict(entry) for entry in json.loads(selfreport_path.read_text())]
                        if selfreport_path.exists()
                        else None
                    )
                    layout = build_layout(
                        layout.page or page,
                        image.width,
                        image.height,
                        vlm_text,
                        detections,
                        selfreport=selfreport,
                    )
                    layout.extra["rotation"] = intended
                    layout.write_store(PipelineStore(work_dir), str(layout_path.relative_to(work_dir)))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("sync: unreadable rotation journal %s — recovery abandoned: %s", journal_path, e)
        journal_path.unlink(missing_ok=True)
        return layout
    return layout


def _recover_crashed_rows(
    journal_path: Path,
    rows: RowsReading,
    image_path: Path,
    rows_path: Path,
) -> bool:
    """Complete a half-rotated crash for a rows reading: advance the rows'
    boxes to the journal's recorded intent so they never silently
    misalign with the rotated image, and PERSIST the recovered reading.
    The journal's ``swapped`` flag (flipped after the image swap) tells
    whether the image moved — reliable at every angle, including 180°,
    where the dimensions never change. A legacy journal without the flag
    falls back to the dimensions heuristic. Returns True when the journal
    was resolved (the rows are consistent with the current image); False
    when it was unreadable and recovery is abandoned — the caller must
    NOT proceed, because the image's actual rotation is unknown and a
    delta computed from the stale rows would silently misalign them."""
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        intended = int(journal.get("rotation", 0)) % FULL_ROTATION_DEGREES
        stale = int(journal.get("from", 0)) % FULL_ROTATION_DEGREES
        if rows.rotation % FULL_ROTATION_DEGREES != stale:
            return True
        swapped = journal.get("swapped")
        if swapped is None:
            image = ImageOps.exif_transpose(Image.open(image_path))
            swapped = image.width != rows.width or image.height != rows.height
        if not swapped:
            # the crash happened BEFORE the image swap — the rows are
            # still consistent with the current image
            journal_path.unlink(missing_ok=True)
            return True
        recovery = (intended - stale) % FULL_ROTATION_DEGREES
        steps = recovery // QUARTER_TURN_DEGREES
        width, height = rows.width, rows.height
        for _ in range(steps):
            for line in rows.lines:
                x0, y0, x1, y1 = line["box"]
                line["box"] = [height - y1, x0, height - y0, x1]
            width, height = height, width
        rows.rotation = intended
        atomic_write(rows_path, json.dumps(rows.to_dict(), ensure_ascii=False, indent=1) + "\n")
        journal_path.unlink(missing_ok=True)
        return True
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("sync: unreadable rotation journal %s — recovery abandoned: %s", journal_path, e)
        # the journal STAYS: the image's rotation is unknown, so any later
        # rotate must fail again rather than silently misalign from the
        # stale rows; the operator resolves the journal first
        return False


def _rotate_rows_reading(
    reading: RowsReading,
    words_path: Path,
    steps: int,
    image: Image.Image,
) -> Words | None:
    """Rotate the rows reading one quarter-turn per step in the reading's
    recorded frame: the line boxes — and the words' coordinates, when the
    words sidecar was persisted — remap by (x, y) -> (height - y, x), and
    the measured waistline/baseline become the rotated box's own edges,
    keeping the reading-order rule (rows.adjust's rule B) in the new
    frame. Returns the rotated words for the caller's atomic write."""
    width, height = reading.width, reading.height
    words = Words.from_dict(json.loads(words_path.read_text(encoding="utf-8"))) if words_path.is_file() else None
    for _ in range(steps):
        lines: list[dict[str, Any]] = []
        for line in reading.lines:
            x0, y0, x1, y1 = line["box"]
            line["box"] = [height - y1, x0, height - y0, x1]
            lines.append(line)
        reading.lines = lines
        if words is not None:
            for word in words:
                x0, y0, x1, y1 = word.x0, word.y0, word.x1, word.y1
                word.rect = Rectangle(x0=height - y1, y0=x0, x1=height - y0, y1=x1)
                # the measured baseline/waistline are horizontals now
                # vertical: the rotated box's own edges keep the reading
                # order rule (rows.adjust's rule B) in the new frame
                word.waistline, word.baseline = word.y0, word.y1
        width, height = height, width
    return words


def rotate_page(batch_id: str, page: str, quarters: int, work_dir: Path) -> bool:
    if not BATCH_ID.match(batch_id) or not safe_page_name(page):
        raise ValueError("invalid batch or page name")
    quarters = int(quarters) % QUARTERS_PER_TURN
    readings = BatchReadings(work_dir, batch_id)
    image_path = work_dir / batch_id / "oriented" / page
    rows_path = readings.rows_path(page)
    layout_path = readings.guess_dir / Path(page).with_suffix(".layout.json")
    if not image_path.is_file():
        raise ValueError(f"no such page: {page}")
    if not rows_path.is_file() and not layout_path.is_file():
        raise ValueError(f"no reading for {page} — the read stage must run before a rotate")
    journal_path = work_dir / batch_id / "oriented" / f"{Path(page).stem}.rotate.json"
    reading = readings.load_reading(page, journal_path, image_path)
    current = _rotation_of(reading) % FULL_ROTATION_DEGREES
    words: Words | None = None
    delta = (quarters * QUARTER_TURN_DEGREES - current) % FULL_ROTATION_DEGREES
    if delta == 0:
        journal_path.unlink(missing_ok=True)
        return False
    steps = delta // QUARTER_TURN_DEGREES
    image = ImageOps.exif_transpose(Image.open(image_path))
    rotated = image.rotate(-QUARTER_TURN_DEGREES * steps, expand=True)  # clockwise
    rotated.info.pop("exif", None)
    words_path = readings.words_path(page)
    if isinstance(reading, RowsReading):
        words = _rotate_rows_reading(reading, words_path, steps, image)
        reading.width, reading.height = rotated.width, rotated.height
        reading.rotation = (current + delta) % FULL_ROTATION_DEGREES
    else:
        reading = readings.rebuild_rotated_layout(reading, page, steps, image, rotated)
        reading.extra["rotation"] = (current + delta) % FULL_ROTATION_DEGREES
    tmp = image_path.with_name(image_path.name + ".tmp")
    rotated.save(tmp, format=image.format or "JPEG")
    # the journal lands BEFORE the image swap with swapped:false — a crash
    # here leaves the image unrotated and the rows consistent. After the
    # swap the flag flips to true BEFORE the reading write, so a crash
    # between the two is recoverable at every angle (the flag, not the
    # dimensions, says whether the image moved — dimensions are blind at
    # 180°).
    atomic_write(
        journal_path,
        json.dumps({"from": current, "rotation": _rotation_of(reading), "swapped": False}, ensure_ascii=False) + "\n",
    )
    tmp.replace(image_path)
    atomic_write(
        journal_path,
        json.dumps({"from": current, "rotation": _rotation_of(reading), "swapped": True}, ensure_ascii=False) + "\n",
    )
    if isinstance(reading, RowsReading):
        atomic_write(rows_path, json.dumps(reading.to_dict(), ensure_ascii=False, indent=1) + "\n")
        if words is not None:
            atomic_write(words_path, json.dumps(words.to_dict(), ensure_ascii=False, indent=1) + "\n")
    else:
        reading.write_store(PipelineStore(work_dir), str(layout_path.relative_to(work_dir)))
    journal_path.unlink(missing_ok=True)
    return True


def _job_state_path(batch_id: str, work_dir: Path) -> Path:
    return work_dir / batch_id / "ocr-guess" / ".jobs.json"


def page_job_state(batch_id: str, work_dir: Path) -> dict[str, str]:
    """The pages currently being reprocessed (the rotate's async job) —
    the drafts payload exposes the names so the surface can grey the
    document with a note while the transcription re-runs (2026-08-16)."""
    path = _job_state_path(batch_id, work_dir)
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (ValueError, OSError):
        return {}


def set_page_job(batch_id: str, page: str, state: str | None, work_dir: Path) -> None:
    """Record or clear a page's reprocess state (atomic — the payload reads
    it live)."""
    path = _job_state_path(batch_id, work_dir)
    current = page_job_state(batch_id, work_dir)
    if state is None:
        current.pop(page, None)
    else:
        current[page] = state
    if current:
        atomic_write(path, json.dumps(current, indent=1) + "\n")
    else:
        path.unlink(missing_ok=True)


def demote_stale_jobs(work_dir: Path) -> None:
    """A server restart kills the reprocess threads mid-flight — any page
    left "transcribing" never got its re-read (its text is stale), so it
    demotes to "failed": the warning shows, never a silent half-done page
    (2026-08-16)."""
    for jobs_path in sorted(work_dir.glob("*/ocr-guess/.jobs.json")):
        batch_id = jobs_path.parent.parent.name
        for page, state in page_job_state(batch_id, work_dir).items():
            if state == "transcribing":
                set_page_job(batch_id, page, "failed", work_dir)


def _write_multi_sidecar(
    page: str,
    image_path: Path,
    raw_dir: Path,
    text: str,
    orientation_report_fn: Callable[[Path, str], dict[str, Any]] | None,
) -> None:
    """The reviewer's rotate signals the first pass missed an orientation
    — re-run the report on the corrected image, locating the freshly
    re-read transcription; a multi-direction report writes the sidecar the
    layout stage reads (the per-line boxes + orientations, keyed to the
    text's line numbers)."""
    report_fn = orientation_report_fn if orientation_report_fn is not None else orientation_report
    report = report_fn(image_path, text)
    hints = report.get("orientation_hint", []) if isinstance(report, dict) else []
    degrees = {int(h.get("degrees")) for h in hints if h.get("degrees") in (0, 90, 180, 270)}
    # the v3 multi-direction evidence lives in the lines' degrees too
    located = report.get("lines", []) if isinstance(report, dict) else []
    degrees |= {int(ln.get("degrees")) for ln in located if ln.get("degrees") in (0, 90, 180, 270)}
    if len(degrees) >= 2:
        atomic_write(
            raw_dir / Path(page).with_suffix(".orientation.json"),
            json.dumps(report, ensure_ascii=False) + "\n",
        )


def reprocess_page_transcription(
    batch_id: str,
    page: str,
    work_dir: Path,
    *,
    transcribe: Any = None,
    selfreport: Callable[..., list[UnsureWord]] | None = None,
    orientation_report_fn: Callable[[Path, str], dict[str, Any]] | None = None,
    people: list[str] | None = None,
    places: list[str] | None = None,
    label: str | None = None,
) -> None:
    """The slow half of the orientation fix: re-read the page's text with
    the vision model on the CORRECTED image (2026-08-16 — the old
    transcription was read from the upside-down page, which is unreliable:
    page-02's first line read "At last venture this form is the building
    of a" vs the corrected page's "A new venture this term is the holding
    of a"). Runs as the backend's async job after the fast rotation; the
    page's job state marks it while it runs. The second pass does better
    (2026-08-17): the reviewer's rotate IS the signal the first pass
    missed an orientation, so the orientation report re-runs on the
    corrected image and the reading is rebuilt with FRESH boxes — never
    the old remapped ones.
    ``transcribe``/``selfreport``/``orientation_report_fn`` are the
    injectable seams for tests. On failure the page is marked
    "failed" — the stale text stays visible with the warning, never a
    silent wrong answer."""
    if not BATCH_ID.match(batch_id) or not safe_page_name(page):
        raise ValueError("invalid batch or page name")
    guess_dir = work_dir / batch_id / "ocr-guess"
    image_path = work_dir / batch_id / "oriented" / page
    rows_path = guess_dir / Path(page).with_suffix(f".{ROWS_JSON}")
    if not image_path.is_file():
        raise ValueError(f"no such page: {page}")
    try:
        rotation = 0
        if rows_path.exists():
            rotation = int(json.loads(rows_path.read_text(encoding="utf-8")).get("rotation", 0))
        elif (guess_dir / Path(page).with_suffix(".layout.json")).is_file():
            # strip-era fallback: carry the old layout's recorded rotation
            layout_path = guess_dir / Path(page).with_suffix(".layout.json")
            layout = load_layout_store(PipelineStore(work_dir), str(layout_path.relative_to(work_dir)))
            rotation = int(layout.extra.get("rotation", 0))
        # force the re-read: drop the markers the pipeline's skip logic uses
        raw_dir = guess_dir
        for suffix in (".txt", ".vlm.json", ".selfreport.json", ".orientation.json"):
            (raw_dir / Path(page).with_suffix(suffix)).unlink(missing_ok=True)
        htr_pages_vlm(
            [PageImage(page, image_path)],
            raw_dir,
            transcribe=transcribe,
            people=people,
            places=places,
            label=label,
            # the reprocess's own root — never the global WORK_DIR
            # (the hermetic tests, 2026-08-29)
            store_root=work_dir,
        )
        new_text = (raw_dir / Path(page).with_suffix(".txt")).read_text(encoding="utf-8")
        report = (
            selfreport(image_path, new_text, people=people, places=places)
            if selfreport
            else selfreport_words(image_path, new_text, people=people, places=places)
        )
        report_path = raw_dir / Path(page).with_suffix(".selfreport.json")
        atomic_write(report_path, json.dumps([word.to_dict() for word in report], ensure_ascii=False, indent=1) + "\n")
        # the fresh orientation report on the CORRECTED image — a
        # multi-direction report writes the sidecar the layout stage reads
        _write_multi_sidecar(page, image_path, raw_dir, new_text, orientation_report_fn)
        # the fresh reading on the CORRECTED image — rows, not a layout:
        # the line boxes come from the marks chain, the text re-mapped;
        # the reading's words are written beside them (the drawn-lines
        # correction groups those words)
        reading = reading_for_page(ImageOps.exif_transpose(Image.open(image_path)))
        text_lines = [ln for ln in new_text.splitlines() if ln.strip()]
        for i, line in enumerate(reading.lines):
            line["text"] = text_lines[i] if i < len(text_lines) else ""
        new_rows = RowsReading(
            page=page,
            width=reading.width,
            height=reading.height,
            rotation=rotation,
            lines=reading.lines,
        )
        atomic_write(rows_path, json.dumps(new_rows.to_dict(), ensure_ascii=False, indent=1) + "\n")
        atomic_write(
            BatchReadings(work_dir, batch_id).words_path(page),
            json.dumps(Words(reading.words).to_dict(), ensure_ascii=False, indent=1) + "\n",
        )
        set_page_job(batch_id, page, None, work_dir)
    # lucidlint: ignore broad-except the stage's terminal boundary — mark failed on ANY error, then re-raise
    except Exception:
        set_page_job(batch_id, page, "failed", work_dir)
        raise
