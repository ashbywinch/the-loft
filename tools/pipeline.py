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
import contextlib
import json
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.ai_client import AIClient, AIClientError
from tools.atomic import atomic_write
from tools.classify import route, run_classify
from tools.htr import htr_pages, htr_pages_vlm
from tools.loft_paths import ARCHIVE_DIR, REGISTRY_DIR, WORK_DIR
from tools.ocr import orient_pages
from tools.registry import RegistryError as PipelineError
from tools.registry import load_batch, record_path
from tools.sync import record_confirmation

PAGE_LIMIT = 30  # one guess call per batch; beyond this the context is too big — chunking is future work
GUESS_PAGE_CHUNK = 5  # the guess re-emits each page's corrected text; the OUTPUT size binds — 5 pages of
# verbatim text + JSON fits the client's max_tokens (2026-08-14: a 12-page pile's JSON response truncated)

STATUS_PROCESSING = "importing"
STATUS_REVIEW = "review"
STATUS_CONFIRMED = "confirmed"


def _standing_knowledge(archive_dir: Path = ARCHIVE_DIR) -> tuple[list[str], list[str]]:
    """The archive's people and places names — the context the guess works from."""
    people: list[str] = []
    places: list[str] = []
    people_path = archive_dir / "people.json"
    places_path = archive_dir / "places.json"
    if people_path.exists():
        for record in json.loads(people_path.read_text(encoding="utf-8")).get("people", []):
            name = str(record.get("name", "")).strip()
            if name:
                people.append(name)
            people += [str(alias) for alias in record.get("aliases", []) if str(alias).strip()]
    if places_path.exists():
        for record in json.loads(places_path.read_text(encoding="utf-8")).get("places", []):
            name = str(record.get("name", "")).strip()
            if name:
                places.append(name)
    return sorted(set(people)), sorted(set(places))


