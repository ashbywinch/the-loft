"""The layout pass's detection stage (TECH-SPEC §16.16, 2026-08-15).

Runs under the .venv-htr interpreter (py3.13 — PaddleOCR lives there;
the main venv never imports it; the PIL/paddleocr imports are inline,
matching tools/htr.py's pattern for the same situation). Detects the
page's text lines + per-word boxes with PP-OCRv5 mobile det
(enable_mkldnn=False — the oneDNN/PIR path crashes on this CPU;
orientation/unwarping/line-orientation off — the oriented pages are
already upright), then associates the detections with the VLM guess
(tools.layout) and writes the page layout JSON atomically.

Proven on the live pages (2026-08-15): 40 line boxes on page-03, all with
real ink; the engine returns coordinates in the ORIGINAL image's pixels
(mapped back after its internal <=4000px resize) — asserted here so a
future engine change fails loudly instead of silently misaligning.

Usage: .venv-htr/bin/python -m tools.layout_detect <batch_id> [page ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from paddleocr import PaddleOCR
from PIL import Image

from tools.layout import (
    admit_and_remap,
    build_layout,
    load_orientation_hint,
    load_orientation_report,
    load_vlm_boxes,
    multi_layout,
    orientation_passes,
    write_layout_store,
)
from tools.loft_paths import WORK_DIR
from tools.pipeline_store import PipelineStore
from tools.store import DiskStore  # noqa: F401
from tools.vlm import VlmError, parse_transcription_response, transcribe_image_vlm

# The proven engine config (spike, 2026-08-15) — the rec model rides along
# (its noisy text IS the cross-reader confidence signal).
ENGINE = dict(
    ocr_version="PP-OCRv5",
    text_detection_model_name="PP-OCRv5_mobile_det",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    enable_mkldnn=False,
    # The engine's peak memory scales with the detection input AREA — the
    # 8GB laptop OOM-killed the layout stage on the full-res phone scans
    # (3500px) with the default 4000px limit (2026-08-17, repeated kills
    # at model load + first prediction). 2000px bounds the peak ~4x; the
    # engine resizes internally and maps the boxes back to the input
    # image's pixels, so the layout geometry is unchanged — the
    # coordinate assertion below guards that mapping.
    text_det_limit_side_len=2000,
)

# Tolerances for the coordinate-space assertion: the engine maps detections
# back to the input image; a coordinate straying past the image bounds means
# the mapping changed and every stored box would be wrong.
_BOUNDS_EPSILON = 4.0


def _assert_original_space(boxes: list[list[Any]], width: int, height: int) -> None:
    """Fail loudly if the detections are not in the original image's pixels."""
    for box in boxes:
        xs = [pt[0] for pt in box]
        ys = [pt[1] for pt in box]
        if min(xs) < -_BOUNDS_EPSILON or max(xs) > width + _BOUNDS_EPSILON:
            raise RuntimeError(
                f"detection x outside the original image ({min(xs):.0f}..{max(xs):.0f} in {width}px) "
                "— the engine's coordinate mapping changed; do not store these boxes"
            )
        if min(ys) < -_BOUNDS_EPSILON or max(ys) > height + _BOUNDS_EPSILON:
            raise RuntimeError(
                f"detection y outside the original image ({min(ys):.0f}..{max(ys):.0f} in {height}px) "
                "— the engine's coordinate mapping changed; do not store these boxes"
            )


