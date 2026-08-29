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
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from tools.atomic import atomic_write
from tools.htr import htr_pages_vlm
from tools.layout import (
    build_layout,
    layout_detections,
    load_layout,
    load_layout_store,
    rotate_detections,
    validate_layout,
    write_layout_store,
)
from tools.layout_stage import run_layout
from tools.loft_paths import REGISTRY_DIR, WORK_DIR
from tools.pipeline_store import PipelineStore
from tools.registry import load_batch, record_path
from tools.store import DiskStore  # noqa: F401
from tools.vlm import orientation_report, selfreport_words

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("batch_id", "doc_index", "pages", "text", "status", "confirmed_at")

BATCH_ID = re.compile(r"^[A-Za-z0-9-]+$")

# page names from boundaries.json become path segments in the drafts read —
# a charset that excludes every separator and "..", so a hostile entry can't
# read outside the batch's guess dir (defense-in-depth, review, 2026-08-14).
# `~` is allowed: phone export duplicates arrive as "name~2.jpg" (the
# PhotoScan batch, 2026-08-16 — the guard must not reject real scans).
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
    # and 500 instead of 400 (review, 2026-08-15: the receiver's
    # "client errors are 4xx, never 500" contract)
    doc_index = payload["doc_index"]
    if isinstance(doc_index, bool) or not isinstance(doc_index, int) or doc_index < 1:
        raise ValueError(f"confirmation doc_index must be a positive integer, got {doc_index!r}")
    # a rejection carries no corrected text — record_confirmation treats
    # text=None as the rejection marker, so the validator must not demand a
    # string for it (review, 2026-08-15: a rejection with text null got a
    # 400 and was never recorded)
    if payload["status"] != "rejected" and not isinstance(payload["text"], str):
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
        return [
            (path.stem, json.loads(path.read_text(encoding="utf-8"))) for path in sorted(self.directory.glob("*.json"))
        ]

    def mark_received(self, item_ids: list[str]) -> None:
        for item_id in item_ids:
            if not self._ITEM_ID.match(item_id):
                raise ValueError(f"invalid outbox item id: {item_id!r}")  # path traversal guard
            (self.directory / f"{item_id}.json").unlink(missing_ok=True)


# The sync write seam's identity + optional dirs — a single call site,
# lucidlint: ignore long-param-list no repeated group
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
    if not BATCH_ID.match(batch_id):
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


def safe_page_name(page: str) -> bool:
    """A page name that is safe as a path segment (charset excludes every
    separator and "..") — the drafts read and the review surface's image
    route share this one guard (defense-in-depth, review, 2026-08-14)."""
    return bool(_PAGE_NAME.match(page)) and ".." not in page


def draft_payloads(batch_id: str, work_dir: Path) -> list[dict[str, Any]]:
    """The machine drafts the review surface reads: per-page guessed texts
    + the document boundaries + the per-page layout (TECH-SPEC §16.16:
    line boxes + per-word confidence, when the layout pass has run), for
    one batch. The batch id is validated (it becomes a path segment —
    traversal guard, 2026-08-14 review)."""
    if not BATCH_ID.match(batch_id):
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
            if not safe_page_name(page):
                raise ValueError(f"unsafe page name in boundaries: {page!r}")
        texts = {
            page: (guess_dir / Path(page).with_suffix(".txt")).read_text(encoding="utf-8")
            for page in pages
            if (guess_dir / Path(page).with_suffix(".txt")).exists()
        }
        # Fail-fast (2026-08-17): a layout with a degenerate or
        # out-of-image box must NEVER reach the review surface — the page
        # gets no layout (its text still shows) and a loud marker instead
        # of wrong boxes. The reviewer must never see boxes that don't
        # correspond to the page.
        layouts = {}
        layout_errors = {}
        for page in pages:
            layout_path = guess_dir / Path(page).with_suffix(".layout.json")
            if not layout_path.exists():
                continue
            layout = load_layout_store(PipelineStore(work_dir), str(layout_path.relative_to(work_dir)))
            violations = validate_layout(layout)
            if violations:
                layout_errors[page] = violations
                continue
            layouts[page] = layout
        # the orientations the pipeline already read on each page (VR15,
        # 2026-08-17): the distinct per-line orientations from the layout.
        # The reviewer's rotate to a covered orientation is view-only — no
        # queued re-read. A page with a layout but no per-line orientations
        # was read at the image's upright (0); a page with no layout has
        # nothing covered (any rotate queues the old path).
        orientations = {
            page: sorted({int(line.get("orientation", 0)) for line in layouts[page].get("lines", [])})
            for page in pages
            if page in layouts
        }
        drafts.append(
            {
                "batch_id": batch_id,
                "pages": pages,
                "texts": texts,
                "layouts": layouts,
                "layout_errors": layout_errors,
                "orientations": orientations,
                **document,
            }
        )
    return drafts


