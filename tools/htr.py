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
import os
import subprocess
import sys
import tempfile
from functools import partial
from pathlib import Path
from typing import Any

from PIL import Image

# The transformers/TrOCR stack (~450MB of torch+CUDA libs) is ONLY needed
# by the local HTR backend (LOFT_HTR_BACKEND=local, the privacy mode). The
# serving layer imports htr_pages_vlm for the reprocess route, and the
from tools.atomic import atomic_write
from tools.loft_paths import WORK_DIR
from tools.pipeline_store import PipelineStore, file_sha256
from tools.store import DiskStore  # noqa: F401
from tools.vlm import parse_transcription_response, transcribe_image_vlm, transcription_system_with_context


def _marker_input_matches(marker: Path, input_sha: str) -> bool:
    """Does the completion marker record the CURRENT input fingerprint?
    A marker without the field (written before 2026-08-20) is treated as
    stale — it cannot prove its input — so the stage re-transcribes once
    and the fresh marker carries the fingerprint."""
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("input_sha") == input_sha


# The transformers/TrOCR stack (~450MB of torch+CUDA libs) is ONLY needed
# by the local HTR backend (LOFT_HTR_BACKEND=local, the privacy mode). It
# is imported INSIDE _trocr_models — the call-site lazy import — so no
# process that imports tools.htr (the review server included, via
# htr_pages_vlm) ever loads torch: before 2026-08-17 the top-level import
# dragged it into the server and every watchfiles reload-spawned copy of
# it, ~450MB each. The lazy import is the deliberate exception to the
# imports-at-top standard (lucidlint-review-log §3.3).
KRAKEN = str(Path(__file__).resolve().parent.parent / ".venv-htr" / "bin" / "kraken")
ORLI_MODEL = Path.home() / ".local/share/htrmopo/c690cc12-0cf5-59dd-af71-69cdef2392b2/orli_base.safetensors"
TROCR_MODEL = "microsoft/trocr-small-handwritten"

# The ML stages leave a core for the rest of the box (2026-08-17, the
# laptop requirement): torch's inference threads cap at nproc-1.
ML_THREADS = max(1, (os.cpu_count() or 2) - 1)

# Line-box geometry (the crop bounds derived from each line's baseline): the
# box spans the gap to the NEXT baseline — clamped to sane heights, split
# 60% above / 40% below the baseline; the last line (no next baseline) gets
# a default gap. Crops pad the box 8px each side.
DEFAULT_LINE_GAP = 60  # px below the last line's baseline
MIN_LINE_GAP = 20.0
MAX_LINE_GAP = 200.0
GAP_ABOVE_BASELINE = 0.6  # share of the gap above the baseline
GAP_BELOW_BASELINE = 0.4  # share of the gap below the baseline
CROP_PADDING = 8  # px of margin around each line crop
ERROR_SNIPPET_CHARS = 200  # chars of model output shown in HtrError messages


class HtrError(RuntimeError):
    """An HTR stage failed; the message is the plain-language line."""


