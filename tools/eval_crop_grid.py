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
from tools.vlm import VlmError, parse_transcription_response, transcribe_image_vlm, transcription_system_with_context


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


def _read_crop(crop: CropReading, image_path: Path, tmp: Path, index: int) -> tuple[list[dict[str, Any]], int] | None:
    """Read ONE crop with the VLM — the text + the crop-local boxes.
    None when the call failed or the model gave no geometry. Returns
    (the lines, the token usage) on success."""
    box = (int(crop.x), int(crop.y), int(crop.x + crop.w), int(crop.y + crop.h))
    crop_path = tmp / f"crop-{index}.png"
    with Image.open(image_path) as im:
        im.crop(box).save(crop_path)
    t0 = monotonic()
    try:
        text, usage = transcribe_image_vlm(crop_path, system=transcription_system_with_context())
        plain, boxes = parse_transcription_response(text)
    except (VlmError, ValueError, KeyError, IndexError, TypeError) as exc:
        print(f"crop {index} FAILED: {str(exc)[:120]}", file=sys.stderr)
        return None
    tokens = int(usage.get("total_tokens", 0) or 0)
    if boxes is None:
        print(f"crop {index}: no geometry from the model", file=sys.stderr)
        return None
    lines = [{"text": plain.split("\n")[li], "box": boxes[li], "orientation": 0} for li in sorted(boxes)]
    print(
        f"crop {index} ({box[0]},{box[1]}) {crop.w:.0f}x{crop.h:.0f}: {len(lines)} lines, "
        f"{monotonic() - t0:.1f}s, {tokens} tokens",
        file=sys.stderr,
    )
    return (lines, tokens)


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


def run(batch_id: str, page: str, work_dir: Path, cols: int = 2, rows: int = 3) -> dict[str, Any]:
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
            read = _read_crop(crop, image_path, Path(tmp), i)
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
    # persist the assembled layout + the report — the experiment's record
    # (2026-08-22: the first run measured but did not save; the visual
    # comparison needs the actual boxes)
    out = work_dir / batch_id / "ocr-guess" / f"{page}.cropgrid.json"
    out.write_text(json.dumps(assembled, indent=1, ensure_ascii=False), encoding="utf-8")
    report_path = work_dir / batch_id / "ocr-guess" / f"{page}.cropgrid-report.json"
    report_path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval_crop_grid", description="The crop-grid experiment's real run")
    parser.add_argument("batch_id")
    parser.add_argument("page")
    parser.add_argument("--cols", type=int, default=2)
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR)
    args = parser.parse_args(argv)
    report = run(args.batch_id, args.page, args.work_dir, args.cols, args.rows)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
