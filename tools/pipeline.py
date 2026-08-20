"""The ingest chain driver: orient → raw OCR → model guess → boundaries →
user confirmation, per registered batch (TECH-SPEC §16.13/§16.14).

process runs the machine stages and leaves the batch awaiting review; the
guess stage hands the noisy raw OCR plus the standing knowledge (people,
places) and the batch label to the model, which returns per-page verbatim
corrections AND document boundaries (a page opens a document at a greeting,
closes it at a sign-off). review is the user's confirmation gate: each
document's text is accepted, edited, or rejected, and the confirmed
transcriptions land in work/<batch>/ocr-confirmed/.

Usage:
    python tools/pipeline.py process <batch-id>
    python tools/pipeline.py review  <batch-id>
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from tools.ai_client import AIClient, AIClientError
from tools.classify import route, run_classify
from tools.grouping import score_boundaries
from tools.htr import htr_pages, htr_pages_vlm
from tools.layout_stage import run_layout as layout_stage_run
from tools.loft_paths import ARCHIVE_DIR, REGISTRY_DIR, WORK_DIR
from tools.ocr import orient_pages
from tools.pipeline_store import PipelineStore, text_sha256
from tools.registry import RegistryError as PipelineError
from tools.registry import load_batch, record_path
from tools.store import DiskStore, StoreError  # noqa: F401
from tools.sync import record_confirmation
from tools.vlm import VlmError, line_orientation_degrees, orientation_report

PAGE_LIMIT = 30  # one guess call per batch; beyond this the context is too big — chunking is future work
GUESS_PAGE_CHUNK = 5  # the guess re-emits each page's corrected text; the OUTPUT size binds — 5 pages of
# verbatim text + JSON fits the client's max_tokens (2026-08-14: a 12-page pile's JSON response truncated)

# The multi-orientation gate (PRD VR15, 2026-08-17): a page whose arbiter
# scores suggest text in more than one direction gets the vision model's
# orientation report — and only then. The second-best rotation must carry
# a meaningful share of the winner's strong words (the postcard's 0:16 /
# 270:9 splits; a clean page's losers are near zero).
AMBIGUITY_RATIO = 0.25  # the second-best rotation's share of the winner
AMBIGUITY_FLOOR = 5  # ...and it must clear this many strong words outright

# The guess model (2026-08-17): the default chat model (deepseek-v4-flash)
# reasons UNBOUNDED on the correction tasks — reproduced: 12K then 24K
# tokens of pure reasoning, finish_reason "length", zero content, the
# guess stage failed with "empty response from API". The vision model
# (mimo-v2.5, the pipeline's proven model — it completes the same prompt
# with finish_reason "stop") is the completing choice on this endpoint;
# the thinking-disable/budget params are ignored by the endpoint, so the
# model must simply be one that answers.
GUESS_MODEL = "dynamic/image"

STATUS_PROCESSING = "importing"
STATUS_REVIEW = "review"
STATUS_CONFIRMED = "confirmed"


def _standing_knowledge(archive_dir: Path = ARCHIVE_DIR) -> tuple[list[str], list[str]]:
    """The archive's people and places names — the context the guess works from."""
    people: list[str] = []
    places: list[str] = []
    store = PipelineStore(archive_dir)
    if store.exists("people.json"):
        for record in json.loads(store.read_latest("people.json")).get("people", []):
            name = str(record.get("name", "")).strip()
            if name:
                people.append(name)
            people += [str(alias) for alias in record.get("aliases", []) if str(alias).strip()]
    if store.exists("places.json"):
        for record in json.loads(store.read_latest("places.json")).get("places", []):
            name = str(record.get("name", "")).strip()
            if name:
                places.append(name)
    return sorted(set(people)), sorted(set(places))


def _guess_prompt(
    page_texts: list[tuple[str, str]], label: str, people: list[str], places: list[str]
) -> tuple[str, str]:
    """The system + user prompt for the guess stage — verbatim discipline
    (IMPORT-PRD Rule L), boundary detection by greeting/sign-off, standing
    knowledge as context."""
    system = (
        "You are the transcription assistant for a family archive. You correct noisy "
        "OCR of scanned family letters.\n"
        "Rules:\n"
        "- VERBATIM: the document's own words, nothing added, nothing removed. Fix OCR "
        "noise (mangled words, split lines) but never paraphrase, never add words or "
        "punctuation the page lacks, never correct spelling.\n"
        "- Keep the page's line and paragraph structure.\n"
        '- A page you cannot read at all: text "" — never invent content.\n'
        "- Detect document boundaries: a page STARTS a document when it opens a letter "
        '(a greeting such as "Dear X", an address block, a date beginning a new '
        'letter); a page ENDS one at a sign-off ("Yours, X", a signature, the close '
        "of a letter).\n"
        f"Context — known family people: {', '.join(people) or 'none'}. "
        f"Known places: {', '.join(places) or 'none'}. Batch: {label or 'unlabelled'}.\n"
        'Output JSON only: {"pages": [{"page": "<filename>", "text": "<verbatim '
        'corrected text>", "starts_document": true/false, "ends_document": true/false, '
        '"greeting": "<text or null>", "signoff": "<text or null>"}]}'
    )
    blocks = "\n\n".join(f"Page {name}:\n{text}" for name, text in page_texts)
    user = f"Here is the tesseract OCR of the batch's pages.\n\n{blocks}"
    return system, user


