"""The crop-grid experiment's real run (Phase 2): one page
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
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from PIL import Image

from document.rectangle import Rectangle
from pipeline.evals.eval_geometry import CropLine, CropReading, PageSize, assemble_crop_grid, grid_crops
from pipeline.layout import Layout, load_layout_store
from pipeline.layout_line import LayoutLine
from pipeline.model.transcription import Transcription
from pipeline.model.vlm import (
    DEFAULT_BASE_URL,
    VlmError,
    parse_transcription_response,
    transcribe_image_vlm,
    transcription_system_with_context,
)
from pipeline.model.vlm_answer import VlmAnswer
from pipeline.store import PipelineStore
from pipeline.unmatched_line import UnmatchedLine
from tools.box import overlap
from tools.loft_paths import WORK_DIR
from tools.text import normalize


def _accumulate_bounds(xs: list[float], ys: list[float], item: LayoutLine | UnmatchedLine) -> None:
    """One boxed record's ink extent joins the bounds accumulators."""
    if item.box:
        xs += [item.box[0], item.box[2]]
        ys += [item.box[1], item.box[3]]


def _content_bounds(layout: Layout) -> Rectangle:
    """The ink extent: the layout's boxed lines + the unmatched
    detections — the crops cover the letter, never the blank margins."""
    xs: list[float] = []
    ys: list[float] = []
    for line in layout.lines:
        _accumulate_bounds(xs, ys, line)
    for unmatched in layout.unmatched:
        _accumulate_bounds(xs, ys, unmatched)
    return Rectangle(min(xs), min(ys), max(xs), max(ys))


@dataclass(frozen=True)
class CropRead:
    """One crop's read: the crop-local lines it yielded and what the read
    cost (both reads' tokens when the crop was rotated and re-read)."""

    lines: list[CropLine]
    tokens: int


def _read_transcription(path: Path, model: str, base_url: str, api_key: str | None) -> VlmAnswer:
    """The VLM call for one crop image (upright or rotated): the model's
    answer and what the call cost."""
    return transcribe_image_vlm(
        path,
        model=model,
        system=transcription_system_with_context(),
        base_url=base_url,
        api_key=api_key,
        # the crop read's completion is ~1-4k tokens; 64000 (the
        # full-page location budget) EXCEEDS the glm-4.5v's 65536
        # context once the image is in.
        max_tokens=8000,
    )


def _fail_crop_read(index: int, reason: str) -> None:
    """A crop that cannot yield lines: log why and end the read — the
    returned None is the caller's failed value."""
    print(f"crop {index}: {reason}", file=sys.stderr)
    return None


def read_crop(
    crop: CropReading,
    image_path: Path,
    tmp: Path,
    index: int,
    model: str,
    base_url: str,
    api_key: str | None,
) -> CropRead | None:
    """Read ONE crop with the VLM — the text + the crop-local boxes.
    When the upright read's boxes are TALLER than wide (the text is
    vertical — a postcard message), the crop is rotated +90° so the
    text is horizontal and re-read; the boxes are remapped back into
    the crop frame. None when the call failed or the model gave no
    geometry."""
    box = (int(crop.x), int(crop.y), int(crop.x + crop.w), int(crop.y + crop.h))
    crop_path = tmp / f"crop-{index}.png"
    with Image.open(image_path) as im:
        im.crop(box).save(crop_path)
    t0 = monotonic()
    try:
        answer = _read_transcription(crop_path, model, base_url, api_key)
        reading = parse_transcription_response(answer.answer)
    except (VlmError, ValueError, KeyError, IndexError, TypeError) as exc:
        print(f"crop {index} FAILED: {str(exc)[:120]}", file=sys.stderr)
        return None
    tokens = answer.usage.tokens
    if reading.boxes is None:
        return _fail_crop_read(index, "no geometry from the model")
    text, boxes = reading.text, reading.boxes
    rotated_ok = False
    if _vertical_boxes(boxes):
        rotated = tmp / f"crop-{index}-rot.png"
        with Image.open(crop_path) as im:
            im.rotate(90, expand=True).save(rotated)
        # the answer and its parse travel as one pair: a failed re-read leaves
        # NOTHING behind, so the upright read's answer is never paired with a
        # parse that did not happen (the fallback is the upright read)
        rotated_read: tuple[VlmAnswer, Transcription] | None = None
        try:
            answer2 = _read_transcription(rotated, model, base_url, api_key)
            rotated_read = (answer2, parse_transcription_response(answer2.answer))
        # lucidlint: ignore swallow a failed re-read keeps the upright read (the fallback)
        except (VlmError, ValueError, KeyError, IndexError, TypeError) as exc:
            print(f"crop {index} rotated read FAILED: {str(exc)[:120]}", file=sys.stderr)
        if rotated_read is not None:
            answer2, reading2 = rotated_read
            if reading2.boxes and reading2.text:
                # the +90 rotation's inverse: the rotated frame's height is
                # the crop's width (pinned empirically)
                rot_h = int(crop.w)
                boxes = {li: remap_rotated(b, int(crop.h), rot_h) for li, b in reading2.boxes.items()}
                text, tokens = reading2.text, tokens + answer2.usage.tokens
                rotated_ok = True
                print(f"crop {index}: vertical text — rotated +90 and re-read", file=sys.stderr)
    if not text:
        return _fail_crop_read(index, "no readable text")
    # the rotated re-read's lines carry the crop's text orientation: the
    # +90 rotation makes them horizontal for the read, and the page-frame
    # consumer needs to know they are vertical on the page
    orientation = 90 if rotated_ok else 0
    lines = [CropLine(text=text.split("\n")[li], box=boxes[li], orientation=orientation) for li in sorted(boxes)]
    print(
        f"crop {index} ({box[0]},{box[1]}) {crop.w:.0f}x{crop.h:.0f}: {len(lines)} lines, "
        f"{monotonic() - t0:.1f}s, {tokens} tokens",
        file=sys.stderr,
    )
    return CropRead(lines=lines, tokens=tokens)


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
    must scale to the rotated frame's pixels FIRST. The x-order flips
    too (the panel's x increases as the rotated frame's y decreases)."""
    x0n, y0n, x1n, y1n = box
    return [
        rot_h - (y1n / 1000) * rot_h,
        (x0n / 1000) * rot_w,
        rot_h - (y0n / 1000) * rot_h,
        (x1n / 1000) * rot_w,
    ]


@dataclass(frozen=True)
class AnchorAgreement:
    """How the crop-grid's boxes agree with the current pipeline's boxes:
    the per-line IoUs and how many lines matched."""

    ious: list[float]
    matched: int

    @property
    def mean_iou(self) -> float | None:
        """The mean IoU over the matched lines — None when none matched."""
        return round(sum(self.ious) / len(self.ious), 3) if self.ious else None


def _anchor_agreement(assembled: Layout, layout: Layout) -> AnchorAgreement:
    """The crop-grid's boxes vs the current pipeline's rec-ink boxes:
    the same model's text, so the normalized-text matching is reliable."""
    ious: list[float] = []
    matched = 0
    for current in layout.lines:
        if not current.box:
            continue
        match = next((line for line in assembled.lines if normalize(line.text) == normalize(current.text)), None)
        if match and match.box:
            ious.append(overlap(match.box, current.box))
            matched += 1
    return AnchorAgreement(ious=ious, matched=matched)


