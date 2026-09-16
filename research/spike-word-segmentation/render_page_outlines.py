"""The whole page as the new pipeline reads it: every word outlined, and every
row outlined, one image each.

Runs the pipeline's own output (boxes.json, words.json in the data dir) —
never hand-copied numbers. Domain content only (which page, which file,
which colours); drawing is tools.page_visuals primitives.
Usage: .venv/bin/python research/spike-word-segmentation/render_page_outlines.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from tools.page_visuals import captioned_sheet, review_image, scaled_crop

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
DATA = Path("/tmp/newpipe")
OUT = Path(__file__).resolve().parent / "evidence"

WORD_COLOUR = (0, 90, 200, 255)
ROW_COLOUR = (200, 0, 0, 255)
BOX_WIDTH = 3  # px: heavy enough to survive the review downscale


def _draw(path: Path, title: str, boxes: list[list[tuple[float, float]]], colour: tuple) -> None:
    """The whole page, every box outlined, one caption bar at the very top.

    One image, not panels: a caption bar or a gap between stacked panels lands
    inside the writing and reads as a white box across the page (user,
    2026-09-16)."""
    page = Image.open(SCAN).convert("RGB")
    crop = scaled_crop(page, 0, 0, page.width, page.height, 1.0)
    sheet, draw, bar_h = captioned_sheet(crop, [title, f"{len(boxes)} boxes, all outlined"])
    for box in boxes:
        draw.polygon([(px, py + bar_h) for px, py in box], outline=colour, width=BOX_WIDTH)
    sheet.save(path.with_suffix(".png"))
    path.write_bytes(review_image(sheet))
    print(f"{path.name} -> {path} ({path.stat().st_size // 1024}KB), full size {path.with_suffix('.png').name}")


def _words() -> list[list[tuple[float, float]]]:
    """Every word box as a rectangle (the pipeline measured them in page px)."""
    words = json.loads((DATA / "words.json").read_text())["words"]
    return [[(w["x0"], w["y0"]), (w["x1"], w["y0"]), (w["x1"], w["y1"]), (w["x0"], w["y1"])] for w in words]


def _rows() -> list[list[tuple[float, float]]]:
    """Every row box as the polygon the pipeline wrote."""
    return [box for box in json.loads((DATA / "boxes.json").read_text())["boxes"]]


def _main() -> int:
    for name, title, boxes, colour in (
        ("page-words", "the whole page — every WORD boxed", _words(), WORD_COLOUR),
        ("page-rows", "the whole page — every ROW boxed", _rows(), ROW_COLOUR),
    ):
        _draw(OUT / f"{name}.jpg", title, boxes, colour)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