def _flag_bool(value: object) -> bool:
    """The model's boundary flags are JSON booleans; string forms must not
    coerce ("false" → True would mis-group documents, 2026-08-14 review)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1")
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return False


def guess_pages(
    page_texts: list[tuple[str, str]],
    label: str,
    people: list[str],
    places: list[str],
    client: Callable[[str, str], str],
) -> list[dict[str, Any]]:
    """One model call: corrected verbatim text + boundary flags per page.

    ``client`` is the chat seam (AIClient.chat shape); injectable for tests.
    """
    if len(page_texts) > PAGE_LIMIT:
        raise PipelineError(
            f"batch has {len(page_texts)} pages — the guess stage handles up to {PAGE_LIMIT} per call; "
            "chunking is future work"
        )
    system, user = _guess_prompt(page_texts, label, people, places)
    try:
        raw = client(system, user)
    except AIClientError as exc:
        raise PipelineError(f"model guess failed: {exc}") from exc
    try:
        payload = json.loads(raw)
        pages = payload["pages"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PipelineError(f"model returned unparseable JSON: {raw[:200]!r}") from exc
    out: list[dict[str, Any]] = []
    for entry in pages:
        if not isinstance(entry, dict) or "page" not in entry or "text" not in entry:
            raise PipelineError(f"model returned a malformed page entry: {entry!r}")
        out.append(
            {
                "page": str(entry["page"]),
                "text": str(entry["text"]),
                "starts_document": _flag_bool(entry.get("starts_document")),
                "ends_document": _flag_bool(entry.get("ends_document")),
                "greeting": entry.get("greeting"),
                "signoff": entry.get("signoff"),
            }
        )
    return out


def apply_routes(classify: dict[str, Any], rotations: dict[str, Any]) -> dict[str, Any]:
    """Add the print/cursive route to each text page from its orientation
    density; photo/drawing pages get no route (never transcribed)."""
    for name, entry in classify.items():
        if entry.get("kind") == "text":
            density = int(rotations.get(name, {}).get("strong", 0))
            entry["route"] = route(density)
        else:
            entry["route"] = None
    return classify


def _guess_is_stale(text_pages: list[str], raw_dir: Path, guess_dir: Path, boundaries_path: Path) -> bool:
    """Is the existing guess stale? Two failure modes: (1) individual page
    .txt files were cleared (a bad layout_detect run) — the boundaries may
    exist while the artifacts they promise are gone; (2) the RAW
    transcriptions the guess was built from changed (a re-orientation
    regenerated ocr-raw) — the recorded input fingerprints no longer
    match. Existence of boundaries alone is a lie of a completion proxy —
    a stale guess must be re-run, not silently reused (2026-08-20)."""
    missing = [name for name in text_pages if not (guess_dir / Path(name).with_suffix(".txt")).exists()]
    stale_inputs = _guess_inputs_changed(text_pages, raw_dir, boundaries_path)
    if not missing and not stale_inputs:
        return False
    reasons = []
    if missing:
        reasons.append(f"{len(missing)} page(s) missing")
    if stale_inputs:
        reasons.append("raw transcriptions changed")
    print(f"WARNING: guess stale ({'; '.join(reasons)}) — deleting stale boundaries and re-running guess")
    boundaries_path.unlink(missing_ok=True)
    # Also clear any stale orientation reports that reference the old text
    for name in missing:
        ori = guess_dir / Path(name).with_suffix(".orientation.json")
        if ori.exists():
            ori.unlink()
    return True


def _guess_inputs_changed(text_pages: list[str], raw_dir: Path, boundaries_path: Path) -> bool:
    """Did the raw transcriptions the guess was built from change? The
    boundaries.json records each raw text's fingerprint; a mismatch means
    the guess reflects an older reading (2026-08-20: a re-orientation
    regenerated ocr-raw, but the guess still carried the pre-fix text). A
    boundaries file without the fingerprint field (pre-2026-08-20) cannot
    prove its inputs and is treated as stale once."""
    inputs_path = boundaries_path.with_suffix(".inputs.json")
    if not inputs_path.exists():
        return True  # pre-fingerprint boundaries cannot prove their inputs
    try:
        recorded = json.loads(inputs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if not recorded:
        return True
    for name in text_pages:
        raw_txt = raw_dir / Path(name).with_suffix(".txt")
        if not raw_txt.exists():
            continue  # the missing-check above handles absent artifacts
        current = text_sha256(raw_txt.read_text(encoding="utf-8"))
        if recorded.get(name) != current:
            return True
    return False


# a single call site — the stage paths and DI seams are the caller's locals
# lucidlint: ignore long-param-list a parameter object would be ceremony for one entry point
def process(
    batch_id: str,
    *,
    registry_dir: Path = REGISTRY_DIR,
    work_dir: Path = WORK_DIR,
    archive_dir: Path = ARCHIVE_DIR,
    client: Callable[[str, str], str] | None = None,
    orientation_report_fn: Callable[[Path, str], dict[str, Any]] | None = None,
    run_layout: Callable[[str, Path], None] | None = None,
) -> None:
    """Classify → orient (text pages) → route → HTR/tesseract → guess →
    layout (boxes + flags; the multi-orientation pages get the combined
    per-line layout) → review."""
    record = load_batch(batch_id, registry_dir)
    folder = Path(str(record["path"]))
    if not folder.is_dir():
        raise PipelineError(f"batch folder missing: {folder} (did the user move it? re-adopt)")
    pages = [folder / rel for rel in sorted(record.get("pages", {}))]
    if not pages:
        raise PipelineError(f"batch {batch_id} has no registered pages")

    batch_work = work_dir / batch_id
    classify_path = batch_work / "classify.json"
    oriented_dir = batch_work / "oriented"
    raw_dir = batch_work / "ocr-raw"
    guess_dir = batch_work / "ocr-guess"
    boundaries_path = guess_dir / "boundaries.json"

    _update_status(record, batch_id, STATUS_PROCESSING, registry_dir)

    # a content-changed pile (pages added/removed after adoption): the
    # regenerable stages are stale — clear them (NEVER ocr-confirmed) and
    # consume the flag so this run reprocesses the full current page set
    if record.get("content_changed"):
        _clear_stale_stages(record, batch_id, classify_path, oriented_dir, raw_dir, guess_dir, registry_dir)

    # 1. classify FIRST (on the raw pages): photos/drawings skip orientation + OCR entirely
    classify, text_pages, image_pages = _classify_pages(batch_id, classify_path, work_dir, registry_dir, pages)

    if not text_pages:
        _update_status(record, batch_id, STATUS_REVIEW, registry_dir)
        print(
            f"batch {batch_id}: no text pages — review the classification "
            "(make confirm will show nothing to transcribe)"
        )
        return

    # 2. orient + tesseract raw, TEXT PAGES ONLY (rotations.json is the
    # completion marker — piles may hold PNG/TIFF pages, not only JPEGs)
    _orient_and_ocr(text_pages, folder, oriented_dir, raw_dir, batch_work)

    # 3. route print vs cursive by the orientation density, recorded in classify.json
    cursive = _route_pages(classify, oriented_dir, classify_path, text_pages)

    # 4. transcribe the cursive pages (the 2026-08-14 decision: the vision
    # model by default; LOFT_HTR_BACKEND=local keeps the orli+TrOCR privacy mode)
    _transcribe_cursive(cursive, oriented_dir, raw_dir, batch_id, registry_dir)

    # 5. model guess on the TEXT pages only (chunked past PAGE_LIMIT — a
    # multi-page document spanning a chunk boundary is split, a noted
    # limitation; postcards and letters within a chunk group correctly)
    if boundaries_path.exists() and not _guess_is_stale(text_pages, raw_dir, guess_dir, boundaries_path):
        print("guess already present — reusing")
    else:
        _run_guess(
            text_pages,
            raw_dir,
            guess_dir,
            boundaries_path,
            record,
            batch_id,
            registry_dir,
            archive_dir,
            classify,
            client,
        )

    # 6. layout stage (VR14 — every text page gets line boxes + per-word
    # confidence; VR15 — the multi-orientation pages get the combined
    # per-line-orientation layout). The vision-model orientation report
    # runs only for the arbiter-ambiguous pages; the pass itself runs
    # under the .venv-htr interpreter (PaddleOCR lives there).
    report = orientation_report_fn if orientation_report_fn is not None else orientation_report
    # the module-level run_layout (tools.layout_stage) — the DI param of
    # the same name shadows it inside process, so resolve before use
    layout_runner = run_layout if run_layout is not None else layout_stage_run
    _write_orientation_hints(text_pages, batch_work, oriented_dir, guess_dir, report)
    layout_runner(batch_id, work_dir)

    _update_status(record, batch_id, STATUS_REVIEW, registry_dir)
    print(f"batch {batch_id} awaiting review (make confirm ARGS={batch_id!r})")


# would add a type for one use
# lucidlint: ignore long-param-list a single call site — the stage paths are the caller's locals; a parameter object
def _clear_stale_stages(
    record: dict[str, Any],
    batch_id: str,
    classify_path: Path,
    oriented_dir: Path,
    raw_dir: Path,
    guess_dir: Path,
    registry_dir: Path,
) -> None:
    """A content-changed pile (pages added/removed after adoption): the
    regenerable stages are stale — clear them (NEVER ocr-confirmed) and
    consume the flag so this run reprocesses the full current page set."""
    for stale in (classify_path, oriented_dir, raw_dir, guess_dir):
        if stale.is_file():
            stale.unlink(missing_ok=True)
        elif stale.is_dir():
            shutil.rmtree(stale)
    record.pop("content_changed")
    _update_status(record, batch_id, STATUS_PROCESSING, registry_dir)
    print("content changed since adoption — regenerable stages cleared; confirmed transcriptions preserved")


def _classify_pages(
    batch_id: str, classify_path: Path, work_dir: Path, registry_dir: Path, pages: list[Path]
) -> tuple[dict[str, Any], list[str], list[str]]:
    """The per-page photo/text classification — run when absent, a pile's
    photos/drawings skip orientation + OCR entirely. Returns
    (classify, text_pages, image_pages)."""
    store = PipelineStore(work_dir)
    rel_classify = f"{batch_id}/classify.json"
    if store.exists(rel_classify):
        print("classification already present — reusing")
    else:
        run_classify(batch_id, registry_dir=registry_dir, work_dir=work_dir)
        print(f"classified {len(pages)} page(s) -> {classify_path}")
    classify = json.loads(store.read_latest(rel_classify))
    text_pages = [name for name, entry in classify.items() if entry.get("kind") == "text"]
    image_pages = [name for name, entry in classify.items() if entry.get("kind") != "text"]
    if image_pages:
        print(f"{len(image_pages)} page(s) are images — no transcription")
    return classify, text_pages, image_pages


def _orient_and_ocr(text_pages: list[str], folder: Path, oriented_dir: Path, raw_dir: Path, batch_work: Path) -> None:
    """Orient the text pages and run tesseract raw OCR (rotations.json is
    the completion marker — piles may hold PNG/TIFF pages, not only JPEGs)."""
    store = PipelineStore(batch_work.parent)
    batch_id = batch_work.name
    if not store.exists(f"{batch_id}/oriented/rotations.json"):
        oriented = orient_pages([folder / name for name in text_pages], oriented_dir, root=folder)
        raw_dir.mkdir(parents=True, exist_ok=True)
        for page in oriented:
            store.write(f"{batch_id}/ocr-raw/{Path(str(page['name'])).with_suffix('.txt')}", str(page["text"]))
        store.write(
            f"{batch_id}/oriented/rotations.json",
            json.dumps(
                {
                    str(page["name"]): {"degrees": page["degrees"], "strong": page["strong"], "scores": page["scores"]}
                    for page in oriented
                },
                indent=1,
                ensure_ascii=False,
            )
            + "\n",
        )
        rotated = sum(1 for page in oriented if page["degrees"] != 0)
        print(f"oriented + raw OCR: {len(oriented)} page(s), {rotated} rotated -> {batch_work}")
    else:
        print("oriented + raw OCR already present — reusing")


def _route_pages(classify: dict[str, Any], oriented_dir: Path, classify_path: Path, text_pages: list[str]) -> list[str]:
    """Route print vs cursive by the orientation density, recorded in
    classify.json; returns the cursive page names."""
    work_dir = classify_path.parent.parent
    batch_id = classify_path.parent.name
    store = PipelineStore(work_dir)
    rotations = json.loads(store.read_latest(f"{batch_id}/oriented/rotations.json"))
    apply_routes(classify, rotations)
    store.write(f"{batch_id}/classify.json", json.dumps(classify, indent=1, ensure_ascii=False) + "\n")
    cursive = [name for name, entry in classify.items() if entry.get("route") == "cursive"]
    if cursive:
        print(f"routing: {len(cursive)} cursive page(s) -> HTR, {len(text_pages) - len(cursive)} print -> tesseract")
    return cursive


def _transcribe_cursive(
    cursive: list[str], oriented_dir: Path, raw_dir: Path, batch_id: str, registry_dir: Path
) -> None:
    """Transcribe the cursive pages (the 2026-08-14 decision: the vision
    model by default; LOFT_HTR_BACKEND=local keeps the orli+TrOCR privacy mode)."""
    if cursive:
        cursive_pages = [(name, oriented_dir / name) for name in cursive]
        if os.environ.get("LOFT_HTR_BACKEND", "vlm") == "vlm":
            people, places = _standing_knowledge()
            with contextlib.suppress(PipelineError):
                label = load_batch(batch_id, registry_dir).get("label")
            htr_pages_vlm(cursive_pages, raw_dir, people=people, places=places, label=label)
        else:
            htr_pages(cursive_pages, raw_dir)


# object would add a type for one use
# lucidlint: ignore long-param-list a single call site — the guess stage's inputs are the caller's locals; a parameter
def _run_guess(
    text_pages: list[str],
    raw_dir: Path,
    guess_dir: Path,
    boundaries_path: Path,
    record: dict[str, Any],
    batch_id: str,
    registry_dir: Path,
    archive_dir: Path,
    classify: dict[str, Any],
    client: Callable[[str, str], str] | None,
) -> None:
    """The model guess on the TEXT pages only (chunked past PAGE_LIMIT — a
    multi-page document spanning a chunk boundary is split, a noted
    limitation; postcards and letters within a chunk group correctly),
    then the grouping scorer over the FULL page sequence (photos
    included) — the duplex/paper/page-number evidence the model never
    sees decides the boundaries (tools/grouping.py, 2026-08-17)."""
    work_dir = raw_dir.parent.parent
    store = PipelineStore(work_dir)
    reg_store = PipelineStore(registry_dir)
    raw_texts = [
        (name, store.read_latest(f"{batch_id}/ocr-raw/{Path(name).with_suffix('.txt')}")) for name in text_pages
    ]
    label = str(record.get("label", ""))
    people, places = _standing_knowledge(archive_dir)
    chat = client if client is not None else AIClient(model=GUESS_MODEL, max_tokens=12000, timeout=900.0).chat
    flags: list[dict[str, Any]] = []
    # each iteration calls guess_pages — a model inference with side effects — and extends
    # with its result; a comprehension would bury the side-effecting call inside an expression
    # lucidlint: ignore loop-pipeline side-effecting model call per iteration, not a pure build
    for start in range(0, len(raw_texts), GUESS_PAGE_CHUNK):
        flags.extend(guess_pages(raw_texts[start : start + GUESS_PAGE_CHUNK], label, people, places, chat))
    guess_dir.mkdir(parents=True, exist_ok=True)
    # the model echoes page names — they become file paths; a name
    # outside the registered set is dropped from the writes AND the
    # grouping, so boundaries.json never references an untrusted page
    # (2026-08-15 review: the drop guarded only the writes, and the
    # old group_documents still received every flag — the review gate
    # then crashed on the missing .txt or read outside guess_dir via ../)
    known_flags = [flag for flag in flags if str(flag["page"]) in text_pages]
    for flag in flags:
        if str(flag["page"]) not in text_pages:
            print(f"guess returned an unknown page {flag['page']!r} — dropped")
    for flag in known_flags:
        store.write(f"{batch_id}/ocr-guess/{Path(str(flag['page'])).with_suffix('.txt')}", str(flag["text"]))
    # the grouping scorer (2026-08-17): the full page sequence, the
    # classify kinds, the paper sizes, and the corrected texts feed the
    # evidence hierarchy — duplex sides > paper size > page numbers >
    # the model's flags. Photo pages enter the documents (the postcard's
    # picture side is page 1 of its document, acceptance 21).
    folder = Path(str(record.get("path", "")))
    dims: dict[str, tuple[int, int]] = {}
    for rel in sorted(record.get("pages", {})):
        with Image.open(folder / rel) as im:
            dims[rel] = im.size
    flags_by_page = {str(flag["page"]): flag for flag in known_flags}
    texts = {str(flag["page"]): flag.get("text") for flag in known_flags}
    boundaries = score_boundaries(
        sorted(record.get("pages", {})),
        {page: str(entry.get("kind", "text")) for page, entry in classify.items()},
        dims,
        texts,
        flags_by_page,
    )
    inputs = {
        name: text_sha256(store.read_latest(f"{batch_id}/ocr-raw/{Path(name).with_suffix('.txt')}"))
        for name in text_pages
    }
    store.write(f"{batch_id}/ocr-guess/boundaries.json", json.dumps(boundaries, indent=1, ensure_ascii=False) + "\n")
    store.write(f"{batch_id}/ocr-guess/boundaries.inputs.json", json.dumps(inputs, ensure_ascii=False))
    # seed the registry record with the full boundaries so the review
    # surface's batch list shows the correct pending count (the registry
    # is the status' home; the guess stage's boundaries.json is the
    # pipeline's output, never the registry — 2026-08-15)
    record["boundaries"] = boundaries
    reg_store.write(f"{batch_id}.json", json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    print(f"model guess: {len(flags)} page(s), {len(boundaries)} document(s) -> {guess_dir}")


def _ambiguous_rotations(scores: dict[str, int]) -> bool:
    """The arbiter's strong-word counts suggest text in more than one
    direction (PRD VR15): the second-best rotation carries a meaningful
    share of the winner's words — the postcard's {0: 16, 270: 9} splits,
    while a clean page's losers sit near zero."""
    vals = sorted((int(scores.get(str(k), 0)) for k in (0, 90, 180, 270)), reverse=True)
    if len(vals) < 2 or vals[0] <= 0:
        return False
    return vals[1] >= max(AMBIGUITY_FLOOR, AMBIGUITY_RATIO * vals[0])


