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
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic
from typing import Any, Literal

from PIL import Image

from document.rectangle import Rectangle
from pipeline.artefacts import BatchArtefacts
from pipeline.evals.eval_geometry import CropLine, CropReading, PageSize, assemble_crop_grid, grid_crops
from pipeline.layout import Layout, load_layout_store
from pipeline.layout_line import LayoutLine
from pipeline.model.config import ModelConfig
from pipeline.model.transcription import Transcription
from pipeline.model.vlm import (
    VlmError,
    VlmOptions,
    VlmPrompts,
    parse_transcription_response,
    transcribe_image_vlm,
)
from pipeline.store import PipelineStore
from pipeline.unmatched_line import UnmatchedLine
from tools.box import overlap
from tools.loft_paths import LoftPaths
from tools.text import normalize

# What a vision read means when the caller states nothing: the vision model's
# options at the client's gateway endpoint, with the client's own key rule
# (``find_api_key``). Named here so the call site says it, and a reader need
# not open VlmOptions to learn what a bare options object means.
DEFAULT_VISION_OPTIONS = VlmOptions()


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
class ReadFailure:
    """Why a crop's read did not land: the call died, or its answer did not
    parse — and what the error said. The kind is a field, not a prefix inside
    the message, so the run can tell a dead call from a bad answer without
    reading prose, and a failure cannot be carried without one."""

    kind: Literal["call", "answer"]
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail}"


@dataclass(frozen=True)
class CropRead:
    """One crop's read: the crop-local lines it yielded, what the read cost
    (both reads' tokens when the crop was rotated and re-read), and the
    rotated re-read's failure when that read did not land — the lines are the
    upright read's then, and the caller is told why."""

    lines: list[CropLine]
    tokens: int
    failure: ReadFailure | None = None


@dataclass(frozen=True)
class _Reading:
    """One crop's text as a read yielded it, before the lines are cut: the text,
    the box each of its lines sits in (the crop's frame), what the read cost,
    whether the text is vertical on the page (the +90 re-read's is), and the
    re-read's failure when it did not land. Every branch of the read returns
    one of these, so the crop's text, boxes, cost and orientation cannot
    diverge."""

    text: str
    boxes: dict[int, list[float]]
    tokens: int
    vertical: bool = False
    failure: ReadFailure | None = None


@dataclass(frozen=True)
class RotatedRead:
    """A rotated crop's re-read: the transcription it landed on and what the
    call cost, or the failure that kept it from landing. The failure is a
    value, never an exception, because the read's fallback is the upright read
    the caller already holds — a caller that never learns the re-read failed
    would read a vertical crop as if it had been re-read."""

    reading: Transcription | None
    tokens: int
    failure: ReadFailure | None


def _crop_read_options(page_options: VlmOptions) -> VlmOptions:
    """The crop read's config, derived from the caller's page config: the
    transcription context prompt (the known names and places help the read) and
    the crop read's own completion budget. A crop answers with the lines inside
    it — a few thousand tokens — so it does not read with the page's system
    prompt or the page-location budget (``VlmOptions.max_tokens``, 64000), which
    is sized for the full-page location call and on a 64k-context model leaves
    the image no room at all."""
    return replace(page_options, system=VlmPrompts.transcription_system_with_context(), max_tokens=8000)


def _read_rotated(path: Path, options: VlmOptions) -> RotatedRead:
    """The rotated crop's re-read: its transcription and cost, or the call's
    failure. The failure is returned, not raised, because the read's fallback
    is the upright read the caller already holds — a caller that never learns
    the re-read failed would read a vertical crop as if it had been re-read.

    The call's failures are ``VlmError`` (the module's contract). The parse
    cannot fail: ``parse_transcription_response`` returns a value for every
    answer — plain text when the model wrote no JSON, no boxes when it measured
    none (its own docstring) — so a raise from it is a bug in this module and
    propagates rather than reading as a model failure."""
    try:
        answer = options.run(transcribe_image_vlm, path)
    except VlmError as exc:
        return RotatedRead(reading=None, tokens=0, failure=ReadFailure("call", f"{type(exc).__name__}: {exc}"))
    return RotatedRead(reading=parse_transcription_response(answer.answer), tokens=answer.usage.tokens, failure=None)


def _fail_crop_read(index: int, reason: str) -> None:
    """A crop that cannot yield lines: log why and end the read — the
    returned None is the caller's failed value."""
    print(f"crop {index}: {reason}", file=sys.stderr)
    return None


def _crop_image(image_path: Path, crop: CropReading, crop_path: Path) -> None:
    """The crop's own image, cut from the page and saved — the call reads a file."""
    box = (int(crop.x), int(crop.y), int(crop.x + crop.w), int(crop.y + crop.h))
    with Image.open(image_path) as im:
        im.crop(box).save(crop_path)


def _rotated_image(crop_path: Path, rotated_path: Path) -> None:
    """The crop image turned +90°, so its vertical text reads horizontally —
    saved beside the upright crop, since the re-read is a call like the first."""
    with Image.open(crop_path) as im:
        im.rotate(90, expand=True).save(rotated_path)


def _crop_lines(reading: _Reading) -> list[CropLine]:
    """The read's lines: its text split by the model's line indexes, each in the
    box it was given, carrying the orientation the read found — the +90
    re-read's lines are vertical on the page, the upright read's are not."""
    orientation = 90 if reading.vertical else 0
    return [
        CropLine(text=reading.text.split("\n")[index], box=reading.boxes[index], orientation=orientation)
        for index in sorted(reading.boxes)
    ]


