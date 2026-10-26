"""Content routing for batches: photo/drawing vs text, and within text,
cursive vs print (TECHSPEC §16.14; MULTI-DOC-IMPORT-PRD.md R11–R12).

A vision-model call decides text vs photo vs drawing: the reader that sees
the page also names its kind, one small call per raw page (user,
2026-10-26: the local CLIP classifier and its torch stack are gone).
Within text pages, the tesseract strong-word density measured at
orientation decides cursive vs print — print OCRs well under tesseract,
cursive does not (real data: cursive pages scored 7–58 strong words, the
printed reference 1185). Photos and drawings are flagged as image items
and never transcribed.

Usage:
    python tools/classify.py <batch-id>          # classify the raw pages
    python tools/classify.py <batch-id> --route  # + the density routing
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pipeline.model.vlm import VlmError, extract_json, transcribe_image_vlm
from pipeline.page_classification import PageClassification
from pipeline.registry import RegistryError, load_batch
from pipeline.store import PipelineStore
from tools.loft_paths import REGISTRY_DIR, WORK_DIR
from tools.store import DiskStore  # noqa: F401 — the architecture test's store-layer marker

DENSITY_THRESHOLD = 200  # strong words per page: cursive measured 7–58, printed reference 1185


def route(density: int, threshold: int = DENSITY_THRESHOLD) -> str:
    """Print OCRs well under tesseract, cursive does not — the density decides."""
    return "print" if density >= threshold else "cursive"


def classify_pages(
    pages: list[Path],
    classifier: Callable[[Path], PageClassification],
    root: Path,
) -> dict[str, PageClassification]:
    """One classification per page keyed by its path RELATIVE to the pile root
    (the registry's key space — basenames collide for piles with subfolders)."""
    return {str(page.relative_to(root)): classifier(page) for page in pages}


CONTENT_KINDS = ("text", "photo", "drawing")

PAGE_KIND_PROMPT = (
    "What does this scanned page SHOW? Reply with JSON only: "
    '{"kind": "text"|"photo"|"drawing", "confidence": <0.0-1.0>}. '
    '"text": writing to be read — a letter, a form, a list, a transcript; '
    '"photo": a picture of people, places or things — a snapshot, a postcard, '
    'however it was scanned; "drawing": an illustration or sketch. '
    'Judge the page\'s content, never its paper: a scanned letter is "text" '
    "even though the scan is photographic. The confidence is your own."
)


def classify_page(
    image: Path, *, max_tokens: int = 1000, timeout: float = 120.0, urlopen: Any = None
) -> PageClassification:
    """The page's content kind, named by the vision model that reads the
    image itself — one small call per raw page, thinking off, so the answer
    is a reading and not a deliberation."""
    answer = transcribe_image_vlm(
        image,
        system="You classify scanned pages.",
        user_text=PAGE_KIND_PROMPT,
        max_tokens=max_tokens,
        timeout=timeout,
        urlopen=urlopen,
    )
    raw = extract_json(answer.answer)
    if not isinstance(raw, dict):
        raise VlmError(f"no classification in the model's answer: {answer.answer[:120]!r}")
    try:
        kind = str(raw["kind"]).strip().lower()
        confidence = float(raw["confidence"])
    except (KeyError, TypeError, ValueError) as e:
        raise VlmError(f"unusable classification: {answer.answer[:120]!r}") from e
    if kind not in CONTENT_KINDS or not 0.0 <= confidence <= 1.0:
        raise VlmError(f"unusable classification: {answer.answer[:120]!r}")
    return PageClassification.from_confidences({kind: confidence})


def run_classify(
    batch_id: str,
    *,
    registry_dir: Path = REGISTRY_DIR,
    work_dir: Path = WORK_DIR,
    classifier: Callable[[Path], PageClassification] | None = None,
) -> Path:
    """Classify a batch's RAW pages (before orientation — photos need neither)."""
    record = load_batch(batch_id, registry_dir)
    folder = record.path
    pages = sorted((folder / rel) for rel in record.pages)
    if not pages:
        raise RegistryError(f"batch {batch_id} has no registered pages")
    classify_path = work_dir / batch_id / "classify.json"
    store = PipelineStore(work_dir)
    store_path = str(classify_path.relative_to(work_dir))
    if store.exists(store_path):
        return classify_path  # idempotent
    classify = classifier if classifier is not None else classify_page
    results = classify_pages(pages, classify, folder)
    classify_path.parent.mkdir(parents=True, exist_ok=True)
    wire = {name: record.to_dict() for name, record in results.items()}
    store.write(store_path, json.dumps(wire, indent=1, ensure_ascii=False) + "\n")
    return classify_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="classify", description="Content routing for a batch")
    parser.add_argument("batch_id")
    args = parser.parse_args(argv)
    try:
        classify_path = run_classify(args.batch_id)
        results = json.loads(PipelineStore(WORK_DIR).read_latest(str(classify_path.relative_to(WORK_DIR))))
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    kinds: dict[str, int] = {}
    for page in results.values():
        kinds[str(page["kind"])] = kinds.get(str(page["kind"]), 0) + 1
    print(f"classified {len(results)} page(s): {kinds}")
    print(f"-> {classify_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