def _bbox(poly: list[Any]) -> list[float]:
    """The polygon's axis-aligned box [x0, y0, x1, y1] — plain floats (the
    engine returns numpy scalars, which json cannot serialize)."""
    xs = [float(pt[0]) for pt in poly]
    ys = [float(pt[1]) for pt in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def detect_page(engine: Any, image: Path) -> dict[str, Any]:
    """The raw detection output for one page: lines + per-word boxes in the
    original image's pixels."""
    with Image.open(image) as im:
        width, height = im.size
    first = engine.predict(input=str(image), return_word_box=True)[0]
    polys = first["dt_polys"]
    texts = first["rec_texts"]
    scores = first["rec_scores"]
    word_regions = first.get("text_word_region") or first.get("text_word_boxes")
    _assert_original_space(polys, width, height)
    detections = []
    for i, poly in enumerate(polys):
        regions = word_regions[i] if word_regions is not None and i < len(word_regions) else []
        words_out: list[dict[str, Any]] = [{"box": _bbox(region)} for region in regions]
        detections.append(
            {
                "box": _bbox(poly),
                "text": texts[i] if i < len(texts) else "",
                "score": float(scores[i]) if i < len(scores) else 0.0,
                "words": words_out,
            }
        )
    return {"width": width, "height": height, "detections": detections}


def layout_page(
    engine: Any,
    image: Path,
    vlm_text: str,
    selfreport: list[dict[str, Any]] | None = None,
    vlm_boxes: dict[int, list[float]] | None = None,
) -> dict[str, Any]:
    """Detect + associate one page; the layout dict ready to publish. The
    self-report (the transcription model's own doubt, tools/selfreport.py)
    drives the per-word flags when present; without one the cross-reader
    agreement is the fallback. The VLM's OWN per-line boxes
    (``vlm_boxes``, from the transcription sidecar) anchor the lines the
    model that READ the page transcribed — the rec association only fills
    the rest (2026-08-16: the rec cannot read cursive and merges/misses
    its lines)."""
    raw = detect_page(engine, image)
    return build_layout(
        image.name,
        raw["width"],
        raw["height"],
        vlm_text,
        raw["detections"],
        selfreport=selfreport,
        vlm_boxes=vlm_boxes,
    )


def pass_at(
    engine: Any, image: Path, degrees: int, ow: int, oh: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One orientation pass (PRD VR15): rotate the page so that
    orientation is upright, detect, and admit only the lines the
    recognizer reads as real text at this orientation — remapped to the
    original image's frame. Returns (kept, rejected)."""
    rotated = image.with_name(f"{image.stem}.rot{degrees}.png")
    Image.open(image).rotate(-degrees, expand=True).save(rotated)
    try:
        raw = detect_page(engine, rotated)
        return admit_and_remap(raw["detections"], degrees, (ow, oh), (raw["width"], raw["height"]))
    finally:
        rotated.unlink(missing_ok=True)


def _vlm_clip_reader(crop: Path) -> str | None:
    """Read one upright line clip with the vision model — the extra-line
    recognition (2026-08-20): the rec engine's rotated-frame fragment is
    garbage for cursive; the VLM reads the de-rotated clip. None on any
    failure — the line then DROPS (fail fast, never garbage-admitted)."""
    try:
        text, _ = transcribe_image_vlm(crop, max_tokens=4000, timeout=120.0)
    except VlmError:
        return None
    try:
        plain, _ = parse_transcription_response(text)
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return plain.strip() or None


# the multi-pass assembly's six stage inputs — engine, image, the orientations, the report, the text, the trust
# flag — are one function's data; a parameter object would obscure it (the same why as multi_layout's suppression)
# lucidlint: ignore long-param-list a parameter object would obscure the pure function
def layout_page_multi(
    engine: Any,
    image: Path,
    orientations: list[int],
    report_lines: list[dict[str, Any]] | None = None,
    vlm_text: str | None = None,
    trust_report_degrees: bool = False,
) -> dict[str, Any]:
    """The multi-orientation layout (PRD VR15): a detection pass at each
    reported orientation, recognition-driven admission, one combined
    layout — the guess's authoritative transcription located at the
    report's per-line boxes (the v3 anchoring, 2026-08-17), the rec
    passes validating; without the report the rec-based lines fall back.
    The oriented image is already the pipeline's right way up, so the
    initial display rotation stays 0. The rec-only extra lines are
    re-read from their own upright clips (2026-08-20); the clip-sourced
    report's located degrees are trusted over the pass orientations
    (``trust_report_degrees``)."""
    with Image.open(image) as im:
        ow, oh = im.size
    passes: list[tuple[int, list[dict[str, Any]]]] = []
    for degrees in orientations:
        kept, _ = pass_at(engine, image, degrees, ow, oh)
        passes.append((degrees, kept))
    return multi_layout(
        image.name,
        ow,
        oh,
        passes,
        report_lines=report_lines,
        vlm_text=vlm_text,
        image=image,
        recognize=_vlm_clip_reader,
        trust_report_degrees=trust_report_degrees,
    )


def run_batch(batch_id: str, page_names: list[str] | None, work_dir: Path, engine: Any) -> int:
    """Layout the batch's oriented pages; page_names narrows the set (None =
    every oriented page). Returns 0 on success."""
    oriented_dir = work_dir / batch_id / "oriented"
    guess_dir = work_dir / batch_id / "ocr-guess"
    if not oriented_dir.is_dir():
        print(f"layout: no oriented dir for batch {batch_id!r}", file=sys.stderr)
        return 1
    # all jpgs, not just page-*: phone-export duplicates arrive as names
    # like "1782635795946-5f7905a9~2.jpg" (the PhotoScan batch, 2026-08-16)
    # and must not be silently skipped by the layout pass
    pages = [p for p in sorted(oriented_dir.glob("*.jpg"))]
    wanted: set[str] = set()
    if page_names:
        # The CLI takes bare stems ("page-02"); the glob yields full
        # filenames ("page-02.jpg") — normalize so the filter actually
        # matches (2026-08-20: a raw `p.name in wanted` silently produced
        # an empty page list and exit 0, a no-op that looked like success).
        wanted = {p if p.endswith(".jpg") else p + ".jpg" for p in page_names}
        pages = [p for p in pages if p.name in wanted]
        if not pages:
            print(
                f"layout: FATAL — none of the requested pages exist in {oriented_dir}: {', '.join(sorted(wanted))}",
                file=sys.stderr,
            )
            return 2
    missing: list[str] = []
    for image in pages:
        vlm_path = guess_dir / image.with_suffix(".txt").name
        if not vlm_path.exists():
            rc = _warn_missing_guess(image.name, vlm_path.name, page_names, wanted)
            if rc:
                return rc
            missing.append(image.name)
            continue
        try:
            _layout_one(engine, image, guess_dir, batch_id)
        except ValueError as exc:  # lucidlint: ignore swallow one bad page must not kill the batch (2026-08-20)
            # A refused layout write (invalid boxes) must not kill the
            # batch (2026-08-20: page-12's out-of-image boxes crashed the
            # whole run after 11 pages had laid out). Record, skip the
            # page, continue — the serve path already refuses the page
            # and the next pass can retry with fresh inputs.
            print(f"layout: {image.name} refused — {str(exc)[:160]}", file=sys.stderr)
    if missing:
        print(
            f"layout: {len(missing)} page(s) skipped — no guess text: {', '.join(sorted(missing))}",
            file=sys.stderr,
        )
    return 0


def _layout_one(engine: Any, image: Path, guess_dir: Path, batch_id: str) -> None:
    """Layout ONE page: read its guess/orientation/self-report, run the
    (multi-orientation) layout build, and persist via the store. Split
    from run_batch so the per-page path stays under the complexity bar."""
    vlm_path = guess_dir / image.with_suffix(".txt").name
    report = load_orientation_report(guess_dir / f"{image.stem}.orientation.json")
    orientations = load_orientation_hint(guess_dir / f"{image.stem}.orientation.json")
    # The multi path needs either the hint OR the report's line evidence.
    # The v3 report's multi-direction evidence lives in the LINES' degrees
    # (the model locates the known text; the orientation_hint may be empty
    # — 2026-08-20: page-03's empty-hints report fell to the plain path and
    # the good anchored text was replaced by detection fragments).
    if not orientations:
        located = report.get("lines", []) if isinstance(report, dict) else []
        line_degrees = {int(ln.get("degrees")) for ln in located if ln.get("degrees") in (0, 90, 180, 270)}
        if len(line_degrees) >= 2:
            orientations = sorted(line_degrees)
    if orientations:
        passes = orientation_passes(orientations)
        report_lines = report.get("lines") or None
        vlm_text = vlm_path.read_text(encoding="utf-8")
        layout = layout_page_multi(
            engine,
            image,
            passes,
            report_lines=report_lines,
            vlm_text=vlm_text,
            trust_report_degrees=report.get("source") == "clip",
        )
        print(
            f"layout: {image.name} multi-orientation {orientations} (passes {passes}) -> {len(layout['lines'])} lines"
        )
    else:
        selfreport_path = guess_dir / f"{image.stem}.selfreport.json"
        selfreport = None
        if selfreport_path.exists():
            selfreport = json.loads(selfreport_path.read_text(encoding="utf-8"))
        vlm_boxes = load_vlm_boxes(guess_dir / f"{image.stem}.vlm.json")
        layout = layout_page(engine, image, vlm_path.read_text(encoding="utf-8"), selfreport, vlm_boxes)
    out = guess_dir / f"{image.stem}.layout.json"
    store = PipelineStore(WORK_DIR)
    store_path = str(Path(batch_id) / "ocr-guess" / out.name)
    write_layout_store(layout, store, store_path)
    flagged = sum(1 for line in layout["lines"] for w in line["words"] if w["conf"] == 0.0)
    print(
        f"layout: {image.name} {len(layout['lines'])} lines, "
        f"{len(layout['unmatched'])} unmatched, {flagged} flagged words -> {out.name}"
    )


def _warn_missing_guess(image_name: str, txt_name: str, page_names: list[str] | None, wanted: set[str]) -> int:
    """A page with no guess text must never be laid out from geometry alone
    (2026-08-20 — the bad page-02 layout was exactly that). Explicitly
    requested pages are fatal (2); implicit pages are skipped loudly with
    a stderr warning. Returns the exit code to return, 0 to continue."""
    if page_names and image_name in wanted:
        print(
            f"layout: FATAL — no guess text for {image_name} (requested explicitly). "
            f"Run the guess stage first, or restore {txt_name}.",
            file=sys.stderr,
        )
        return 2
    print(f"layout: no guess text for {image_name} — skipping", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="layout_detect", description="The layout pass per batch")
    parser.add_argument("batch_id")
    parser.add_argument("pages", nargs="*", help="optional page names to limit the pass")
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR)
    args = parser.parse_args(argv)
    engine = PaddleOCR(**ENGINE)
    try:
        return run_batch(args.batch_id, args.pages or None, args.work_dir, engine)
    finally:
        del engine  # drop the weights promptly — the 3.13 venv shares RAM with the main venv


if __name__ == "__main__":
    sys.exit(main())
