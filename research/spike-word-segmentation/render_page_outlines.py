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
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from document.rectangle import Rectangle
from pipeline.rows.page_visuals import captioned_sheet, review_image
from tools.word_numbering import render_numbered, unplaced

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
if not SCAN.exists():
    raise SystemExit(f"render_* needs the adopt batch mounted - the scan is not at {SCAN}")
DATA = Path("/tmp/newpipe")
OUT = Path(__file__).resolve().parent / "evidence"


def _words() -> list[Rectangle]:
    """Every word box the pipeline measured, in page px."""
    words = json.loads((DATA / "words.json").read_text())["words"]
    return [Rectangle(x0=w["x0"], y0=w["y0"], x1=w["x1"], y1=w["y1"]) for w in words]


def _rows() -> list[Rectangle]:
    """Every row box: each polygon as its bounding rectangle in page px."""
    boxes = json.loads((DATA / "boxes.json").read_text())["boxes"]
    return [
        Rectangle(
            x0=min(px for px, _ in box),
            y0=min(py for _, py in box),
            x1=max(px for px, _ in box),
            y1=max(py for _, py in box),
        )
        for box in boxes
    ]


def _draw(path: Path, title: str, boxes: list[Rectangle]) -> None:
    """The whole page with every box numbered and coloured, plus a review copy.

    One image, not panels: a caption bar or a gap between stacked panels lands
    inside the writing and reads as a white box across the page (user,
    2026-09-16)."""
    page = Image.open(SCAN).convert("RGB")
    section = Rectangle(x0=0.0, y0=0.0, x1=float(page.width), y1=float(page.height))
    rendered = render_numbered(page, section, [(b.x0, b.y0, b.x1, b.y1) for b in boxes], 1.0)
    sheet = captioned_sheet(rendered.image, [title, f"{len(boxes)} boxes, numbered in reading order"])
    sheet.sheet.save(path.with_suffix(".png"))
    path.write_bytes(review_image(sheet.sheet, width=1400, quality=74))
    missing = unplaced(rendered.chips)
    print(f"{path.name} -> {path} ({path.stat().st_size // 1024}KB); {len(boxes)} boxes, {len(missing)} chips unplaced")


@dataclass(frozen=True)
class _Half:
    """One half of the page in its own file: its title, the vertical band of
    the page it covers, and the scale the boxes are drawn at."""

    title: str
    fy0: float
    fy1: float
    scale: float = 2.0


def _draw_half(path: Path, boxes: list[Rectangle], half: _Half) -> None:
    """One half of the page as its own file, boxes numbered within the half.

    Separate files, never a stack: a stacked panel's caption bar and gap land
    inside the writing. Halving the page also gives the numbering room — at
    whole-page density the chip placer runs out of free space."""
    page = Image.open(SCAN).convert("RGB")
    y0, y1 = half.fy0 * page.height, half.fy1 * page.height
    section = Rectangle(x0=0.0, y0=y0, x1=float(page.width), y1=y1)
    inside = [b for b in boxes if b.y1 >= y0 and b.y0 <= y1]
    rendered = render_numbered(page, section, [(b.x0, b.y0, b.x1, b.y1) for b in inside], half.scale)
    sheet = captioned_sheet(rendered.image, [half.title, f"{len(inside)} boxes, numbered in reading order"])
    sheet.sheet.save(path.with_suffix(".png"))
    path.write_bytes(review_image(sheet.sheet, width=1400, quality=74))
    missing = unplaced(rendered.chips)
    print(f"{path.name} -> {path.stat().st_size // 1024}KB; {len(inside)} boxes, {len(missing)} chips unplaced")


def _main() -> int:
    for name, title, boxes in (
        ("page-words", "the whole page — every WORD boxed, numbered", _words()),
        ("page-rows", "the whole page — every ROW boxed, numbered", _rows()),
    ):
        _draw(OUT / f"{name}.jpg", title, boxes)
        _draw_half(OUT / f"{name}-top.jpg", boxes, _Half(title=f"{title} (top half)", fy0=0.0, fy1=0.5))
        _draw_half(OUT / f"{name}-bottom.jpg", boxes, _Half(title=f"{title} (bottom half)", fy0=0.5, fy1=1.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
