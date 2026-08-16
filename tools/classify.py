"""Content routing for batches: photo/drawing vs text, and within text,
cursive vs print (TECH-SPEC §16.14; MULTI-DOC-IMPORT-PRD.md R11–R12).

A local zero-shot image classifier (open_clip, MobileCLIP — CPU) decides
text vs photo vs drawing: image-content discrimination is CLIP's strength.
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

import open_clip
import torch
from PIL import Image

from tools.atomic import atomic_write
from tools.loft_paths import REGISTRY_DIR, WORK_DIR
from tools.registry import RegistryError, load_batch

# CLIP zero-shot labels — image content only; print-vs-cursive is the
# density signal's job, not CLIP's
CONTENT_PROMPTS = {
    "text": "a page of written text",
    "photo": "a photograph",
    "drawing": "a drawing or illustration",
}
DENSITY_THRESHOLD = 200  # strong words per page: cursive measured 7–58, printed reference 1185


def route(density: int, threshold: int = DENSITY_THRESHOLD) -> str:
    """Print OCRs well under tesseract, cursive does not — the density decides."""
    return "print" if density >= threshold else "cursive"


def _load_clip() -> tuple[Any, Any, Any]:
    """open_clip's stubs mis-type create_model_and_transforms, and its third
    return is NOT the tokenizer for MobileCLIP (a second Compose); the
    tokenizer comes from get_tokenizer. The boundary is treated as untyped —
    the live acceptance test exercises it."""
    model, preprocess, _ = open_clip.create_model_and_transforms("MobileCLIP-S2", pretrained="datacompdr")
    tokenizer = open_clip.get_tokenizer("MobileCLIP-S2")
    return model, preprocess, tokenizer


def classify_pages(
    pages: list[Path],
    classifier: Callable[[Path], tuple[str, dict[str, float]]],
    root: Path,
) -> dict[str, dict[str, Any]]:
    """One dict per page keyed by its path RELATIVE to the pile root (the
    registry's key space — basenames collide for piles with subfolders)."""
    return {
        str(page.relative_to(root)): {"kind": kind, "confidences": confidences}
        for page in pages
        for kind, confidences in [classifier(page)]
    }


def zero_shot_classifier() -> Callable[[Path], tuple[str, dict[str, float]]]:
    """The CLIP zero-shot classifier bound to CONTENT_PROMPTS (local, CPU)."""
    model, preprocess, tokenizer = _load_clip()
    model.eval()
    labels = sorted(CONTENT_PROMPTS)
    texts = tokenizer([CONTENT_PROMPTS[label] for label in labels])
    with torch.no_grad():
        text_features = model.encode_text(texts)
        text_features /= text_features.norm(dim=-1, keepdim=True)

    def classify(image_path: Path) -> tuple[str, dict[str, float]]:
        with torch.no_grad():
            image = preprocess(Image.open(image_path).convert("RGB")).unsqueeze(0)
            image_features = model.encode_image(image)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            probs = (image_features @ text_features.T).softmax(dim=-1)[0]
        confidences = {label: float(probs[i]) for i, label in enumerate(labels)}
        kind = max(confidences.items(), key=lambda kv: kv[1])[0]
        return kind, confidences

    return classify


def run_classify(
    batch_id: str,
    *,
    registry_dir: Path = REGISTRY_DIR,
    work_dir: Path = WORK_DIR,
    classifier: Callable[[Path], tuple[str, dict[str, float]]] | None = None,
) -> Path:
    """Classify a batch's RAW pages (before orientation — photos need neither)."""
    record = load_batch(batch_id, registry_dir)
    folder = Path(str(record["path"]))
    pages = sorted((folder / rel) for rel in record.get("pages", {}))
    if not pages:
        raise RegistryError(f"batch {batch_id} has no registered pages")
    classify_path = work_dir / batch_id / "classify.json"
    if classify_path.exists():
        return classify_path  # idempotent
    classify = classifier if classifier is not None else zero_shot_classifier()
    results = classify_pages(pages, classify, folder)
    classify_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(classify_path, json.dumps(results, indent=1, ensure_ascii=False) + "\n")
    return classify_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="classify", description="Content routing for a batch")
    parser.add_argument("batch_id")
    args = parser.parse_args(argv)
    try:
        classify_path = run_classify(args.batch_id)
        results = json.loads(classify_path.read_text(encoding="utf-8"))
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