def _write_orientation_hints(
    text_pages: list[str],
    batch_work: Path,
    oriented_dir: Path,
    guess_dir: Path,
    orientation_report_fn: Callable[[Path, str], dict[str, Any]],
) -> None:
    """For pages whose arbiter scores suggest more than one text
    direction, ask the vision model to LOCATE the page's known
    transcription (the guess's corrected text — the model assigns each
    line its box + orientation) and store it
    (``ocr-guess/<stem>.orientation.json``) for the layout stage. A
    single-dominant page gets no report — the plain single-orientation
    layout suffices; the report runs only where the scores already
    suspect more than one direction (PRD VR15, 2026-08-17). A
    single-direction report (the model disagrees) also writes nothing —
    the layout stage then takes the plain path."""
    store = PipelineStore(batch_work.parent)
    batch_id = batch_work.name
    if not store.exists(f"{batch_id}/oriented/rotations.json"):
        return
    rotations = json.loads(store.read_latest(f"{batch_id}/oriented/rotations.json"))
    failures_rel = f"{batch_id}/ocr-guess/orientation.failed.json"
    failures: list[dict[str, Any]] = []
    if store.exists(failures_rel):
        # a corrupt failure log fails loudly — never silently reset the trail
        failures = json.loads(store.read_latest(failures_rel))
    for page in text_pages:
        out_rel = f"{batch_id}/ocr-guess/{Path(page).stem}.orientation.json"
        if store.exists(out_rel):
            continue  # idempotent — re-running process must not re-pay the model call
        scores = rotations.get(page, {}).get("scores", {})
        if not _ambiguous_rotations(scores):
            continue
        guess_text = ""
        txt_rel = f"{batch_id}/ocr-guess/{Path(page).stem}.txt"
        if store.exists(txt_rel):
            guess_text = store.read_latest(txt_rel)
        # The clip path (2026-08-20): when the transcription returned
        # per-line geometry, clip each in-bounds line and classify its
        # EXACT angle — ~600 tokens and ~6s per line, vs the full-page
        # location call that burned 64K reasoning tokens with zero
        # content. The full-page call remains the fallback for pages the
        # transcription gave no geometry.
        clip_report = _try_clip_report(store, batch_id, page, oriented_dir)
        try:
            report = clip_report if clip_report is not None else orientation_report_fn(oriented_dir / page, guess_text)
        # the seam is a Callable (anything may raise): the failure is recorded
        # (orientation.failed.json) and the layout falls back; the next pass
        # retries (nothing marks it done)
        # lucidlint: ignore broad-except a failed report must not kill the batch — recorded, falls back, retried
        except Exception as exc:
            _record_orientation_failure(failures, store, failures_rel, page, exc)
            continue
        _commit_orientation_report(store, out_rel, page, report)


