"""The crop-grid experiment's real run (2026-08-22, Phase 2): one page
read as a grid of overlapping crops, each crop read by the VLM — the
model measures the lines WITHIN the crop (its geometry is trustworthy
only when the question is LOCAL; the full-page location report is
schematic), the crop-local boxes stitched into the page. Sequential
single-image calls — the proven-working shape (the multi-image prompts
spiral at the 8000-token budget).

Usage: eval_crop_grid.py <batch_id> <page> [--cols N] [--rows N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from time import monotonic
from typing import Any

from PIL import Image

from tools.box import overlap
from tools.eval_geometry import CropReading, assemble_crop_grid, grid_crops
from tools.layout import load_layout_store
from tools.loft_paths import WORK_DIR
from tools.pipeline_store import PipelineStore
from tools.text import normalize
from tools.vlm import (
    DEFAULT_BASE_URL,
    VlmError,
    parse_transcription_response,
    transcribe_image_vlm,
    transcription_system_with_context,
)


def _content_bounds(layout: dict[str, Any]) -> tuple[float, float, float, float]:
    """The ink extent: the layout's boxed lines + the unmatched
    detections — the crops cover the letter, never the blank margins."""
    xs: list[float] = []
    ys: list[float] = []
    for line in layout.get("lines", []):
        if line.get("box"):
            xs += [line["box"][0], line["box"][2]]
            ys += [line["box"][1], line["box"][3]]
    for u in layout.get("unmatched", []):
        if u.get("box"):
            xs += [u["box"][0], u["box"][2]]
            ys += [u["box"][1], u["box"][3]]
    return min(xs), min(ys), max(xs), max(ys)


# lucidlint: ignore long-param-list the crop read's inputs are the run's locals — no class for one call site
def read_crop(
    crop: CropReading,
    image_path: Path,
    tmp: Path,
    index: int,
    model: str,
    base_url: str,
    api_key: str | None,
) -> tuple[list[dict[str, Any]], int] | None:
    """Read ONE crop with the VLM — the text + the crop-local boxes.
    When the upright read's boxes are TALLER than wide (the text is
    vertical — a postcard message), the crop is rotated +90° so the
    text is horizontal and re-read; the boxes are remapped back into
    the crop frame. None when the call failed or the model gave no
    geometry. Returns (the lines, the token usage)."""
    box = (int(crop.x), int(crop.y), int(crop.x + crop.w), int(crop.y + crop.h))
    crop_path = tmp / f"crop-{index}.png"
    with Image.open(image_path) as im:
        im.crop(box).save(crop_path)
    t0 = monotonic()
    try:
        text, usage = transcribe_image_vlm(
            crop_path,
            model=model,
            system=transcription_system_with_context(),
            base_url=base_url,
            api_key=api_key,
            # the crop read's completion is ~1-4k tokens; 64000 (the
            # full-page location budget) EXCEEDS the glm-4.5v's 65536
            # context once the image is in — the 400 (2026-08-22)
            max_tokens=8000,
        )
        plain, boxes = parse_transcription_response(text)
    except (VlmError, ValueError, KeyError, IndexError, TypeError) as exc:
        print(f"crop {index} FAILED: {str(exc)[:120]}", file=sys.stderr)
        return None
    tokens = int(usage.get("total_tokens", 0) or 0)
    if boxes is None:
        print(f"crop {index}: no geometry from the model", file=sys.stderr)
        return None
    if _vertical_boxes(boxes):
        rotated = tmp / f"crop-{index}-rot.png"
        with Image.open(crop_path) as im:
            im.rotate(90, expand=True).save(rotated)
        usage2: dict[str, int] = {}
        try:
            text2, usage2 = transcribe_image_vlm(
                rotated,
                model=model,
                system=transcription_system_with_context(),
                base_url=base_url,
                api_key=api_key,
                max_tokens=8000,
            )
            plain2, boxes2 = parse_transcription_response(text2)
        # lucidlint: ignore swallow a failed re-read keeps the upright read (the fallback)
        except (VlmError, ValueError, KeyError, IndexError, TypeError) as exc:
            print(f"crop {index} rotated read FAILED: {str(exc)[:120]}", file=sys.stderr)
            plain2, boxes2 = None, None
        if boxes2 and plain2:
            # the +90 rotation's inverse: the rotated frame's height is
            # the crop's width (pinned empirically 2026-08-22)
            rot_h = int(crop.w)
            boxes2 = {li: remap_rotated(b, int(crop.h), rot_h) for li, b in boxes2.items()}
            plain, boxes, tokens = plain2, boxes2, tokens + int(usage2.get("total_tokens", 0) or 0)
            print(f"crop {index}: vertical text — rotated +90 and re-read", file=sys.stderr)
    if plain is None:
        print(f"crop {index}: no readable text", file=sys.stderr)
        return None
    lines = [{"text": plain.split("\n")[li], "box": boxes[li], "orientation": 0} for li in sorted(boxes)]
    print(
        f"crop {index} ({box[0]},{box[1]}) {crop.w:.0f}x{crop.h:.0f}: {len(lines)} lines, "
        f"{monotonic() - t0:.1f}s, {tokens} tokens",
        file=sys.stderr,
    )
    return (lines, tokens)


def _vertical_boxes(boxes: dict[int, list[float]]) -> bool:
    """The crop's boxes are taller than wide — the text is vertical
    (the postcard's message); the crop needs the +90° rotation."""
    if not boxes:
        return False
    hs = sorted(b[3] - b[1] for b in boxes.values())
    ws = sorted(b[2] - b[0] for b in boxes.values())
    return hs[len(hs) // 2] > ws[len(ws) // 2] * 1.2


def remap_rotated(box: list[float], rot_w: int, rot_h: int) -> list[float]:
    """The NORMALIZED box (0-1000) in the +90-rotated frame -> the
    original crop frame's pixels. The +90 rotation maps (x, y) -> (y,
    H' - x); the inverse is x = H' - y', y = x'. The normalized box
    must scale to the rotated frame's pixels FIRST — the 2026-08-22
    bug used the normalized y' directly against the pixel height, and
    the message's strips landed ~1000px off. The x-order flips too
    (the panel's x increases as the rotated frame's y decreases)."""
    x0n, y0n, x1n, y1n = box
    return [
        rot_h - (y1n / 1000) * rot_h,
        (x0n / 1000) * rot_w,
        rot_h - (y0n / 1000) * rot_h,
        (x1n / 1000) * rot_w,
    ]


def _anchor_agreement(assembled: dict[str, Any], layout: dict[str, Any]) -> tuple[list[float], int]:
    """The crop-grid's boxes vs the current pipeline's rec-ink boxes:
    the same model's text, so the normalized-text matching is reliable.
    Returns (the IoUs, the matched count)."""
    ious: list[float] = []
    matched = 0
    for current in layout.get("lines", []):
        if not current.get("box"):
            continue
        match = next((ln for ln in assembled["lines"] if normalize(ln["text"]) == normalize(current["text"])), None)
        if match and match.get("box"):
            ious.append(overlap(match["box"], current["box"]))
            matched += 1
    return ious, matched


# lucidlint: ignore long-param-list the crop-grid run's inputs are the page's state — no class for one call site
def run(
    batch_id: str,
    page: str,
    work_dir: Path,
    cols: int = 2,
    rows: int = 3,
    model: str = "dynamic/image",
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Read the page's crops, stitch, and report. Returns the report
    dict (the run's record — the geometry experiment's ledger)."""
    image_path = work_dir / batch_id / "oriented" / f"{page}.jpg"
    store = PipelineStore(work_dir)
    layout = load_layout_store(store, f"{batch_id}/ocr-guess/{page}.layout.json")
    with Image.open(image_path) as im:
        width, height = im.size
    bx0, by0, bx1, by1 = _content_bounds(layout)
    crops = grid_crops(bx1 - bx0, by1 - by0, cols, rows)
    for crop in crops:
        crop.x += bx0
        crop.y += by0
    tokens = 0
    failed = 0
    started = monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        for i, crop in enumerate(crops):
            read = read_crop(crop, image_path, Path(tmp), i, model, base_url, api_key)
            if read is None:
                failed += 1
                continue
            crop.lines, used = read
            tokens += used
    elapsed = monotonic() - started
    assembled = assemble_crop_grid(crops, page, width, height)
    boxless = [ln for ln in assembled["lines"] if not ln.get("box")]
    ious, matched = _anchor_agreement(assembled, layout)
    current_boxed = len([line for line in layout.get("lines", []) if line.get("box")])
    report = {
        "page": page,
        "cols": cols,
        "rows": rows,
        "crops": len(crops),
        "failed_crops": failed,
        "lines": len(assembled["lines"]),
        "boxless": len(boxless),
        "tokens": tokens,
        "elapsed_s": round(elapsed, 1),
        "mean_iou_vs_current": round(sum(ious) / len(ious), 3) if ious else None,
        "matched_lines": matched,
        "current_boxed": current_boxed,
    }
    # the model-scoped saves — the trial runs several models on the same
    # page; each keeps its own assembled layout + report
    slug = model.replace("/", "-").replace("@", "")
    out = work_dir / batch_id / "ocr-guess" / f"{page}.cropgrid-{slug}.json"
    out.write_text(json.dumps(assembled, indent=1, ensure_ascii=False), encoding="utf-8")
    report_path = work_dir / batch_id / "ocr-guess" / f"{page}.cropgrid-report-{slug}.json"
    report_path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval_crop_grid", description="The crop-grid experiment's real run")
    parser.add_argument("batch_id")
    parser.add_argument("page")
    parser.add_argument("--cols", type=int, default=2)
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR)
    parser.add_argument("--model", default="dynamic/image", help="the model to trial")
    parser.add_argument("--base-url", default=None, help="the API base (default: the gateway)")
    parser.add_argument(
        "--api-key",
        default=None,
        help="the API key (default: the gateway token; set OPENROUTER_API_KEY for OpenRouter)",
    )
    args = parser.parse_args(argv)
    report = run(
        args.batch_id,
        args.page,
        args.work_dir,
        args.cols,
        args.rows,
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key or os.environ.get("OPENROUTER_API_KEY"),
    )
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