@dataclass(frozen=True)
class CropGridReport:
    """The crop-grid run's ledger: how the page was read, what failed, what
    it cost, and how the stitched boxes agree with the current layout."""

    page: str
    cols: int
    rows: int
    crops: int
    failed_crops: int
    lines: int
    boxless: int
    tokens: int
    elapsed_s: float
    mean_iou_vs_current: float | None
    matched_lines: int
    current_boxed: int

    def to_dict(self) -> dict[str, Any]:
        """The report as its JSON record."""
        return {
            "page": self.page,
            "cols": self.cols,
            "rows": self.rows,
            "crops": self.crops,
            "failed_crops": self.failed_crops,
            "lines": self.lines,
            "boxless": self.boxless,
            "tokens": self.tokens,
            "elapsed_s": self.elapsed_s,
            "mean_iou_vs_current": self.mean_iou_vs_current,
            "matched_lines": self.matched_lines,
            "current_boxed": self.current_boxed,
        }


def run(
    batch_id: str,
    page: str,
    work_dir: Path,
    cols: int = 2,
    rows: int = 3,
    model: str = "dynamic/image",
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
) -> CropGridReport:
    """Read the page's crops, stitch, and report — the geometry
    experiment's ledger for one page."""
    image_path = work_dir / batch_id / "oriented" / f"{page}.jpg"
    store = PipelineStore(work_dir)
    layout = load_layout_store(store, f"{batch_id}/ocr-guess/{page}.layout.json")
    with Image.open(image_path) as im:
        width, height = im.size
    bounds = _content_bounds(layout)
    crops = grid_crops(PageSize(bounds.x1 - bounds.x0, bounds.y1 - bounds.y0), cols, rows)
    for crop in crops:
        crop.x += bounds.x0
        crop.y += bounds.y0
    tokens = 0
    failed = 0
    started = monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        for i, crop in enumerate(crops):
            read = read_crop(crop, image_path, Path(tmp), i, model, base_url, api_key)
            if read is None:
                failed += 1
                continue
            crop.lines = read.lines
            tokens += read.tokens
    elapsed = monotonic() - started
    assembled = assemble_crop_grid(crops, page, PageSize(width, height))
    boxless = [line for line in assembled.lines if not line.box]
    agreement = _anchor_agreement(assembled, layout)
    current_boxed = len([line for line in layout.lines if line.box])
    report = CropGridReport(
        page=page,
        cols=cols,
        rows=rows,
        crops=len(crops),
        failed_crops=failed,
        lines=len(assembled.lines),
        boxless=len(boxless),
        tokens=tokens,
        elapsed_s=round(elapsed, 1),
        mean_iou_vs_current=agreement.mean_iou,
        matched_lines=agreement.matched,
        current_boxed=current_boxed,
    )
    # the model-scoped saves — the trial runs several models on the same
    # page; each keeps its own assembled layout + report
    slug = model.replace("/", "-").replace("@", "")
    out = work_dir / batch_id / "ocr-guess" / f"{page}.cropgrid-{slug}.json"
    out.write_text(json.dumps(assembled.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    report_path = work_dir / batch_id / "ocr-guess" / f"{page}.cropgrid-report-{slug}.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
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
    print(json.dumps(report.to_dict(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