def segment_page(image: Path, orli: Path = ORLI_MODEL, kraken: str = KRAKEN) -> list[dict[str, Any]]:
    """Run kraken+orli on one page; returns the JSON line records (baselines),
    coordinates in the ORIGINAL image space (the page is downscaled to orli's
    trained input range for speed, and the baselines are remapped back)."""
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
            os.close(fd)  # PIL opens the path itself — the fd must not leak (review, 2026-08-15)
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
        raise HtrError(f"kraken segment returned no JSON for {image.name}: {stdout[:ERROR_SNIPPET_CHARS]!r}")
    try:
        payload, _ = json.JSONDecoder().raw_decode(stdout[start:])  # trailing progress text allowed
    except json.JSONDecodeError as exc:
        raise HtrError(
            f"kraken segment returned malformed JSON for {image.name}: {stdout[start : start + ERROR_SNIPPET_CHARS]!r}"
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
        next_y = entries[i + 1]["y"] if i + 1 < len(entries) else entry["y"] + DEFAULT_LINE_GAP
        gap = max(MIN_LINE_GAP, min(MAX_LINE_GAP, next_y - entry["y"]))
        top = entry["y"] - GAP_ABOVE_BASELINE * gap
        bottom = entry["y"] + GAP_BELOW_BASELINE * gap
        boxes.append((int(entry["x0"]), int(top), int(entry["x1"]), int(bottom)))
    return boxes


def crop_lines(image: Path, boxes: list[tuple[int, int, int, int]]) -> list[Any]:
    """The line images (PIL), padded 8px each side, in reading order."""
    img = Image.open(image).convert("RGB")
    crops: list[Any] = []
    for x0, y0, x1, y1 in boxes:
        left, top = max(0, x0 - CROP_PADDING), max(0, y0 - CROP_PADDING)
        right, bottom = min(img.width, x1 + CROP_PADDING), min(img.height, y1 + CROP_PADDING)
        if right > left and bottom > top:
            crops.append(img.crop((left, top, right, bottom)))
    return crops


def _trocr_models() -> tuple[Any, Any]:
    """The TrOCR recognition stack — loaded ONLY when the local HTR
    backend actually runs (the call-site lazy import, 2026-08-17: see
    the module note — no process that never runs htr_pages loads
    torch). Threads capped at nproc-1 — the ML stages leave a core for
    the rest of the box."""
    import torch  # lucidlint: ignore inline-import the lazy local-backend load (module note)
    from transformers import (  # lucidlint: ignore inline-import the lazy local-backend load (module note)
        TrOCRProcessor,
        VisionEncoderDecoderModel,
    )

    torch.set_num_threads(ML_THREADS)
    processor = TrOCRProcessor.from_pretrained(TROCR_MODEL)
    model = VisionEncoderDecoderModel.from_pretrained(TROCR_MODEL)
    return processor, model


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
        processor, model = _trocr_models()
        try:
            text = transcribe_lines(crops, processor, model)
        finally:
            del model  # the 3.14 main venv shares RAM with everything else
    store = PipelineStore(WORK_DIR)
    batch_id = out_path.parent.parent.name
    store_path = str(Path(batch_id) / "ocr-guess" / out_path.name)
    store.write(store_path, text)
    atomic_write(out_path, text)  # backward compat — htr_pages reads from the old path
    return text


def htr_pages(pages: list[tuple[str, Path]], raw_dir: Path) -> None:
    """HTR each (name, page-image) pair into raw_dir/<stem>.txt, in order."""
    processor, model = _trocr_models()
    transcribe = partial(transcribe_lines, processor=processor, model=model)
    try:
        for name, image in pages:
            out = raw_dir / Path(name).with_suffix(".txt")
            # the segment cache is written BEFORE the recognition output —
            # a crash in between leaves it present with no .txt, and a skip
            # keyed on the cache would permanently skip the page (review,
            # 2026-08-15: the page's transcription silently never lands).
            # htr_page reuses the cached segment, so the resume is cheap.
            if out.exists():
                print(f"htr: {name} already done — reusing")
                continue
            htr_page(image, out, _segment=segment_page, _transcribe=transcribe)
            print(f"htr: {name} -> {out.name}")
    finally:
        del processor, model  # the 3.14 main venv shares RAM with everything else; drop the weights promptly


# shape; the extra params (transcribe seam, people/places/label context) belong to this backend alone; a stage-inputs
# type would be ceremony for one use
# lucidlint: ignore long-param-list the VLM backend's stage inputs — htr_pages takes only (pages, raw_dir), a disjoint
def htr_pages_vlm(
    pages: list[tuple[str, Path]],
    raw_dir: Path,
    transcribe: Any = None,
    *,
    people: list[str] | None = None,
    places: list[str] | None = None,
    label: str | None = None,
    store_root: Path = WORK_DIR,
) -> None:
    """The vision-model backend (the 2026-08-14 decision): each page in,
    verbatim text out, token usage recorded in a sidecar so re-runs skip
    transcribed pages and the cost is auditable. ``transcribe`` is the
    injectable seam (transcribe_image_vlm shape). The system prompt carries
    the context that helps the model READ — the family's known names and
    places (a familiar name is read correctly, not guessed letter-by-letter),
    the pile's label, and the previous page's text for continuity (user,
    2026-08-15: "whatever useful context we have to help it guess better")."""
    call = transcribe if transcribe is not None else transcribe_image_vlm
    previous: str | None = None
    for name, image in pages:
        out = raw_dir / Path(name).with_suffix(".txt")
        marker = out.with_suffix(".vlm.json")
        # Skip only when BOTH the completion marker and the artifact it
        # promises exist and are non-empty, AND the marker records the
        # CURRENT input image's fingerprint. A marker whose input changed
        # (a re-orientation rewrote the jpg) is stale — the text was read
        # from the old image (2026-08-20: page-02's marker predated its
        # orientation fix, so the chain "reused" the corrupt guess).
        # Existence alone is a lie of a completion proxy; validate the
        # input dependency before skipping.
        input_sha = file_sha256(image)
        if (
            marker.exists()
            and out.exists()
            and out.read_text(encoding="utf-8").strip()
            and _marker_input_matches(marker, input_sha)
        ):
            print(f"vlm: {name} already done — reusing")
            previous = out.read_text(encoding="utf-8")  # keep the continuity current
            continue
        if marker.exists():
            print(f"vlm: {name} input changed or text missing — re-transcribing")
        else:
            print(f"vlm: {name} transcribing…", flush=True)
        system = transcription_system_with_context(people=people, places=places, label=label, previous_page=previous)
        text, usage = call(image, system=system)
        plain, boxes = parse_transcription_response(text)
        atomic_write(out, plain)  # backward compat — callers read from the old path
        store = PipelineStore(store_root)
        batch_id = out.parent.parent.name
        store_path = str(Path(batch_id) / "ocr-guess" / out.name)
        store.write(store_path, plain)
        marker_data: dict[str, Any] = dict(usage)
        marker_data["input_sha"] = input_sha
        if boxes is not None:
            # the VLM's own line geometry (normalized 0-1000) — the layout
            # pass uses it instead of the rec association, which cannot read
            # cursive (2026-08-16: the rec merges lines into tall boxes and
            # misses the top line entirely — the VLM that READ the page can
            # anchor each line it transcribed). Only the entries with boxes
            # ride along; a page without geometry keeps the old fallback.
            marker_data["lines"] = [{"text": plain.split("\n")[i], "box": boxes[i]} for i in sorted(boxes)]
        store = PipelineStore(store_root)
        batch_id = out.parent.parent.name
        store_path = str(Path(batch_id) / "ocr-guess" / marker.name)
        store.write(store_path, json.dumps(marker_data, ensure_ascii=False))
        atomic_write(marker, json.dumps(marker_data, ensure_ascii=False))  # backward compat — marker.exists()
        previous = plain
        print(f"vlm: {name} -> {out.name} ({usage.get('total_tokens', 0)} tokens)")


if __name__ == "__main__":
    sys.exit(0)