# lucidlint: ignore long-param-list a single crash-recovery call site — the paths are the caller's locals
def _recover_crashed_layout(
    journal_path: Path,
    layout: dict[str, Any],
    layout_path: Path,
    image_path: Path,
    page: str,
    work_dir: Path,
    batch_id: str,
) -> dict[str, Any]:
    """Complete a half-rotated crash from the journal — rebuild the layout to
    the recorded intent so the boxes never silently misalign. An unreadable
    journal abandons recovery (logged) and the stale layout stands; the
    caller computes the delta from it."""
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        intended = int(journal.get("rotation", 0)) % FULL_ROTATION_DEGREES
        stale = int(journal.get("from", 0)) % FULL_ROTATION_DEGREES
        if int(layout.get("rotation", 0)) % FULL_ROTATION_DEGREES == stale:
            image = ImageOps.exif_transpose(Image.open(image_path))
            if image.width == int(layout.get("width", 0)) and image.height == int(layout.get("height", 0)):
                # the crash happened BEFORE the image swap — the journal
                # is premature, the layout is still consistent
                journal_path.unlink(missing_ok=True)
            else:
                # the image IS rotated — recover the layout to the intent
                recovery = (intended - stale) % FULL_ROTATION_DEGREES
                if recovery:
                    steps = recovery // QUARTER_TURN_DEGREES
                    # the stale boxes live in the PRE-turn frame — rotate
                    # them by the STALE LAYOUT's recorded dims, not the
                    # current image's (2026-08-26: the swapped image's
                    # height sent every recovered box off-image; same
                    # coordinate-frame class as the crop-origin bug)
                    detections = rotate_detections(
                        layout_detections(layout),
                        steps,
                        int(layout.get("width", image.width)),
                        int(layout.get("height", image.height)),
                    )
                    vlm_text = "\n".join(line["text"] for line in layout.get("lines", []))
                    selfreport_path = work_dir / batch_id / "ocr-guess" / Path(page).with_suffix(".selfreport.json")
                    selfreport = (
                        json.loads(selfreport_path.read_text(encoding="utf-8")) if selfreport_path.exists() else None
                    )
                    layout = build_layout(
                        layout.get("page", page),
                        image.width,
                        image.height,
                        vlm_text,
                        detections,
                        selfreport=selfreport,
                    )
                    layout["rotation"] = intended
                    write_layout_store(layout, PipelineStore(work_dir), str(layout_path.relative_to(work_dir)))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("sync: unreadable rotation journal %s — recovery abandoned: %s", journal_path, e)
        journal_path.unlink(missing_ok=True)
        return layout
    return layout


def rotate_page(batch_id: str, page: str, quarters: int, work_dir: Path) -> bool:
    """Apply a reviewer's orientation correction: rotate the oriented page
    clockwise by ``quarters`` × 90° and re-anchor its layout in place
    (2026-08-16 — the orientation arbiter cannot read cursive, so an
    upside-down page passes review; the fix must correct the pipeline's
    data, not just the view). The rotation is a rigid remap of the
    detection boxes — no re-OCR — and the transcription is
    rotation-invariant content (the same words, rotated), so only the
    image and the layout change. The layout records the CUMULATIVE applied
    rotation ("rotation": degrees CW), so the sync's intents can be the
    DESIRED cumulative and the delta is computed here — idempotent and
    order-safe across offline queues (a retried intent is a no-op).
    Returns whether anything rotated (the caller only reprocesses when it
    did). Both writes are atomic — a reader never meets a half-rotated
    page."""
    if not BATCH_ID.match(batch_id) or not safe_page_name(page):
        raise ValueError("invalid batch or page name")
    quarters = int(quarters) % QUARTERS_PER_TURN
    image_path = work_dir / batch_id / "oriented" / page
    layout_path = work_dir / batch_id / "ocr-guess" / Path(page).with_suffix(".layout.json")
    if not image_path.is_file():
        raise ValueError(f"no such page: {page}")
    if not layout_path.is_file():
        raise ValueError(f"no layout for {page} — the layout pass must run before a rotate")
    layout = load_layout_store(PipelineStore(work_dir), str(layout_path.relative_to(work_dir)))
    # A crash between the image swap and the layout write leaves the image
    # rotated while the layout still carries the old rotation and boxes —
    # the pair is not transactional (bot review, 2026-08-16). The journal
    # records the intent; the next rotate completes the layout BEFORE the
    # delta is computed, so the boxes never silently misalign.
    journal_path = work_dir / batch_id / "oriented" / f"{Path(page).stem}.rotate.json"
    if journal_path.exists():
        layout = _recover_crashed_layout(journal_path, layout, layout_path, image_path, page, work_dir, batch_id)
    # the cumulative rotation the page already carries — the intent is the
    # DESIRED total, so the delta is what we apply now. The desired CAN be
    # 0 (a reviewer rotating the wrong way back to the original) — the
    # delta is the no-op check, not the desired itself (2026-08-16: the
    # early return on quarters==0 silently ignored the rotate-back).
    current = int(layout.get("rotation", 0)) % FULL_ROTATION_DEGREES
    delta = (quarters * QUARTER_TURN_DEGREES - current) % FULL_ROTATION_DEGREES
    if delta == 0:
        # the recovery may have just completed the layout from a crash —
        # the journal's job is done either way (2026-08-16)
        journal_path.unlink(missing_ok=True)
        return False
    steps = delta // QUARTER_TURN_DEGREES
    image = ImageOps.exif_transpose(Image.open(image_path))
    rotated = image.rotate(-QUARTER_TURN_DEGREES * steps, expand=True)  # clockwise
    rotated.info.pop("exif", None)
    detections = rotate_detections(layout_detections(layout), steps, image.width, image.height)
    selfreport_path = work_dir / batch_id / "ocr-guess" / Path(page).with_suffix(".selfreport.json")
    selfreport = json.loads(selfreport_path.read_text(encoding="utf-8")) if selfreport_path.exists() else None
    vlm_text = "\n".join(line["text"] for line in layout.get("lines", []))
    new_layout = build_layout(
        layout.get("page", page),
        rotated.width,
        rotated.height,
        vlm_text,
        detections,
        selfreport=selfreport,
    )
    new_layout["rotation"] = (current + delta) % FULL_ROTATION_DEGREES
    # Rotation is a rigid remap: the transcription's order is authoritative.
    # The rebuild's reading-order sort re-sorts by the ROTATED geometry,
    # which scrambles the text order (2026-08-20 — after a 90° turn both
    # lines sit in one horizontal band and the x-sort swaps them). Restore
    # the transcription order: build_layout's index IS the vlm_text
    # position, so sorting by it is the text order.
    new_layout["lines"].sort(key=lambda ln: ln["index"])
    tmp = image_path.with_name(image_path.name + ".tmp")
    rotated.save(tmp, format=image.format or "JPEG")
    # the journal lands BEFORE the image swap: a crash mid-rotate leaves a
    # recoverable trail (the next rotate completes the layout) instead of a
    # silently misaligned page (bot review, 2026-08-16)
    atomic_write(
        journal_path,
        json.dumps({"from": current, "rotation": new_layout["rotation"]}, ensure_ascii=False) + "\n",
    )
    tmp.replace(image_path)
    write_layout_store(new_layout, PipelineStore(work_dir), str(layout_path.relative_to(work_dir)))
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
    """The second pass does better (2026-08-17): the reviewer's rotate is
    the signal the first pass missed an orientation — re-run the report on
    the corrected image, locating the freshly re-read transcription; a
    multi-direction report writes the sidecar the layout stage reads (the
    per-line boxes + orientations, keyed to the text's line numbers)."""
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


