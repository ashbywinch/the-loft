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
    "case-5555": (
        (1040.0, 2730.0, 1160.0, 2880.0),
        5.0,
        [5555],
        [
            'mark 5528 = the word "5555" on the tests (page x1082-1118, y2770-2842)',
            'lowering the width bar to admit "of" would split it into 3 boxes',  # noqa: E501
        ],
    ),
    "case-342": (
        (1370.0, 4390.0, 1570.0, 4610.0),
        4.0,
        [323, 336, 344],
        [
            "336: the box above 342 holding two words (323 above it, 344 below)",  # noqa: E501
            "numbers as the current whole-page render numbers them",
        ],
    ),
    "case-47": (
        (1880.0, 2500.0, 2060.0, 2660.0),
        5.0,
        [37, 47],
        ["box 47 (rightmost, unnumbered) and the weld 37 that contains it", "whole-page numbers"],
    ),
    "case-3640-weld": (
        (1120.0, 3600.0, 1560.0, 3740.0),
        3.0,
        [217, 212, 213, 215],
        [
            "217: one box containing words 212, 213, 215",  # noqa: E501
            "the failing nested-pair case; numbers as the whole-page render numbers them",  # noqa: E501
        ],
    ),
    "case-3456": (
        (500.0, 3380.0, 860.0, 3520.0),
        3.0,
        [171, 182],
        [
            "the y3456 split: 171 and 182 are the two boxes the gap rule made",
            "was ONE box; verdict needed (correct or regression)",
        ],
    ),
    "case-213-212": (
        (1120.0, 3610.0, 1570.0, 3710.0),
        3.0,
        [213, 212],
        [
            "213: the last nested pair — still two fused words, with 212 inside it",
            "the y3640 weld's remainder after the underline strip",  # noqa: E501
        ],
    ),
    "case-1838": (
        (1810.0, 3110.0, 1900.0, 3220.0),
        4.0,
        [125],
        ["box 125: the gap rule dropped a 12px sliver off its top", "verdict needed (correct or regression)"],
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