def group_documents(flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group per-page boundary flags into documents.

    A page with ``starts_document`` opens a letter (greeting); one with
    ``ends_document`` closes it (sign-off). A page with neither belongs to
    the current document; a page with both is a single-page document. An
    unclosed run at the end stays one open document (the model may have
    missed the sign-off — the reviewer sees it).
    """
    documents: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for flag in flags:
        if current is None or flag.get("starts_document"):
            current = {
                "pages": [],
                "greeting": flag.get("greeting") if flag.get("starts_document") else None,
                "signoff": None,
            }
            documents.append(current)
        current["pages"].append(str(flag.get("page", "")))
        if flag.get("ends_document"):
            current["signoff"] = flag.get("signoff")
            current = None
    return documents


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


def process(
    batch_id: str,
    *,
    registry_dir: Path = REGISTRY_DIR,
    work_dir: Path = WORK_DIR,
    archive_dir: Path = ARCHIVE_DIR,
    client: Callable[[str, str], str] | None = None,
) -> None:
    """Classify → orient (text pages) → route → HTR/tesseract → guess → review."""
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
    if boundaries_path.exists():
        print("guess already present — reusing")
    else:
        _run_guess(text_pages, raw_dir, guess_dir, boundaries_path, record, batch_id, registry_dir, archive_dir, client)

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
    if classify_path.exists():
        print("classification already present — reusing")
    else:
        run_classify(batch_id, registry_dir=registry_dir, work_dir=work_dir)
        print(f"classified {len(pages)} page(s) -> {classify_path}")
    classify = json.loads(classify_path.read_text(encoding="utf-8"))
    text_pages = [name for name, entry in classify.items() if entry.get("kind") == "text"]
    image_pages = [name for name, entry in classify.items() if entry.get("kind") != "text"]
    if image_pages:
        print(f"{len(image_pages)} page(s) are images — no transcription")
    return classify, text_pages, image_pages


def _orient_and_ocr(text_pages: list[str], folder: Path, oriented_dir: Path, raw_dir: Path, batch_work: Path) -> None:
    """Orient the text pages and run tesseract raw OCR (rotations.json is
    the completion marker — piles may hold PNG/TIFF pages, not only JPEGs)."""
    if not (oriented_dir / "rotations.json").exists():
        oriented = orient_pages([folder / name for name in text_pages], oriented_dir, root=folder)
        raw_dir.mkdir(parents=True, exist_ok=True)
        for page in oriented:
            atomic_write(raw_dir / Path(str(page["name"])).with_suffix(".txt"), str(page["text"]))
        atomic_write(
            oriented_dir / "rotations.json",
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
    rotations = json.loads((oriented_dir / "rotations.json").read_text(encoding="utf-8"))
    apply_routes(classify, rotations)
    atomic_write(classify_path, json.dumps(classify, indent=1, ensure_ascii=False) + "\n")
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
    client: Callable[[str, str], str] | None,
) -> None:
    """The model guess on the TEXT pages only (chunked past PAGE_LIMIT — a
    multi-page document spanning a chunk boundary is split, a noted
    limitation; postcards and letters within a chunk group correctly)."""
    raw_texts = [(name, (raw_dir / Path(name).with_suffix(".txt")).read_text(encoding="utf-8")) for name in text_pages]
    label = str(record.get("label", ""))
    people, places = _standing_knowledge(archive_dir)
    chat = client if client is not None else AIClient(max_tokens=12000).chat
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
    # (2026-08-15 review: the drop guarded only the writes, and
    # group_documents still received every flag — the review gate then
    # crashed on the missing .txt or read outside guess_dir via ../)
    known_flags = [flag for flag in flags if str(flag["page"]) in text_pages]
    for flag in flags:
        if str(flag["page"]) not in text_pages:
            print(f"guess returned an unknown page {flag['page']!r} — dropped")
    for flag in known_flags:
        atomic_write(guess_dir / Path(str(flag["page"])).with_suffix(".txt"), str(flag["text"]))
    boundaries = group_documents(known_flags)
    atomic_write(boundaries_path, json.dumps(boundaries, indent=1, ensure_ascii=False) + "\n")
    # seed the registry record with the full boundaries so the review
    # surface's batch list shows the correct pending count (the registry
    # is the status' home; the guess stage's boundaries.json is the
    # pipeline's output, never the registry — 2026-08-15)
    record["boundaries"] = boundaries
    atomic_write(record_path(batch_id, registry_dir), json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    print(f"model guess: {len(flags)} page(s), {len(boundaries)} document(s) -> {guess_dir}")


def _update_status(record: dict[str, Any], batch_id: str, status: str, registry_dir: Path) -> None:
    record["status"] = status
    atomic_write(record_path(batch_id, registry_dir), json.dumps(record, indent=1, ensure_ascii=False) + "\n")


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
    guess_dir = batch_work / "ocr-guess"
    boundaries_path = guess_dir / "boundaries.json"
    if not boundaries_path.exists():
        classify_path = batch_work / "classify.json"
        if classify_path.exists():
            classify = json.loads(classify_path.read_text(encoding="utf-8"))
            if not any(entry.get("kind") == "text" for entry in classify.values()):
                write_line(f"batch {batch_id}: no text pages — nothing to confirm")
                return None
        raise PipelineError(f"no guess for batch {batch_id} — run process first")
    return json.loads(boundaries_path.read_text(encoding="utf-8"))


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
    guess_dir = batch_work / "ocr-guess"
    confirmed_dir = batch_work / "ocr-confirmed"
    confirmed_dir.mkdir(parents=True, exist_ok=True)
    for index, document in enumerate(boundaries, start=1):
        write_line(f"\n=== Document {index} — pages {', '.join(document['pages'])} ===")
        if document.get("greeting"):
            write_line(f"greeting: {document['greeting']}")
        for page in document["pages"]:
            text_path = guess_dir / Path(page).with_suffix(".txt")
            if text_path.exists():
                write_line(f"--- {page} ---\n{text_path.read_text(encoding='utf-8')}")
        answer = line("accept (Enter) / edit (e) / reject (r): ").strip().lower()
        if answer == "r":
            record_confirmation(batch_id, index, document, None, work_dir=work_dir, registry_dir=registry_dir)
            write_line(f"document {index} rejected")
            continue
        text = "\n".join(
            (guess_dir / Path(p).with_suffix(".txt")).read_text(encoding="utf-8") for p in document["pages"]
        )
        if answer == "e":
            text = _read_multiline("paste the corrected text, '.' alone ends:\n", line)
        record_confirmation(batch_id, index, document, text, work_dir=work_dir, registry_dir=registry_dir)
        write_line(f"document {index} confirmed -> {confirmed_dir / f'doc-{index:02d}.txt'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline", description="The ingest chain per batch")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("process", help="orient + raw OCR + model guess + boundaries")
    p.add_argument("batch_id")
    p.set_defaults(fn=process)
    p = sub.add_parser("review", help="user confirmation gate for the guessed text")
    p.add_argument("batch_id")
    p.set_defaults(fn=review)

    args = parser.parse_args(argv)
    try:
        args.fn(args.batch_id)
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