def _try_clip_report(store: PipelineStore, batch_id: str, page: str, oriented_dir: Path) -> dict[str, Any] | None:
    """The clip path's envelope: read the transcription geometry and build
    the per-line clip-and-classify report, or return None (the full-page
    call then stands). None on ANY failure — the contract is "no clip
    report", never a crash; a missing marker or malformed geometry simply
    falls back."""
    raw_marker = f"{batch_id}/ocr-raw/{Path(page).stem}.vlm.json"
    if not store.exists(raw_marker):
        return None
    try:
        marker = json.loads(store.read_latest(raw_marker))
    except (OSError, json.JSONDecodeError):
        return None
    vlm_lines = marker.get("lines") if isinstance(marker, dict) else None
    if not vlm_lines:
        return None
    boxes: dict[int, list[float]] = {}
    for position, ln in enumerate(vlm_lines):
        if isinstance(ln, dict) and "box" in ln:
            boxes[position] = ln["box"]
    if not boxes:
        return None
    try:
        return _clip_orientation_report(oriented_dir / page, boxes)
    # the clip path's only failure types: tempfile/PIL (OSError) and the
    # classifier (VlmError); a clip failure falls back to the full-page call
    except (VlmError, OSError) as exc:
        print(f"layout: clip orientation failed for {page} — falling back: {str(exc)[:120]}", file=sys.stderr)
        return None


