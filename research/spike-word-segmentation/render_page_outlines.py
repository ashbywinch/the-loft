"""The whole page as the new pipeline reads it: every word and every row, each
box in its own colour with its number on it.

Both views are drawn by the house numbering renderer (tools/word_numbering.py),
from a pipeline run's own output (boxes.json, words.json) — never hand-copied
numbers. Numbers are the reading order: top to bottom, left to right.
Usage: .venv/bin/python research/spike-word-segmentation/render_page_outlines.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from tools.page_visuals import captioned_sheet, review_image
from tools.word_numbering import render_numbered, unplaced

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
DATA = Path("/tmp/newpipe")
OUT = Path(__file__).resolve().parent / "evidence"


def _words() -> list[tuple[float, float, float, float]]:
    """Every word box the pipeline measured, in page px."""
    words = json.loads((DATA / "words.json").read_text())["words"]
    return [(w["x0"], w["y0"], w["x1"], w["y1"]) for w in words]


def _rows() -> list[tuple[float, float, float, float]]:
    """Every row box: each polygon as its bounding rectangle in page px."""
    boxes = json.loads((DATA / "boxes.json").read_text())["boxes"]
    return [
        (min(px for px, _ in box), min(py for _, py in box), max(px for px, _ in box), max(py for _, py in box))
        for box in boxes
    ]


def _draw(path: Path, title: str, boxes: list[tuple[float, float, float, float]]) -> None:
    """The whole page with every box numbered and coloured, plus a review copy.

    One image, not panels: a caption bar or a gap between stacked panels lands
    inside the writing and reads as a white box across the page (user,
    2026-09-16)."""
    page = Image.open(SCAN).convert("RGB")
    section = (0.0, 0.0, float(page.width), float(page.height))
    image, chips = render_numbered(page, section, boxes, 1.0)
    sheet, _draw_handle, _bar = captioned_sheet(image, [title, f"{len(boxes)} boxes, numbered in reading order"])
    sheet.save(path.with_suffix(".png"))
    path.write_bytes(review_image(sheet, width=1400, quality=74))
    missing = unplaced(chips)
    print(f"{path.name} -> {path} ({path.stat().st_size // 1024}KB); {len(boxes)} boxes, {len(missing)} chips unplaced")


def _draw_half(path: Path, title: str, boxes: list, fy0: float, fy1: float, scale: float = 2.0) -> None:
    """One half of the page as its own file, boxes numbered within the half.

    Separate files, never a stack: a stacked panel's caption bar and gap land
    inside the writing. Halving the page also gives the numbering room — at
    whole-page density the chip placer runs out of free space."""
    page = Image.open(SCAN).convert("RGB")
    y0, y1 = fy0 * page.height, fy1 * page.height
    section = (0.0, y0, float(page.width), y1)
    inside = [b for b in boxes if b[3] >= y0 and b[1] <= y1]
    image, chips = render_numbered(page, section, inside, scale)
    sheet, _handle, _bar = captioned_sheet(image, [title, f"{len(inside)} boxes, numbered in reading order"])
    sheet.save(path.with_suffix(".png"))
    path.write_bytes(review_image(sheet, width=1400, quality=74))
    print(f"{path.name} -> {path.stat().st_size // 1024}KB; {len(inside)} boxes, {len(unplaced(chips))} chips unplaced")


def _main() -> int:
    for name, title, boxes in (
        ("page-words", "the whole page — every WORD boxed, numbered", _words()),
        ("page-rows", "the whole page — every ROW boxed, numbered", _rows()),
    ):
        _draw(OUT / f"{name}.jpg", title, boxes)
        _draw_half(OUT / f"{name}-top.jpg", f"{title} (top half)", boxes, 0.0, 0.5)
        _draw_half(OUT / f"{name}-bottom.jpg", f"{title} (bottom half)", boxes, 0.5, 1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
