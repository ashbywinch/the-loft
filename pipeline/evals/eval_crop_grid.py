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
from pipeline.model.transcription import TranscribedLine
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
# options at the client's gateway endpoint. The key is None, so each call
# resolves it through the client's own rule (``find_api_key``) — the constant
# holds no credential. Named here so the call site says it, and a reader need
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
    """Why a crop's read did not land: the image could not be opened, cut or
    rotated (``image``), the call died (``call``), or the answer carried no
    usable read (``answer``) — and what the failure said. The kind is a field,
    not a prefix inside the message, so the run can tell a dead call from a bad
    answer without reading prose, and a failure cannot be carried without one.

    One value, two subjects, told apart by where it is held: as ``read_crop``'s
    return it is the crop's own failure — nothing was read; on
    ``CropRead.failure`` it is the rotated re-read's — the upright read stood
    in."""

    kind: Literal["image", "call", "answer"]
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail}"


@dataclass(frozen=True)
class CropRead:
    """One crop's read: the crop-local lines it yielded, what the read cost
    (both reads' tokens when the crop was rotated and re-read), and the
    rotated re-read's failure when that read did not land — the lines are the
    upright read's then, and the caller is told why."""

    # the read's completion budget: a crop answers with the lines inside it — a
    # few thousand tokens; the page options' budget is the location call's and
    # on a 64k-context model leaves the crop image no room at all
    _MAX_TOKENS = 8000

    lines: list[CropLine]
    tokens: int
    failure: ReadFailure | None = None


@dataclass(frozen=True)
class _RotatedCrop:
    """The crop image turned +90°, so its vertical text reads horizontally: the
    file the re-read sends, and that saved file's own pixel frame. The image and
    the frame travel as one value, so the re-read cannot send one image and
    measure its boxes in another — the frame is read back from the file, never
    re-derived from the crop's float bounds."""

    path: Path
    pixel_width: int
    pixel_height: int

    @classmethod
    def saved_at(cls, crop_path: Path, rotated_path: Path) -> _RotatedCrop:
        """The crop turned +90° and saved beside it — the re-read is a call, and
        a call reads a file. An unreadable crop or a save that did not land
        raises ``OSError``; ``read_crop`` owns the value."""
        with Image.open(crop_path) as im:
            im.rotate(90, expand=True).save(rotated_path)
        with Image.open(rotated_path) as im:
            return cls(rotated_path, im.width, im.height)


@dataclass(frozen=True)
class _Reading:
    """One crop's read as the model yielded it: its lines (each its own text and
    box in the crop's frame — ``Transcription.boxed_lines`` does the pairing, so
    no line here is boxless), what the read cost, whether the text runs
    vertically on the page (measured once from the boxes that show it, and true
    whichever read the lines come from), and the re-read's failure when it did
    not land. Every branch of the read returns one of these, so the crop's text,
    boxes, cost and orientation cannot diverge."""

    # × width: a line whose box is this much taller than wide is vertical text
    _VERTICAL_ASPECT_RATIO = 1.2

    lines: list[TranscribedLine]
    tokens: int
    vertical: bool = False
    failure: ReadFailure | None = None

    @classmethod
    def of(cls, lines: list[TranscribedLine], tokens: int) -> _Reading:
        """The upright read: its lines, its cost, and the orientation their
        boxes show — measured once here, so no later branch restates it."""
        return cls(lines=lines, tokens=tokens, vertical=cls._is_vertical(lines))

    @classmethod
    def _is_vertical(cls, lines: list[TranscribedLine]) -> bool:
        """The crop's lines sit in boxes taller than wide — the text is vertical
        (the postcard's message), so the crop needs the +90° rotation. Every
        line here carries the box it was measured in
        (``Transcription.boxed_lines``), so there is no boxless line to decide
        about. A median with a margin over 1 keeps a slightly slanted line's box
        from reading as vertical."""
        if not lines:
            return False
        heights = sorted(line.box[3] - line.box[1] for line in lines)
        widths = sorted(line.box[2] - line.box[0] for line in lines)
        return heights[len(heights) // 2] > widths[len(widths) // 2] * cls._VERTICAL_ASPECT_RATIO

    @property
    def orientation(self) -> int:
        """The text's direction on the page: 90 when the +90 re-read's boxes are
        vertical, 0 when it reads upright. The one place the boolean the boxes
        show becomes the angle a ``CropLine`` carries."""
        return 90 if self.vertical else 0


def _crop_read_options(page_options: VlmOptions) -> VlmOptions:
    """The crop read's config, derived from the caller's page config: the
    transcription context prompt (the known names and places help the read) and
    the crop read's own completion budget (``CropRead._MAX_TOKENS``). A crop
    answers with the lines inside it — a few thousand tokens — so it does not
    read with the page's system prompt or the page-location budget
    (``VlmOptions.max_tokens``, 64000), which is sized for the full-page
    location call and on a 64k-context model leaves the image no room at all.

    Everything else is the page config's and travels with it: the model, the
    endpoint (``page_options.endpoint``), the key, the ``user_text`` (a page
    instruction the caller gave is the caller's, not this module's to drop), the
    timeout, the urlopen seam. The crop read changes what it reads with, not
    what it reads. ``VlmOptions`` is frozen and every field is a scalar or a
    callable, so ``replace`` copies the config without aliasing mutable state."""
    return replace(
        page_options,
        system=VlmPrompts.transcription_system_with_context(),
        max_tokens=CropRead._MAX_TOKENS,
    )


def _failure(exc: OSError | VlmError) -> ReadFailure:
    """The failure one raised exception means: an image the crop could not
    open, cut or rotate (``OSError``) is an ``image`` failure; a call that did
    not answer (``VlmError``, the module's contract) is a ``call`` failure. The
    kind is the exception's type, never its prose."""
    detail = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, OSError):
        return ReadFailure(kind="image", detail=detail)
    return ReadFailure(kind="call", detail=detail)