def _clip_orientation_report(
    image: Path,
    norm_boxes: dict[int, list[float]],
    *,
    classify: Callable[[Path], float] | None = None,
    _max_workers: int = 4,
) -> dict[str, Any]:
    """The per-line clip-and-classify report: for each in-bounds
    transcription box, clip the line from the image and ask the model the
    EXACT clockwise angle. Returns the report shape the layout consumes
    (``{"lines": [{index, box, degrees}]}``). Out-of-bounds or degenerate
    boxes are DROPPED — the model's normalized geometry sometimes exceeds
    the canvas (page-12's refusal), and such a line cannot be clipped and
    must not anchor the layout (2026-08-20)."""
    classify_fn = classify if classify is not None else line_orientation_degrees
    img = Image.open(image)
    img.load()  # PIL lazy-loads on crop; concurrent crops race the load (OSError: truncated)
    w, h = img.size

    def _classify_one(index: int, norm_box: list[float]) -> dict[str, Any] | None:
        x0, y0, x1, y1 = (
            norm_box[0] / 1000 * w,
            norm_box[1] / 1000 * h,
            norm_box[2] / 1000 * w,
            norm_box[3] / 1000 * h,
        )
        if x0 < 0 or y0 < 0 or x1 > w or y1 > h or x1 <= x0 or y1 <= y0:
            return None  # out-of-bounds or degenerate — cannot clip, must not anchor
        crop = img.crop((x0, y0, x1, y1))
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            crop.save(tmp, format="JPEG", quality=85)
            tmp_path = Path(tmp.name)
        try:
            try:
                degrees = classify_fn(tmp_path)
            except (VlmError, OSError):
                return None
        finally:
            tmp_path.unlink(missing_ok=True)
        cardinal = int(round(degrees / 90)) * 90 % 360
        return {"index": index, "box": list(norm_box), "degrees": cardinal}

    lines: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=_max_workers) as pool:
        futures = [pool.submit(_classify_one, i, b) for i, b in sorted(norm_boxes.items())]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result is not None:
                lines.append(result)
    lines.sort(key=lambda ln: ln["index"])
    # "source": "clip" tells the layout stage the per-line degrees are
    # measured from the actual text (exact angles) — trusted over the
    # rec-pass orientations (2026-08-20: a mirrored-pass artifact
    # labeled page-03's horizontal lines 90°).
    return {"orientation_hint": [], "source": "clip", "lines": lines}


