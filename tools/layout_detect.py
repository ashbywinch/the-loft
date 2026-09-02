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
import contextlib
import json
import os
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

from PIL import Image

from tools.layout import (
    Layout,
    admit_and_remap,
    load_orientation_hint,
    load_orientation_report,
    load_vlm_boxes,
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
    return Layout.single(
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
    failure — the line then DROPS (fail fast, never garbage-admitted).
    Every call is logged with its duration and token usage — the layout
    stage's VLM calls were SILENT, so a slow/failed run was undiagnosable
    (2026-08-22: page-03's rebuilds timed out with no evidence of why)."""
    started = monotonic()
    try:
        text, usage = transcribe_image_vlm(crop, max_tokens=4000, timeout=120.0)
        print(
            f"layout: clip read {crop.name} in {monotonic() - started:.1f}s, {usage.get('total_tokens', 0)} tokens",
            file=sys.stderr,
        )
    except VlmError as exc:
        # the FULL VlmError message — it carries the reasoning tail
        # (2026-08-22: the earlier [:120] truncation threw the tail away,
        # leaving only the counts — the actual reasoning was unreadable)
        print(
            f"layout: clip read {crop.name} FAILED after {monotonic() - started:.1f}s: {exc}",
            file=sys.stderr,
        )
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
    return Layout.multi(
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
    every oriented page). Returns 0 on success. Every run's diagnostics —
    the per-clip VLM calls (timing + tokens + failures), the drops, the
    per-page results — are teed to ``work/<batch>/logs/layout-<run>.log``
    so a problematic run is examinable AFTER the fact (2026-08-22: the
    rebuild timeouts were undiagnosable — the calls were silent)."""
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
    outcomes = [_process_page(engine, image, guess_dir, (batch_id, page_names, wanted, work_dir)) for image in pages]
    if 2 in outcomes:
        return 2
    refused = outcomes.count(1)
    missing = _missing_guesses(guess_dir, pages, outcomes)
    if missing:
        print(
            f"layout: {len(missing)} page(s) skipped — no guess text: {', '.join(sorted(missing))}",
            file=sys.stderr,
        )
    return 1 if refused else 0


def _missing_guesses(guess_dir: Path, pages: list[Path], outcomes: list[int]) -> list[str]:
    """The quietly-skipped pages: laid out 0 (or skipped implicitly) but
    with no guess text — extracted for the complexity bar."""
    return [
        image.name
        for image, outcome in zip(pages, outcomes, strict=True)
        if outcome == 0 and not (guess_dir / image.with_suffix(".txt").name).exists()
    ]


def _dedupe_region_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """§6 step 6: lines whose boxes substantially overlap claim the same
    region — keep the longer transcription, drop the shadowed one (the
    model's slabs overlap on rotated pages; 2026-08-30: 'I will write
    again t' and 'with you.' shared a region and the write refused)."""
    kept: list[dict[str, Any]] = []
    for ln in sorted(lines, key=lambda item: -len(item["text"])):
        box = ln["box"]
        shadowed = False
        for k in kept:
            b = k["box"]
            ox = min(box[2], b[2]) - max(box[0], b[0])
            oy = min(box[3], b[3]) - max(box[1], b[1])
            if ox <= 0 or oy <= 0:
                continue
            smaller = min((box[2] - box[0]) * (box[3] - box[1]), (b[2] - b[0]) * (b[3] - b[1]))
            if smaller and (ox * oy) / smaller > 0.6:
                shadowed = True
                break
        if not shadowed:
            kept.append(ln)
    return kept


def _read_column_regions(
    image: Path,
    regions: list[tuple[int, int]],
    y0: int,
    y1: int,
    call: tuple[str, str, str | None, Callable[..., Any] | None],
) -> list[dict[str, Any]] | None:
    """The upright regions' crop reads, the boxes stitched into the page
    frame (the rotated regions go through _rotated_column_lines). None
    when there are no regions to read."""
    # lucidlint: ignore inline-import the rescue's rare path; the harness pulls the VLM stack only when needed
    from tools.eval_crop_grid import read_crop
    from tools.eval_geometry import CropReading  # lucidlint: ignore inline-import the same rare path

    do_read = call[3] or read_crop
    if not regions:
        return None
    _y1 = y1
    lines: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="layout-regions-") as tmp:
        for i, (x0, x1) in enumerate(regions):
            force = False
            crop = CropReading(float(x0), float(y0), float(x1 - x0), float(_y1 - y0), [])
            read = do_read(crop, image, Path(tmp), i, call, force_rotate=force)
            if read is None:
                continue
            region_lines, _used = read
            for ln in region_lines:
                box = ln.get("box")
                if box:
                    ln["box"] = [box[0] + x0, box[1] + y0, box[2] + x0, box[3] + y0]
                lines.append(ln)
    return lines


def _region_orientation(ln_box: list[float], report_lines: list[dict[str, Any]], width: int, height: int) -> int:
    """The orientation report's degrees for the read line whose box
    overlaps the report's (the report's boxes are 0-1000 fractions of
    the page; the read's are page pixels). 0 when nothing overlaps —
    the model read the text upright (2026-08-30: glm-4.6v reads the
    postcard's rotated message without help, but its boxes are
    horizontal slabs, so the box-aspect signal can't see the
    rotation — the report, from the dedicated orientation pass, can)."""
    if not report_lines:
        return 0
    nx0 = ln_box[0] / width * 1000
    nx1 = ln_box[2] / width * 1000
    ny0 = ln_box[1] / height * 1000
    ny1 = ln_box[3] / height * 1000
    best, best_area = 0, 0.0
    for rl in report_lines:
        rb = rl.get("box")
        if not rb:
            continue
        overlap_x = min(nx1, rb[2]) - max(nx0, rb[0])
        overlap_y = min(ny1, rb[3]) - max(ny0, rb[1])
        if overlap_x <= 0 or overlap_y <= 0:
            continue
        area = overlap_x * overlap_y
        if area > best_area:
            best_area = area
            best = int(rl.get("degrees") or 0)
    return best


def _rotated_column_lines(
    image: Path,
    panel: tuple[int, int, int, int],
    engine: Any,
    tmp: Path,
    call: tuple[str, str, str | None, Callable[..., Any] | None],
) -> list[dict[str, Any]]:
    """``panel`` = the vertical text's (x0, y0, x1, y1) — the
    orientation report's 90°-located lines' union box (model-trial
    report §7)."""
    x0, y0, x1, y1 = panel
    model, base_url, api_key, transcribe_fn = call
    """Read vertical-text regions by the ink-column recipe (the
    eval_columns spike, model-trial-report §5's pivot): the rec's
    detection pieces on the rotated panel are REAL ink (its recognition
    is garbage, its boxes are measurements). Each region is cropped,
    rotated +90, its pieces clustered into rows; the whole rotated panel
    is read ONCE (the clean text — per-row clips were noisy) and its
    lines matched to the measured rows by y-band. The union-boxes are
    the measured line boxes; they remap into the page frame with the
    pinned +90 inverse (x = H' - y', y = x'). All lines carry
    the orientation stamped from the remapped box's shape."""
    from tools.ink import cluster_rows, match_labels, union  # lucidlint: ignore inline-import the rescue's rare path
    from tools.vlm import transcription_system_with_context  # lucidlint: ignore inline-import the same rare path

    tmp = Path(tmp)
    lines: list[dict[str, Any]] = []
    with Image.open(image) as im:
        panel_img = im.crop((x0, y0, x1, y1)).rotate(90, expand=True)
    rot_w, rot_h = panel_img.size
    panel_path = tmp / "rotated-panel.png"
    panel_img.save(panel_path)
    raw = detect_page(engine, panel_path)
    pieces = [[float(v) for v in d["box"]] for d in raw["detections"] if d["box"]]
    if not pieces:
        print("layout: no rec pieces on the rotated panel", file=sys.stderr)
        return lines
    rows = cluster_rows(pieces)
    do_transcribe = transcribe_fn or transcribe_image_vlm
    text, usage = do_transcribe(
        panel_path,
        model=model,
        system=transcription_system_with_context(),
        base_url=base_url,
        api_key=api_key,
        max_tokens=8000,
    )
    plain, model_boxes = parse_transcription_response(text)
    # the model's normalized boxes -> the rotated frame's pixel bands
    model_bands = [
        ((b[1] / 1000) * rot_h, (b[3] / 1000) * rot_h, plain.split("\n")[idx])
        for idx, b in sorted((model_boxes or {}).items())
    ]
    unions = [union(row) for row in rows]
    labels = match_labels(unions, plain.split("\n"), model_bands)
    for row_union, label in zip(unions, labels, strict=False):
        if not label.strip():
            continue
        ux0, uy0, ux1, uy1 = row_union
        # the union is in the ROTATED frame's pixels — the pinned
        # +90 inverse without normalized scaling
        page_box = [rot_h - uy1 + x0, ux0 + y0, rot_h - uy0 + x0, ux1 + y0]
        # the remap turns the rotated frame's horizontal lines into
        # vertical page columns — but printed text on the card is
        # horizontal and remaps to wide boxes. Stamp the orientation
        # from the remapped box's actual shape.
        w = page_box[2] - page_box[0]
        h = page_box[3] - page_box[1]
        orientation = 90 if h > w else 0
        lines.append(
            {
                "text": label,
                "box": [round(v) for v in page_box],
                "conf": 1.0,
                "words": [],
                "box_source": "ink",
                "orientation": orientation,
            }
        )
        print(
            f"layout: rotated panel: {len(pieces)} pieces, {len(rows)} rows, "
            f"{int(usage.get('total_tokens', 0) or 0)} tokens",
            file=sys.stderr,
        )
    return lines


def _split_regions_by_report(
    image: Path, regions: list[tuple[int, int]], report_lines: list[dict[str, Any]]
) -> tuple[tuple[int, int, int, int] | None, list[tuple[int, int]]]:
    """The report's located lines ARE the crop boundaries (model-trial
    report §7): the 90°-located lines' union box is the vertical panel
    (read rotated); regions outside it read upright. Returns (the
    vertical panel's (x0, y0, x1, y1) or None, the upright regions)."""
    with Image.open(image) as im:
        page_w, page_h = im.size
    vertical_boxes = [
        (
            int(rl["box"][0] / 1000 * page_w),
            int(rl["box"][1] / 1000 * page_h),
            int(rl["box"][2] / 1000 * page_w),
            int(rl["box"][3] / 1000 * page_h),
        )
        for rl in report_lines
        if rl.get("degrees") == 90 and rl.get("box")
    ]
    if not vertical_boxes:
        return None, regions
    vx0 = min(b[0] for b in vertical_boxes)
    vy0 = min(b[1] for b in vertical_boxes)
    vx1 = max(b[2] for b in vertical_boxes)
    vy1 = max(b[3] for b in vertical_boxes)
    # a margin around the located lines: the report's boxes bound the
    # text, the crop must bound the ink that carries it
    margin = 40
    panel = (max(0, vx0 - margin), max(0, vy0 - margin), min(page_w, vx1 + margin), min(page_h, vy1 + margin))

    def _outside(x0: int, x1: int) -> bool:
        # a region is upright when the vertical panel claims less than
        # a third of it — a sliver overlap must not swallow a column
        overlap = min(x1, panel[2]) - max(x0, panel[0])
        if overlap <= 0:
            return True
        return overlap / (x1 - x0) < 0.3

    return panel, [(x0, x1) for x0, x1 in regions if _outside(x0, x1)]


def _region_read_rescue(
    image: Path,
    work_dir: Path,
    engine: Any,
    report_lines: list[dict[str, Any]] | None = None,
    seams: tuple[Callable[..., Any] | None, Callable[..., Any] | None] | None = None,
) -> dict[str, Any] | None:
    """``seams`` = (read_crop_fn, transcribe_fn) — the DI test seams."""
    read_crop_fn, transcribe_fn = seams or (None, None)
    """The rotated-region rescue (model-trial-report §6, the
    eval_regions/eval_columns/eval_crop_grid spikes): the ink's
    x-projection splits the page into column regions. A region the
    orientation report locates at 90° goes through the ink-column recipe
    (boxes measured from the rec's pieces on the rotated panel, text
    from one panel read, boxes remapped with the pinned +90 inverse);
    upright regions go through the crop reads. Returns a layout dict, or
    None when the reads yield nothing usable. Gates D/E don't run here:
    the rec supplies no page-frame pieces on pages like this (that is
    why the plain build refused), so the ink/conflict checks have
    nothing to measure against. ``read_crop_fn`` is the test seam (DI,
    never monkeypatch)."""
    from tools.eval_regions import column_regions, ink_y_range  # lucidlint: ignore inline-import the same rare path
    from tools.text import flag_line_words  # lucidlint: ignore inline-import the same rare path

    try:
        regions = column_regions(image)
        if not regions:
            return None
        y0, y1 = ink_y_range(image)
    except OSError:
        return None
    panel, upright_regions = _split_regions_by_report(image, regions, report_lines or [])
    lines: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="layout-regions-") as tmp:
        if panel:
            lines.extend(
                _rotated_column_lines(
                    image,
                    panel,
                    engine,
                    tmp,
                    ("dynamic/image", os.environ.get("OPENAI_BASE_URL", ""), None, transcribe_fn),
                )
            )
        if upright_regions:
            call = ("dynamic/image", os.environ.get("OPENAI_BASE_URL", ""), None, read_crop_fn)
            lines.extend(_read_column_regions(image, regions=upright_regions, y0=y0, y1=y1, call=call))
    usable = [ln for ln in lines if ln.get("box") and ln["box"][2] > ln["box"][0] and ln["box"][3] > ln["box"][1]]
    usable = _dedupe_region_lines(usable)
    if len(usable) < 2:  # one line is not a layout
        return None
    usable.sort(key=lambda ln: (ln["box"][1], ln["box"][0]))
    with Image.open(image) as im:
        width, height = im.size
    return {
        "page": image.stem,
        "width": width,
        "height": height,
        "lines": [
            {
                "text": ln["text"],
                "box": [round(v) for v in ln["box"]],
                "conf": 1.0,
                "words": flag_line_words(ln["text"], set()),
                "box_source": ln.get("box_source", "region-read"),
                "orientation": ln.get("orientation", 0),
            }
            for ln in usable
        ],
        "unmatched": [],
    }


def _process_page(
    engine: Any,
    image: Path,
    guess_dir: Path,
    batch: tuple[str, list[str] | None, set[str], Path],
) -> int:
    """Lay ONE page out — 0 = laid out or quietly skipped, 1 = refused
    (the gates: boxless lines now fail the run, 2026-08-22), 2 = fatal
    (an explicitly requested page has no guess text). Split from
    run_batch for the complexity bar. ``batch`` = (batch_id, page_names,
    wanted, work_dir)."""
    batch_id, page_names, wanted, work_dir = batch
    vlm_path = guess_dir / image.with_suffix(".txt").name
    if not vlm_path.exists():
        rc = _warn_missing_guess(image.name, vlm_path.name, page_names, wanted)
        return 2 if rc else 0
    try:
        _layout_one(engine, image, guess_dir, batch_id, work_dir)
        return 0
    except ValueError as exc:
        print(f"layout: {image.name} refused — {str(exc)[:160]}", file=sys.stderr)
        return 1


def _build_page_layout(engine: Any, image: Path, guess_dir: Path) -> Any:
    """Run the multi-orientation build when the orientation hints or the
    report's line evidence say the page needs it, else the plain build
    (extracted from _layout_one 2026-08-30 for the complexity bar)."""
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
    vlm_text = (guess_dir / image.with_suffix(".txt").name).read_text(encoding="utf-8")
    if orientations:
        passes = orientation_passes(orientations)
        layout = layout_page_multi(
            engine,
            image,
            passes,
            report_lines=report.get("lines") or None,
            vlm_text=vlm_text,
            trust_report_degrees=report.get("source") == "clip",
        )
        print(f"layout: {image.name} multi-orientation {orientations} (passes {passes}) -> {len(layout.lines)} lines")
        return layout
    selfreport_path = guess_dir / f"{image.stem}.selfreport.json"
    selfreport = None
    if selfreport_path.exists():
        selfreport = json.loads(selfreport_path.read_text(encoding="utf-8"))
    vlm_boxes = load_vlm_boxes(guess_dir / f"{image.stem}.vlm.json")
    return layout_page(engine, image, vlm_text, selfreport, vlm_boxes)


def _layout_one(engine: Any, image: Path, guess_dir: Path, batch_id: str, work_dir: Path) -> None:
    """Layout ONE page: read its guess/orientation/self-report, run the
    (multi-orientation) layout build, and persist via the store. Split
    from run_batch so the per-page path stays under the complexity bar."""
    layout = _build_page_layout(engine, image, guess_dir)
    # Gate D (2026-08-20): a boxed line must contain the ink it claims —
    # page-03's transcription boxes sat ~200px above the real text, and
    # a well-proportioned box in a blank region is an estimate, not an
    # anchor; the box is dropped (the line stays flagged).
    inkless = layout.drop_inkless(image)
    if inkless:
        print(f"layout: {image.name} — {inkless} box(es) with no ink dropped (Gate D)", file=sys.stderr)
    # Gate E as a correction (2026-08-22): a box that claims another
    # line's region with different text shadows the confirmed anchor —
    # page-03's boxless lines sat on the P.S. margin, refusing the page
    # at the serve gate. The lower-confidence box drops.
    conflicts = layout.drop_conflicts()
    if conflicts:
        print(f"layout: {image.name} — {conflicts} conflicting box(es) dropped (Gate E)", file=sys.stderr)
    out = guess_dir / f"{image.stem}.layout.json"
    # the store roots at the work_dir this run was GIVEN, not the global
    # WORK_DIR: the hermetic tests pass a tmp dir, and the hardcoded root
    # wrote to /run/media/... on CI — which has no work disk (2026-08-29,
    # the build-and-test failure on all four PRs)
    store = PipelineStore(work_dir)
    store_path = str(Path(batch_id) / "ocr-guess" / out.name)
    try:
        write_layout_store(layout.to_dict(), store, store_path)
    except ValueError:
        # The plain/multi build refused (the detector misses boxes on
        # rotated text — the postcard's back). The rotated-region rescue
        # (§6) reads each ink-column at its own orientation instead; the
        # re-write re-validates, so a still-bad rescue refuses honestly.
        report = load_orientation_report(guess_dir / f"{image.stem}.orientation.json")
        rescued = _region_read_rescue(
            image,
            work_dir,
            engine,
            report_lines=(report.get("lines") or []) if isinstance(report, dict) else [],
        )
        if rescued is None:
            raise
        print(
            f"layout: {image.name} region-read rescue ({len(rescued['lines'])} lines)",
            file=sys.stderr,
        )
        write_layout_store(rescued, store, store_path)
    flagged = sum(1 for line in layout.lines for w in line["words"] if w["conf"] == 0.0)
    print(
        f"layout: {image.name} {len(layout.lines)} lines, "
        f"{len(layout.unmatched)} unmatched, {flagged} flagged words -> {out.name}"
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


@contextlib.contextmanager
def _run_log(work_dir: Path, batch_id: str) -> Any:
    """Tee the run's stderr diagnostics to ``work/<batch>/logs/
    layout-<run>.log`` — a problematic run stays examinable after the
    fact (2026-08-22: the rebuild timeouts were undiagnosable because the
    layout stage's VLM calls were silent)."""
    # a FRESH file per run (the microseconds + the pid make the name
    # unique) — never an accumulating log the runs keep appending to
    # (2026-08-22, user: no one big growing log file)
    log_path = work_dir / batch_id / "logs" / f"layout-{datetime.now():%Y%m%d-%H%M%S-%f}-{os.getpid()}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    real_stderr = sys.stderr

    class _Tee:
        def write(self, text: str) -> int:
            real_stderr.write(text)
            log.write(text)
            return len(text)

        def flush(self) -> None:
            real_stderr.flush()
            log.flush()

    try:
        with contextlib.redirect_stderr(_Tee()):
            yield log_path
    finally:
        log.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="layout_detect", description="The layout pass per batch")
    parser.add_argument("batch_id")
    parser.add_argument("pages", nargs="*", help="optional page names to limit the pass")
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR)
    args = parser.parse_args(argv)
    with _run_log(args.work_dir, args.batch_id) as log_path:
        print(f"layout: run log -> {log_path}", file=sys.stderr)
        # paddleocr lives only in .venv-htr; the main venv's tests import this module for the rescue helpers
        # lucidlint: ignore inline-import the paddle stack must load only in the .venv-htr interpreter
        from paddleocr import PaddleOCR

        engine = PaddleOCR(**ENGINE)
        try:
            return run_batch(args.batch_id, args.pages or None, args.work_dir, engine)
        finally:
            del engine  # drop the weights promptly — the 3.13 venv shares RAM with the main venv


if __name__ == "__main__":
    sys.exit(main())