def _crop_image(image_path: Path, crop: CropReading, crop_path: Path) -> None:
    """The crop's own image, cut from the page and saved at the crop's pixel
    rectangle — the call reads a file, not a rectangle. An unreadable page or a
    save that did not land raises ``OSError``; ``read_crop`` owns turning that
    into a value. No frame is derived from the float bounds: the only frame the
    read carries is the saved rotated file's own (``_RotatedCrop``)."""
    box = (int(crop.x), int(crop.y), int(crop.x + crop.w), int(crop.y + crop.h))
    with Image.open(image_path) as im:
        im.crop(box).save(crop_path)


def _crop_lines(reading: _Reading) -> list[CropLine]:
    """The read's lines as the crop's own: each already carries its text with
    the box it was measured in (``Transcription.boxed_lines`` — the pairing is
    the transcription's, never recomputed here), and gains the orientation the
    read found — the +90 re-read's lines are vertical on the page, the upright
    read's are not."""
    return [CropLine(text=line.text, box=line.box, orientation=reading.orientation) for line in reading.lines]


def _rotated_reading(rotated: _RotatedCrop, options: VlmOptions, upright: _Reading) -> _Reading:
    """The vertical crop's re-read: the re-read's horizontal lines when it
    lands, or the upright read carrying an ``answer`` failure when the re-read
    answered with nothing usable.

    The re-read raises — ``VlmError`` from the call, ``OSError`` from the
    rotation — into ``read_crop``, the read's one failure boundary, which
    already holds the upright read the failure falls back to; nothing is caught
    here. ``read_crop``'s catch is where those exceptions become the
    ``CropRead.failure`` value, so this function never invents a second
    boundary. A returned ``_Reading`` is a read that happened.

    The reading is the upright one carried forward (``replace``), so its
    verticality is the fact that sent the crop here, not restated: the lines
    stay vertical on the page whichever text wins, because the upright read's
    boxes are the tall ones that sent the crop here.

    ``options`` is the crop read's own config (``_crop_read_options``), never
    the page's: the re-read is another read of the same crop.

    ``parse_transcription_response`` has no failing arm — a malformed answer is
    a reading without boxes, not an exception — so the re-read's only expected
    failures are the call's and the rotation's.

    Both calls' tokens are the read's cost — the re-read that answered and
    measured nothing still cost them."""
    answer = options.run(transcribe_image_vlm, rotated.path)
    parsed = parse_transcription_response(answer.answer)
    tokens = upright.tokens + answer.usage.tokens
    lines = parsed.boxed_lines()
    if not lines:
        return _Reading(
            lines=upright.lines,
            tokens=tokens,
            vertical=upright.vertical,
            failure=ReadFailure(kind="answer", detail="the rotated read gave no usable lines"),
        )
    return _Reading(
        lines=[TranscribedLine(line.text, remap_rotated(line.box, rotated)) for line in lines],
        tokens=tokens,
        vertical=upright.vertical,
    )