def _commit_orientation_report(store: PipelineStore, out_rel: str, page: str, report: dict[str, Any]) -> None:
    """Write the report sidecar when the model reports more than one
    direction. The v3 report's multi-direction evidence lives in the
    LINES' degrees (the model locates the known text; the
    orientation_hint may be empty) — the sidecar must be written either
    way (2026-08-17: the eval caught the hints-only check dropping an
    ambiguous page back to the plain layout)."""
    hints = report.get("orientation_hint", []) if isinstance(report, dict) else []
    degrees = {int(h.get("degrees")) for h in hints if h.get("degrees") in (0, 90, 180, 270)}
    located = report.get("lines", []) if isinstance(report, dict) else []
    degrees |= {int(ln.get("degrees")) for ln in located if ln.get("degrees") in (0, 90, 180, 270)}
    if len(degrees) >= 2:
        store.write(out_rel, json.dumps(report, ensure_ascii=False) + "\n")
        print(f"layout: orientation report for {page} — {sorted(degrees)}")


def _record_orientation_failure(
    failures: list[dict[str, Any]],
    store: PipelineStore,
    failures_rel: str,
    page: str,
    exc: Exception,
) -> None:
    """Record a failed orientation report (accumulating across passes —
    each attempt appends, so repeated failures build a diagnosable trail)
    and CONTINUE: the layout stage still runs for the page via the
    single-orientation fallback (transcription boxes + the dominant
    rotation). The next process pass retries the report (no report exists,
    so nothing marks it done). 2026-08-20: the heavy location task burns
    64K reasoning tokens with no content, non-deterministically — the
    batch must stay usable through it."""
    entry = {
        "page": page,
        "at": datetime.now(UTC).isoformat(),
        "attempt": len([f for f in failures if f.get("page") == page]) + 1,
        "error": str(exc)[:1000],
    }
    failures.append(entry)
    store.write(failures_rel, json.dumps(failures, indent=1, ensure_ascii=False) + "\n")
    print(
        f"layout: orientation report FAILED for {page} (attempt {entry['attempt']}) — "
        f"continuing with the single-orientation fallback: {str(exc)[:160]}",
        file=sys.stderr,
    )