def _rotated_reading(crop: CropReading, rotated_path: Path, options: VlmOptions, upright: _Reading) -> _Reading:
    """The vertical crop's re-read: the re-read's horizontal reading when it
    lands, or the upright one carrying the failure that kept it from landing.
    Both calls' tokens are the read's cost — the re-read that answered and
    measured nothing still cost them."""
    rotated = _read_rotated(rotated_path, options)
    cost = replace(upright, tokens=upright.tokens + rotated.tokens)
    if rotated.reading is None:
        return replace(cost, failure=rotated.failure)
    if not (rotated.reading.boxes and rotated.reading.text):
        # the re-read answered but measured nothing usable: the upright read
        # stands in, and the result says so
        return replace(cost, failure=ReadFailure("answer", "the rotated read gave no usable lines"))
    # the +90 rotation's inverse: the rotated frame's height is the crop's
    # width (pinned empirically)
    rot_h = int(crop.w)
    boxes = {line: remap_rotated(box, int(crop.h), rot_h) for line, box in rotated.reading.boxes.items()}
    return _Reading(rotated.reading.text, boxes, cost.tokens, vertical=True)


def read_crop(
    crop: CropReading,
    image_path: Path,
    tmp: Path,
    index: int,
    page_options: VlmOptions,
) -> CropRead | None:
    """Read ONE crop with the VLM — the text + the crop-local boxes.
    When the upright read's boxes are TALLER than wide (the text is
    vertical — a postcard message), the crop is rotated +90° so the
    text is horizontal and re-read; the boxes are remapped back into
    the crop frame. None when the call failed or the model gave no
    geometry. A rotated re-read that does not land leaves the upright
    read in place and its failure on the result (``CropRead.failure``).

    ``page_options`` is the caller's page read config; the crop read states
    its own (``_crop_read_options``)."""
    crop_path = tmp / f"crop-{index}.png"
    _crop_image(image_path, crop, crop_path)
    options = _crop_read_options(page_options)
    t0 = monotonic()
    try:
        answer = options.run(transcribe_image_vlm, crop_path)
        transcription = parse_transcription_response(answer.answer)
    except (VlmError, ValueError, KeyError, IndexError, TypeError) as exc:
        print(f"crop {index} FAILED: {str(exc)[:120]}", file=sys.stderr)
        return None
    if transcription.boxes is None:
        return _fail_crop_read(index, "no geometry from the model")
    reading = _Reading(transcription.text, transcription.boxes, answer.usage.tokens)
    if _vertical_boxes(reading.boxes):
        rotated_path = tmp / f"crop-{index}-rot.png"
        _rotated_image(crop_path, rotated_path)
        print(f"crop {index}: vertical text — rotated +90 and re-read", file=sys.stderr)
        reading = _rotated_reading(crop, rotated_path, options, reading)
    if not reading.text:
        return _fail_crop_read(index, "no readable text")
    lines = _crop_lines(reading)
    print(
        f"crop {index} ({int(crop.x)},{int(crop.y)}) {crop.w:.0f}x{crop.h:.0f}: {len(lines)} lines, "
        f"{monotonic() - t0:.1f}s, {reading.tokens} tokens",
        file=sys.stderr,
    )
    return CropRead(lines=lines, tokens=reading.tokens, failure=reading.failure)


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
    """The crop-grid run's ledger: how the page was read, what failed (a crop,
    or a rotated re-read whose upright read stood in), what it cost, and how
    the stitched boxes agree with the current layout."""

    page: str
    cols: int
    rows: int
    crops: int
    failed_crops: int
    re_read_failures: list[str]
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
            "re_read_failures": self.re_read_failures,
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
    options: VlmOptions | None = None,
) -> CropGridReport:
    """Read the page's crops, stitch, and report — the geometry
    experiment's ledger for one page. ``options`` is the page read's config;
    None is the vision model's options at the gateway's default endpoint and
    the client's own key rule (``find_api_key``). Each crop read states its own
    config from it (``_crop_read_options``)."""
    read_options = options or DEFAULT_VISION_OPTIONS
    image_path = BatchArtefacts(work_dir, batch_id).oriented(f"{page}.jpg")
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
    re_read_failures: list[str] = []
    started = monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        for i, crop in enumerate(crops):
            read = read_crop(crop, image_path, Path(tmp), i, read_options)
            if read is None:
                failed += 1
                continue
            if read.failure is not None:
                re_read_failures.append(f"crop {i}: {read.failure}")
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
        re_read_failures=re_read_failures,
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
    artefacts = BatchArtefacts(work_dir, batch_id)
    out = artefacts.guess_dir / f"{page}.cropgrid-{read_options.model_slug}.json"
    out.write_text(json.dumps(assembled.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    report_path = artefacts.guess_dir / f"{page}.cropgrid-report-{read_options.model_slug}.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval_crop_grid", description="The crop-grid experiment's real run")
    parser.add_argument("batch_id")
    parser.add_argument("page")
    parser.add_argument("--cols", type=int, default=2)
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument("--work-dir", type=Path, default=LoftPaths.WORK_DIR)
    parser.add_argument("--model", default=ModelConfig.VISION_MODEL, help="the model to trial")
    parser.add_argument("--base-url", default=None, help="the API base (default: the gateway)")
    parser.add_argument(
        "--api-key",
        default=None,
        help="the API key (default: the gateway token; set OPENROUTER_API_KEY for OpenRouter)",
    )
    args = parser.parse_args(argv)
    options = VlmOptions(
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key or os.environ.get("OPENROUTER_API_KEY"),
    )
    report = run(args.batch_id, args.page, args.work_dir, args.cols, args.rows, options)
    print(json.dumps(report.to_dict(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