def read_crop(
    crop: CropReading,
    image_path: Path,
    tmp: Path,
    index: int,
    page_options: VlmOptions,
) -> CropRead | ReadFailure:
    """Read ONE crop with the VLM — the text + the crop-local boxes.
    When the upright read's boxes are TALLER than wide (the text is
    vertical — a postcard message), the crop is rotated +90° so the
    text is horizontal and re-read; the boxes are remapped back into
    the crop frame.

    This function is the crop read's ONE failure boundary, and it has two catch
    sites because a crop has two reads: the upright read, then — when the boxes
    are vertical — the rotated re-read. Below both, the image helpers raise
    ``OSError`` and the model calls raise ``VlmError``; here either becomes a
    value, so no helper swallows and no caller catches. A failure of the
    upright read is the crop's own: a returned ``ReadFailure``, nothing was
    read. A failure of the re-read is not: the upright read stands in, and the
    returned ``CropRead`` carries the failure on ``CropRead.failure`` with its
    lines. A returned ``CropRead`` is always a read (at least one line).
    Nothing else is caught: ``parse_transcription_response`` has no failing arm,
    so a raise from it is a bug in this module and crashing is the correct
    report.

    ``page_options`` is the caller's page read config; the crop read states
    its own (``_crop_read_options``)."""
    # the call resolves the MIME type from the suffix, so the images it writes
    # and the names it passes name the one format
    crop_suffix = ".png"
    crop_path = tmp / f"crop-{index}{crop_suffix}"
    options = _crop_read_options(page_options)
    t0 = monotonic()
    try:
        _crop_image(image_path, crop, crop_path)
        answer = options.run(transcribe_image_vlm, crop_path)
    except (OSError, VlmError) as exc:
        print(f"crop {index} FAILED: {str(exc)[:120]}", file=sys.stderr)
        return _failure(exc)
    transcription = parse_transcription_response(answer.answer)
    if transcription.boxes is None:
        print(f"crop {index}: no geometry from the model", file=sys.stderr)
        return ReadFailure(kind="answer", detail="no geometry from the model")
    reading = _Reading.of(transcription.boxed_lines(), answer.usage.tokens)
    if reading.vertical:
        # the text runs vertically on the page — that is what sends the crop to
        # the +90 re-read, and it stays true whichever read the lines come from
        rotated_path = tmp / f"crop-{index}-rot{crop_suffix}"
        print(f"crop {index}: vertical text — rotated +90 and re-read", file=sys.stderr)
        try:
            rotated = _RotatedCrop.saved_at(crop_path, rotated_path)
            reading = _rotated_reading(rotated, options, reading)
        except (OSError, VlmError) as exc:
            # the upright read stands in; the result says why the re-read did not
            reading = replace(reading, failure=_failure(exc))
    lines = _crop_lines(reading)
    print(
        f"crop {index} ({int(crop.x)},{int(crop.y)}) {crop.w:.0f}x{crop.h:.0f}: {len(lines)} lines, "
        f"{monotonic() - t0:.1f}s, {reading.tokens} tokens",
        file=sys.stderr,
    )
    return CropRead(lines=lines, tokens=reading.tokens, failure=reading.failure)


def remap_rotated(box: list[float], frame: _RotatedCrop) -> list[float]:
    """A NORMALIZED box (0-1000), measured on the ROTATED crop, as pixels in the
    crop before it was turned.

    A +90° turn swaps the axes: the rotated frame's HEIGHT is the crop's width,
    and its width the crop's height. So the crop's x comes from the rotated
    height and its y from the rotated width — swapped on purpose, which is why
    this takes the frame as one value rather than two numbers a caller could
    pass in the wrong order.

    The turn maps (x, y) → (y, H − x), so the inverse is x = H − y', y = x'; the
    normalized box scales to the rotated frame's pixels first, and the x order
    flips because the panel's x rises as the rotated frame's y falls.
    """
    crop_width, crop_height = frame.pixel_height, frame.pixel_width
    x0, y0, x1, y1 = box
    return [
        crop_width - (y1 / 1000) * crop_width,
        (x0 / 1000) * crop_height,
        crop_width - (y0 / 1000) * crop_width,
        (x1 / 1000) * crop_height,
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


@dataclass(frozen=True)
class PageCropRun:
    """One page's crop-grid run: which batch and page, where the work lives, the
    grid, and the read's config — the six values every call site passes together."""

    batch_id: str
    page: str
    work_dir: Path
    cols: int = 2
    rows: int = 3
    options: VlmOptions | None = None


def run(request: PageCropRun) -> CropGridReport:
    """Read the page's crops, stitch, and report — the geometry
    experiment's ledger for one page. ``options`` is the page read's config;
    None is the vision model's options at the gateway's default endpoint and
    the client's own key rule (``find_api_key``). Each crop read states its own
    config from it (``_crop_read_options``)."""
    batch_id, page, work_dir = request.batch_id, request.page, request.work_dir
    cols, rows = request.cols, request.rows
    read_options = request.options or DEFAULT_VISION_OPTIONS
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
            if isinstance(read, ReadFailure):
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
    report = run(PageCropRun(args.batch_id, args.page, args.work_dir, args.cols, args.rows, options))
    print(json.dumps(report.to_dict(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