def _update_status(record: dict[str, Any], batch_id: str, status: str, registry_dir: Path) -> None:
    record["status"] = status
    store = PipelineStore(registry_dir)
    store.write(f"{batch_id}.json", json.dumps(record, indent=1, ensure_ascii=False) + "\n")


def _read_multiline(prompt: str, readline: Callable[[str], str]) -> str:
    print(prompt, end="", flush=True)
    lines: list[str] = []
    while True:
        line = readline("")
        if line.strip() == ".":
            break
        if line == "":  # EOF (Ctrl-D) — stop, don't hang (2026-08-14 review)
            break
        lines.append(line)
    return "\n".join(lines)


def review(
    batch_id: str,
    *,
    registry_dir: Path = REGISTRY_DIR,
    work_dir: Path = WORK_DIR,
    readline: Callable[[str], str] | None = None,
    write_line: Callable[[str], None] = print,
) -> None:
    """The user's confirmation gate: accept, edit, or reject each document."""
    record_path(batch_id, registry_dir)  # the batch id is a path segment — validate before any mkdir
    batch_work = work_dir / batch_id
    boundaries = _load_boundaries(batch_work, batch_id, write_line)
    if boundaries is None:
        return
    line = readline if readline is not None else lambda _prompt: sys.stdin.readline()
    _confirm_documents(boundaries, batch_work, batch_id, line, write_line, work_dir, registry_dir)

    record = load_batch(batch_id, registry_dir)
    _update_status(record, batch_id, STATUS_CONFIRMED, registry_dir)
    confirmed = [b for b in record.get("boundaries") or [] if b.get("status") == "confirmed"]
    write_line(f"\nbatch {batch_id} confirmed ({len(confirmed)} document(s))")


def _load_boundaries(batch_work: Path, batch_id: str, write_line: Callable[[str], None]) -> list[dict[str, Any]] | None:
    """The guess stage's documents, or None after reporting a photo-only
    batch — nothing to transcribe (2026-08-14 final review: `make confirm`
    must not error on it). A missing guess raises."""
    store = PipelineStore(batch_work.parent)
    if not store.exists(f"{batch_id}/ocr-guess/boundaries.json"):
        if store.exists(f"{batch_id}/classify.json"):
            classify = json.loads(store.read_latest(f"{batch_id}/classify.json"))
            if not any(entry.get("kind") == "text" for entry in classify.values()):
                write_line(f"batch {batch_id}: no text pages — nothing to confirm")
                return None
        raise PipelineError(f"no guess for batch {batch_id} — run process first")
    return json.loads(store.read_latest(f"{batch_id}/ocr-guess/boundaries.json"))


# parameter object would add a type for one use
# lucidlint: ignore long-param-list a single call site — the review gate's IO seams (line/write_line/work/registry); a
def _confirm_documents(
    boundaries: list[dict[str, Any]],
    batch_work: Path,
    batch_id: str,
    line: Callable[[str], str],
    write_line: Callable[[str], None],
    work_dir: Path,
    registry_dir: Path,
) -> None:
    """The user's accept/edit/reject gate per document; the accepted text
    lands in work/<batch>/ocr-confirmed/."""
    store = PipelineStore(work_dir)
    confirmed_dir = batch_work / "ocr-confirmed"
    confirmed_dir.mkdir(parents=True, exist_ok=True)
    for index, document in enumerate(boundaries, start=1):
        text_pages = [
            p for p in document["pages"] if store.exists(f"{batch_id}/ocr-guess/{Path(p).with_suffix('.txt')}")
        ]
        if not text_pages:
            # a photo-only item — nothing to transcribe; its people/places
            # identification is a separate flow (user, 2026-08-17)
            write_line(f"=== Document {index} — {len(document['pages'])} photo page(s), no text to check")
            continue
        write_line(f"\n=== Document {index} — pages {', '.join(document['pages'])} ===")
        if document.get("greeting"):
            write_line(f"greeting: {document['greeting']}")
        for page in text_pages:
            txt_rel = f"{batch_id}/ocr-guess/{Path(page).with_suffix('.txt')}"
            if store.exists(txt_rel):
                write_line(f"--- {page} ---\n{store.read_latest(txt_rel)}")
        answer = line("accept (Enter) / edit (e) / reject (r): ").strip().lower()
        if answer == "r":
            record_confirmation(batch_id, index, document, None, work_dir=work_dir, registry_dir=registry_dir)
            write_line(f"document {index} rejected")
            continue
        text = "\n".join(store.read_latest(f"{batch_id}/ocr-guess/{Path(p).with_suffix('.txt')}") for p in text_pages)
        if answer == "e":
            text = _read_multiline("paste the corrected text, '.' alone ends:\n", line)
        record_confirmation(batch_id, index, document, text, work_dir=work_dir, registry_dir=registry_dir)
        write_line(f"document {index} confirmed -> {confirmed_dir / f'doc-{index:02d}.txt'}")


