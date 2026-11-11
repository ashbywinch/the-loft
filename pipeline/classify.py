"""Content routing for batches: the PAGE CATEGORY, from the vision model
(TECHSPEC §16.14; docs/PLAN/page-categories.md).

One small call per raw page names what it is — a photograph, printed writing,
handwriting, a postcard face, a form, or a drawing — and, for the two page
shapes that may be either, how its writing was made (printed or handwritten).
The reader that sees the page names it (user, 2026-10-26: the local CLIP
classifier and its torch stack are gone).

The category decides the read (`read_route`): photographs and drawings are not
read; printed pages take one direct transcription; handwriting and handwritten
postcard faces take the row pipeline; a form is read as structure. The old
tesseract strong-word density route is gone: the category answers "printed or
handwriting" before any OCR runs.

Usage:
    python -m pipeline.classify <batch-id>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Collection
from pathlib import Path
from typing import Any

from pipeline.model.vlm import VlmError, extract_json, transcribe_image_vlm
from pipeline.page_classification import PageClassification
from pipeline.registry import RegistryError, load_batch
from pipeline.store import PipelineStore
from tools.loft_paths import LoftPaths
from tools.store import DiskStore  # noqa: F401 — the architecture test's store-layer marker


def category_of(entry: dict[str, Any]) -> str:
    """A classify record's category, old spellings included: a record written
    before the 2026-11-02 vocabulary says "text"/"photo", and is read as the
    category it names, never rewritten."""
    kind = str(entry.get("kind", "")).strip().lower()
    return LEGACY_KINDS.get(kind, kind)


def read_route(entry: dict[str, Any]) -> str:
    """How a page is read, by its category — the one routing rule:

    - a photograph or a drawing: nothing to transcribe;
    - printed writing: one direct VLM read;
    - handwriting: the row pipeline (auto rows, then the human row check);
    - a postcard face: printed faces take the direct read; handwritten ones the
      row pipeline (their two orientations are the reviewer's lines' problem
      when the auto detection is bad);
    - a form: a structured read (labels and values), whatever the medium — a
      form read as prose loses its meaning.
    A page whose category was never recorded (the legacy "text") is read as
    handwriting, the safe route."""
    kind = category_of(entry)
    if kind == "printed":
        return "direct"
    if kind == "postcard_face":
        return "direct" if entry.get("medium") == "printed" else "rows"
    if kind == "form":
        return "structured"
    if kind == "handwriting":
        return "rows"
    return "none"


def classify_pages(
    pages: list[Path],
    classifier: Callable[[Path], PageClassification],
    root: Path,
) -> dict[str, PageClassification]:
    """One classification per page keyed by its path RELATIVE to the pile root
    (the registry's key space — basenames collide for piles with subfolders)."""
    return {str(page.relative_to(root)): classifier(page) for page in pages}


# the PAGE CATEGORIES (docs/PLAN/page-categories.md): what one scan is. A
# document type (letter, postcard, form) is derived from the pages a group holds.
# printing is writing too: the hand script is its own category, and printed
# text its own; a postcard face or a form is a page SHAPE whose writing may be
# either, so those two carry the medium
CONTENT_KINDS = ("photograph", "printed", "handwriting", "postcard_face", "form", "drawing")
MEDIUMS = ("printed", "handwritten")
# the categories that carry writing to read; the rest carry none (a photograph's
# image is the evidence; a drawing's labels are not a transcription)
TEXT_KINDS = ("printed", "handwriting", "postcard_face", "form")
# what the categories were called before 2026-11-02 — the classify records on
# disk carry the old names, and a record is never rewritten to a new spelling
LEGACY_KINDS = {"text": "handwriting", "photo": "photograph"}

# how a page's writing is read, by its category (docs/PLAN/page-categories.md):
# no text / one direct VLM read / the row pipeline (auto rows + the human row
# check) / a structured read (labels and values)
READ_ROUTES = ("none", "direct", "rows", "structured")
# the two page SHAPES whose writing may be printed or handwritten
MEDIUM_SHAPES = ("postcard_face", "form")

PAGE_KIND_PROMPT = (
    "What does this scanned page SHOW? Reply with JSON only: "
    '{"kind": "photograph"|"printed"|"handwriting"|"postcard_face"|"form"|"drawing", '
    '"confidence": <0.0-1.0>, "medium": "printed"|"handwritten"|null}. '
    '"photograph": a picture of people, places or things — a snapshot, however it was scanned; '
    '"printed": writing made by type, print or typescript — a typed letter, a newspaper, a caption; '
    '"handwriting": writing made by hand — pen or pencil, however neat; '
    '"postcard_face": the picture side of a postcard, with or without a printed caption or a handwritten message; '
    '"form": a form — printed labels and the entries filled against them; '
    '"drawing": an illustration or sketch, not a photograph. '
    'For "postcard_face" and "form", "medium" names the writing on the page: '
    '"printed" for type or print, "handwritten" for pen or pencil, null when it carries none. '
    "It is null for every other kind. "
    'Judge the page\'s content, never its paper: a scanned printed letter is "printed" '
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
        medium = None if raw.get("medium") is None else str(raw["medium"]).strip().lower()
    except (KeyError, TypeError, ValueError) as e:
        raise VlmError(f"unusable classification: {answer.answer[:120]!r}") from e
    if kind not in CONTENT_KINDS or not 0.0 <= confidence <= 1.0:
        raise VlmError(f"unusable classification: {answer.answer[:120]!r}")
    if kind in MEDIUM_SHAPES and medium is not None and medium not in MEDIUMS:
        raise VlmError(f"unusable medium: {answer.answer[:120]!r}")
    return PageClassification.from_confidences({kind: confidence}, medium)


def run_classify(
    batch_id: str,
    *,
    registry_dir: Path = LoftPaths.REGISTRY_DIR,
    work_dir: Path = LoftPaths.WORK_DIR,
    classifier: Callable[[Path], PageClassification] | None = None,
    reclassify: Collection[str] = (),
) -> Path:
    """Classify a batch's RAW pages (before orientation — photos need neither).

    Idempotent: a page with a classification is left alone, and the call is a
    no-op when every page has one. ``reclassify`` names pages whose record is
    stale (a classification from before the category vocabulary, which cannot
    route a read); those are classified again and the file is rewritten with
    the new answers merged in."""
    record = load_batch(batch_id, registry_dir)
    folder = record.path
    pages = sorted((folder / rel) for rel in record.pages)
    if not pages:
        raise RegistryError(f"batch {batch_id} has no registered pages")
    classify_path = work_dir / batch_id / "classify.json"
    store = PipelineStore(work_dir)
    store_path = str(classify_path.relative_to(work_dir))
    existing: dict[str, Any] = json.loads(store.read_latest(store_path)) if store.exists(store_path) else {}
    todo = [
        page
        for page in pages
        if str(page.relative_to(folder)) not in existing or str(page.relative_to(folder)) in set(reclassify)
    ]
    if not todo:
        return classify_path
    classify = classifier if classifier is not None else classify_page
    results = classify_pages(todo, classify, folder)
    merged = {**existing, **{name: result.to_dict() for name, result in results.items()}}
    classify_path.parent.mkdir(parents=True, exist_ok=True)
    store.write(store_path, json.dumps(merged, indent=1, ensure_ascii=False) + "\n")
    return classify_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="classify", description="Content routing for a batch")
    parser.add_argument("batch_id")
    args = parser.parse_args(argv)
    try:
        classify_path = run_classify(args.batch_id)
        store = PipelineStore(LoftPaths.WORK_DIR)
        results = json.loads(store.read_latest(str(classify_path.relative_to(LoftPaths.WORK_DIR))))
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
