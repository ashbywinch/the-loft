"""Zooms of the word boxes the user flagged, numbered, one file each.

The window is the domain content; the drawing (box hues, numbered chips) is the
house numbering renderer. Numbers are reading order within the window, so they
differ from the whole-page render's.
Usage: .venv/bin/python research/spike-word-segmentation/render_case_zooms.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from tools.page_visuals import captioned_sheet, review_image
from tools.word_numbering import number_words, render_numbered, unplaced

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
DATA = Path("/tmp/newpipe")
OUT = Path(__file__).resolve().parent / "evidence"

# name -> window (page px), scale, the whole-page numbers to draw, the caption
# Only the boxes at issue are drawn: the chip placer needs free space, and a
# window full of overlapping boxes leaves none.
CASES: dict[str, tuple[tuple[float, float, float, float], float, list[int], list[str]]] = {
    "case-342": (
        (1370.0, 4390.0, 1570.0, 4610.0),
        4.0,
        [321, 334, 342],
        ["the box directly above 342 (334), and 342 itself", "each box numbered as the whole-page render numbers them"],
    ),
    "case-47": (
        (1880.0, 2500.0, 2060.0, 2660.0),
        5.0,
        [37, 47],
        ["box 47 (rightmost, unnumbered) and the weld 37 that contains it", "whole-page numbers"],
    ),
}


def _main() -> int:
    page = Image.open(SCAN).convert("RGB")
    words = json.loads((DATA / "words.json").read_text())["words"]
    boxes = [(w["x0"], w["y0"], w["x1"], w["y1"]) for w in words]
    for name, (window, scale, wanted, caption) in CASES.items():
        x0, y0, x1, y1 = window
        whole = number_words(boxes)
        inside = [entry["box"] for entry in whole if entry["render_id"] in wanted]
        image, chips = render_numbered(page, (x0, y0, x1, y1), inside, scale)
        sheet, _handle, _bar = captioned_sheet(image, caption)
        out = OUT / f"{name}.jpg"
        out.write_bytes(review_image(sheet, width=1400, quality=76))
        print(f"{name}: {len(inside)} boxes in the window, {len(unplaced(chips))} chips unplaced -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