def cmd_guess(batch_id: str, pages: list[str], work_dir: Path, registry_dir: Path) -> int:
    """Surgical recovery (2026-08-20): re-run the VLM guess for specific
    pages, then regenerate boundaries from the full page set. The guess
    stage previously could only run as part of the whole ``process`` chain —
    fixing one page re-paid model calls for every page. ``pages`` limits
    which pages get re-transcribed; the boundaries regen still sees the
    full set (the grouping scorer needs the whole sequence)."""
    batch_work = work_dir / batch_id
    oriented_dir = batch_work / "oriented"
    raw_dir = batch_work / "ocr-raw"
    classify_path = batch_work / "classify.json"
    record = load_batch(batch_id, registry_dir)

    if not classify_path.exists():
        print(f"guess: no classify.json for {batch_id} — run `pipeline process` once first", file=sys.stderr)
        return 1
    classify = json.loads(PipelineStore(work_dir).read_latest(f"{batch_id}/classify.json"))
    text_pages: list[str] = [name for name, entry in classify.items() if entry.get("kind") == "text"]
    if pages:
        requested = {p if p.endswith(".jpg") else p + ".jpg" for p in pages}
        unknown = requested - set(text_pages)
        if unknown:
            print(f"guess: not text pages: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        cursive = [p for p in requested if classify.get(p, {}).get("route") == "cursive"]
        if not cursive:
            print("guess: none of the requested pages are routed cursive — nothing to re-transcribe", file=sys.stderr)
            return 2
    else:
        cursive = [name for name in text_pages if classify.get(name, {}).get("route") == "cursive"]

    people, places = _standing_knowledge()
    label = record.get("label")
    htr_pages_vlm(
        [(name, oriented_dir / name) for name in cursive],
        raw_dir,
        people=people,
        places=places,
        label=label,
    )

    _regen_boundaries(batch_id, record, classify, text_pages, work_dir, registry_dir)
    print(f"guess: {len(cursive)} page(s) re-transcribed, boundaries regenerated")
    return 0


# a single call site — the surgical-recovery regen; a parameter object would be ceremony
# lucidlint: ignore long-param-list the stage paths and DI seams are the caller's locals
def _regen_boundaries(
    batch_id: str,
    record: dict[str, Any],
    classify: dict[str, Any],
    text_pages: list[str],
    work_dir: Path,
    registry_dir: Path,
) -> None:
    """Regenerate boundaries from the full set — the grouping scorer needs
    the whole sequence (photos included), the classify kinds, the image
    sizes, and the texts. Same call pattern as _run_guess (2026-08-20)."""
    raw_dir = work_dir / batch_id / "ocr-raw"
    guess_dir = work_dir / batch_id / "ocr-guess"
    store = PipelineStore(work_dir)
    reg_store = PipelineStore(registry_dir)
    folder = Path(str(record.get("path", "")))
    dims: dict[str, tuple[int, int]] = {}
    for rel in sorted(record.get("pages", {})):
        with Image.open(folder / rel) as im:
            dims[rel] = im.size
    texts: dict[str, str | None] = {
        name: (raw_dir / Path(name).with_suffix(".txt")).read_text(encoding="utf-8") for name in text_pages
    }
    boundaries = score_boundaries(
        sorted(record.get("pages", {})),
        {page: str(entry.get("kind", "text")) for page, entry in classify.items()},
        dims,
        texts,
        {},
    )
    boundaries_path = guess_dir / "boundaries.json"
    boundaries_path.parent.mkdir(parents=True, exist_ok=True)
    inputs = {
        name: text_sha256((raw_dir / Path(name).with_suffix(".txt")).read_text(encoding="utf-8")) for name in text_pages
    }
    store.write(f"{batch_id}/ocr-guess/boundaries.json", json.dumps(boundaries, indent=1, ensure_ascii=False) + "\n")
    store.write(f"{batch_id}/ocr-guess/boundaries.inputs.json", json.dumps(inputs, ensure_ascii=False))
    record["boundaries"] = boundaries
    reg_store.write(f"{batch_id}.json", json.dumps(record, indent=1, ensure_ascii=False) + "\n")


def cmd_layout(batch_id: str, pages: list[str], work_dir: Path, registry_dir: Path) -> int:
    """Surgical recovery (2026-08-20): run the layout stage for specific
    pages only. The layout stage (PaddleOCR in the .venv-htr venv) is the
    slowest stage — re-running it for the whole batch to fix one page is
    wasteful. Delegates to the layout stage's own page filter and its
    fail-loud missing-input check."""
    try:
        layout_stage_run(batch_id, work_dir, pages or None)
    except Exception as exc:  # lucidlint: ignore broad-except the subprocess surfaces its exit as CalledProcessError
        print(f"layout: stage failed: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline", description="The ingest chain per batch")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("process", help="orient + raw OCR + model guess + boundaries")
    p.add_argument("batch_id")
    p.set_defaults(fn=process)
    p = sub.add_parser("guess", help="surgical recovery: re-transcribe specific pages, regen boundaries")
    p.add_argument("batch_id")
    p.add_argument("pages", nargs="*", help="page names (e.g. page-02); empty = all cursive pages")
    p.set_defaults(fn=cmd_guess)
    p = sub.add_parser("layout", help="surgical recovery: layout specific pages only")
    p.add_argument("batch_id")
    p.add_argument("pages", nargs="*", help="page names (e.g. page-02); empty = all pages")
    p.set_defaults(fn=cmd_layout)
    p = sub.add_parser("review", help="user confirmation gate for the guessed text")
    p.add_argument("batch_id")
    p.set_defaults(fn=review)
    args = parser.parse_args(argv)
    try:
        if args.command in ("guess", "layout"):
            args.fn(args.batch_id, args.pages, WORK_DIR, REGISTRY_DIR)
        else:
            args.fn(args.batch_id)
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
