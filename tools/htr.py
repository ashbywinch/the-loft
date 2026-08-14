"""The HTR stage — cursive pages, read by the field's tooling (TECH-SPEC
§16.14; MULTI-DOC-IMPORT-PRD.md R10–R12).

Line detection is the prior art, not hand-rolled: kraken 7 + the orli
baseline model (trained on ~200k pages across writing systems; handles the
layout cases — corner text boxes, marginal notes, filled-in forms) runs as
a subprocess in the .venv-htr (Python 3.13) venv and emits line baselines
as JSON. Recognition is TrOCR-small-handwritten (transformers, handwriting-
trained on IAM) — the PP-OCRv6 recognition models kraken 7.1 ships for
are currently unloadable (their model class is registered by no installed
package, 2026-08-14), so recognition uses the transformers stack in the
main venv.

The stage: segment (kraken+orli) -> crop lines from the baselines -> TrOCR
per line -> page text, written to ocr-raw/<stem>.txt, replacing tesseract
for cursive pages.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.atomic import atomic_write

KRAKEN = str(Path(__file__).resolve().parent.parent / ".venv-htr" / "bin" / "kraken")
ORLI_MODEL = Path.home() / ".local/share/htrmopo/c690cc12-0cf5-59dd-af71-69cdef2392b2/orli_base.safetensors"
TROCR_MODEL = "microsoft/trocr-small-handwritten"


class HtrError(RuntimeError):
    """An HTR stage failed; the message is the plain-language line."""


def segment_page(image: Path, orli: Path = ORLI_MODEL, kraken: str = KRAKEN) -> list[dict[str, Any]]:
    """Run kraken+orli on one page; returns the JSON line records (baselines),
    coordinates in the ORIGINAL image space (the page is downscaled to orli's
    trained input range for speed, and the baselines are remapped back)."""
    import tempfile

    from PIL import Image

    img = Image.open(image).convert("RGB")
    target_width = 1920.0  # orli's trained width; the quality-limiting dimension for horizontal text
    scale = 1.0
    if img.width > target_width:
        scale = target_width / img.width
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    scaled_path: Path | None = None
    try:
        if scale < 1.0:
            fd, tmp_name = tempfile.mkstemp(suffix=".jpg")
            _ = tmp_name  # PIL opens the path itself
            scaled_path = Path(tmp_name)
            img.save(scaled_path, quality=95)
            run_image = scaled_path
        else:
            run_image = image
        result = subprocess.run(
            [kraken, "--precision", "bf16-mixed", "-i", str(run_image), "-", "segment", "-bl", "-i", str(orli)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        if scaled_path is not None:
            scaled_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise HtrError(f"kraken segment failed on {image.name}: {(result.stderr or result.stdout)[:300]}")
    stdout = result.stdout
    start = stdout.find("{")
    if start < 0:
        raise HtrError(f"kraken segment returned no JSON for {image.name}: {stdout[:200]!r}")
    try:
        payload, _ = json.JSONDecoder().raw_decode(stdout[start:])  # trailing progress text allowed
    except json.JSONDecodeError as exc:
        raise HtrError(
            f"kraken segment returned malformed JSON for {image.name}: {stdout[start : start + 200]!r}"
        ) from exc
    lines = payload.get("lines", [])
    if scale < 1.0:
        for line in lines:
            line["baseline"] = [[x / scale, y / scale] for x, y in line.get("baseline", [])]
    return lines


def line_boxes(lines: list[dict[str, Any]]) -> list[tuple[int, int, int, int]]:
    """(x0, y0, x1, y1) per line in reading order.

    Each line's height is its own baseline's gap to the NEXT baseline below
    (clamped) — a global median gap fails on mixed pages, where a dense
    printed region (a callout box) drags every crop to a sliver (2026-08-14:
    page-03's crops came out 17px tall and nothing could read them).
    """
    if not lines:
        return []
    entries = []
    for line in lines:
        pts = line.get("baseline") or []
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        entries.append({"x0": min(xs), "x1": max(xs), "y": sum(ys) / len(ys)})
    entries.sort(key=lambda e: e["y"])
    boxes: list[tuple[int, int, int, int]] = []
    for i, entry in enumerate(entries):
        next_y = entries[i + 1]["y"] if i + 1 < len(entries) else entry["y"] + 60
        gap = max(20.0, min(200.0, next_y - entry["y"]))
        top = entry["y"] - 0.6 * gap
        bottom = entry["y"] + 0.4 * gap
        boxes.append((int(entry["x0"]), int(top), int(entry["x1"]), int(bottom)))
    return boxes


def crop_lines(image: Path, boxes: list[tuple[int, int, int, int]]) -> list[Any]:
    """The line images (PIL), padded 8px each side, in reading order."""
    from PIL import Image

    img = Image.open(image).convert("RGB")
    crops: list[Any] = []
    for x0, y0, x1, y1 in boxes:
        left, top = max(0, x0 - 8), max(0, y0 - 8)
        right, bottom = min(img.width, x1 + 8), min(img.height, y1 + 8)
        if right > left and bottom > top:
            crops.append(img.crop((left, top, right, bottom)))
    return crops


def transcribe_lines(crops: list[Any], processor: Any, model: Any) -> str:
    """TrOCR per line; the page text = the lines joined in reading order."""
    texts: list[str] = []
    for crop in crops:
        pixel_values = processor(crop, return_tensors="pt").pixel_values
        generated = model.generate(pixel_values)
        texts.append(processor.batch_decode(generated, skip_special_tokens=True)[0])
    return "\n".join(texts)


def htr_page(image: Path, out_path: Path, *, _segment: Any = None, _transcribe: Any = None) -> str:
    """Segment + recognize one cursive page; writes the text atomically.

    The segment result is cached next to the output (``<out>.segment.json``)
    — the orli pass is the slow step (~8 min/page on CPU) and must not
    re-run when the recognition changes.
    """
    cache = out_path.with_suffix(".segment.json")
    if cache.exists():
        lines = json.loads(cache.read_text(encoding="utf-8"))
    else:
        lines = (_segment or segment_page)(image)
        atomic_write(cache, json.dumps(lines, ensure_ascii=False))
    boxes = line_boxes(lines)
    if not boxes:
        raise HtrError(f"no text lines detected on {image.name} — the page may be blank or a photo")
    crops = crop_lines(image, boxes)
    if _transcribe is not None:
        text = _transcribe(crops)
    else:
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel

        processor = TrOCRProcessor.from_pretrained(TROCR_MODEL)
        model = VisionEncoderDecoderModel.from_pretrained(TROCR_MODEL)
        try:
            text = transcribe_lines(crops, processor, model)
        finally:
            del model  # the 3.14 main venv shares RAM with everything else
    atomic_write(out_path, text)
    return text


def htr_pages(pages: list[tuple[str, Path]], raw_dir: Path) -> None:
    """HTR each (name, page-image) pair into raw_dir/<stem>.txt, in order."""
    from functools import partial

    from transformers import TrOCRProcessor, VisionEncoderDecoderModel

    processor = TrOCRProcessor.from_pretrained(TROCR_MODEL)
    model = VisionEncoderDecoderModel.from_pretrained(TROCR_MODEL)
    transcribe = partial(transcribe_lines, processor=processor, model=model)
    try:
        for name, image in pages:
            out = raw_dir / Path(name).with_suffix(".txt")
            if out.with_suffix(".segment.json").exists():
                print(f"htr: {name} already done — reusing")
                continue
            htr_page(image, out, _segment=segment_page, _transcribe=transcribe)
            print(f"htr: {name} -> {out.name}")
    finally:
        del processor, model  # the 3.14 main venv shares RAM with everything else; drop the weights promptly


def htr_pages_vlm(
    pages: list[tuple[str, Path]],
    raw_dir: Path,
    transcribe: Any = None,
) -> None:
    """The vision-model backend (the 2026-08-14 decision): each page in,
    verbatim text out, token usage recorded in a sidecar so re-runs skip
    transcribed pages and the cost is auditable. ``transcribe`` is the
    injectable seam (transcribe_image_vlm shape) for tests."""
    from tools.vlm import transcribe_image_vlm

    call = transcribe if transcribe is not None else transcribe_image_vlm
    for name, image in pages:
        out = raw_dir / Path(name).with_suffix(".txt")
        marker = out.with_suffix(".vlm.json")
        if marker.exists():
            print(f"vlm: {name} already done — reusing")
            continue
        print(f"vlm: {name} transcribing…", flush=True)
        text, usage = call(image)
        atomic_write(out, text)
        atomic_write(marker, json.dumps(usage, ensure_ascii=False))
        print(f"vlm: {name} -> {out.name} ({usage.get('total_tokens', 0)} tokens)")


if __name__ == "__main__":
    sys.exit(0)