# lucidlint: ignore long-param-list the reprocess gate's identity + injectable seams — a single call site
def reprocess_page_transcription(
    batch_id: str,
    page: str,
    work_dir: Path,
    *,
    transcribe: Any = None,
    selfreport: Any = None,
    orientation_report_fn: Callable[[Path, str], dict[str, Any]] | None = None,
    layout_runner: Callable[[str, Path, list[str] | None], None] | None = None,
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
    corrected image and the layout stage rebuilds the layout with FRESH
    detections — never the old remapped boxes.
    ``transcribe``/``selfreport``/``orientation_report_fn``/``layout_runner``
    are the injectable seams for tests. On failure the page is marked
    "failed" — the stale text stays visible with the warning, never a
    silent wrong answer."""
    if not BATCH_ID.match(batch_id) or not safe_page_name(page):
        raise ValueError("invalid batch or page name")
    guess_dir = work_dir / batch_id / "ocr-guess"
    image_path = work_dir / batch_id / "oriented" / page
    layout_path = guess_dir / Path(page).with_suffix(".layout.json")
    if not image_path.is_file() or not layout_path.is_file():
        raise ValueError(f"no such page or layout: {page}")
    try:
        layout = load_layout_store(PipelineStore(work_dir), str(layout_path.relative_to(work_dir)))
        # force the re-read: drop the markers the pipeline's skip logic uses
        raw_dir = guess_dir
        for suffix in (".txt", ".vlm.json", ".selfreport.json", ".orientation.json"):
            (raw_dir / Path(page).with_suffix(suffix)).unlink(missing_ok=True)
        htr_pages_vlm(
            [(page, image_path)],
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
        atomic_write(report_path, json.dumps(report, ensure_ascii=False, indent=1) + "\n")
        # the fresh orientation report on the CORRECTED image — a
        # multi-direction report writes the sidecar the layout stage reads
        _write_multi_sidecar(page, image_path, raw_dir, new_text, orientation_report_fn)
        runner = layout_runner if layout_runner is not None else run_layout
        runner(batch_id, work_dir, [page])
        new_layout = load_layout(layout_path)
        if "rotation" in layout:
            new_layout["rotation"] = layout.get("rotation", 0)
            write_layout_store(new_layout, PipelineStore(work_dir), str(layout_path.relative_to(work_dir)))
        set_page_job(batch_id, page, None, work_dir)
    # lucidlint: ignore broad-except the stage's terminal boundary — mark failed on ANY error, then re-raise
    except Exception:
        set_page_job(batch_id, page, "failed", work_dir)
        raise
