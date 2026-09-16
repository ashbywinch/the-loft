"""Close zooms of the blocked cuts, with the cut rows drawn.

Three windows: 2875's upper piece (what is it?), and the cut rows of 5514
(cut stands) beside 5555 (cut must be refused). Domain content only (which
windows, which cut rows); drawing is tools.page_visuals primitives.
Usage: .venv/bin/python research/spike-word-segmentation/render_cut_zooms.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from tools.page_visuals import captioned_sheet, dashed_hline, halo_text, review_image, scaled_crop, stack_sheets

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
OUT = Path(__file__).resolve().parent / "evidence" / "cut-zooms.jpg"

# (x0, y0, x1, y1, scale) page px, cut rows (page y), caption lines
ZOOMS: list[tuple[tuple[float, float, float, float, float], list[float], list[str]]] = [
    (
        (1930, 2505, 2035, 2615, 7.0),
        [2553],
        [
            "2875: the cut at y2553 gives two pieces",
            "upper: 16x10 page px (the piece called 'the rule')",
            "lower: 52x42 page px (the word)",
        ],
    ),
    (
        (1470, 2750, 1710, 2840, 5.0),
        [2791],
        ["5514: cut at y2791 must STAND", "upper 138x18, lower 198x32 page px"],
    ),
    (
        (1060, 2755, 1140, 2865, 7.0),
        [2787, 2825],
        ["5555: cuts at y2787 and y2825 must be REFUSED", "one word arrives in three pieces"],
    ),
]


def _main() -> int:
    page = Image.open(SCAN).convert("RGB")
    sheets = []
    for (x0, y0, x1, y1, scale), rows, caption in ZOOMS:
        crop = scaled_crop(page, x0, y0, x1, y1, scale)
        sheet, draw, bar_h = captioned_sheet(crop, caption)
        for row in rows:
            if y0 < row < y1:
                y = (row - y0) * scale + bar_h
                dashed_hline(draw, 0, crop.width, y)
                halo_text(draw, (crop.width - 120, y - 26), f"cut y{row:.0f}", fill=(200, 0, 0))
        sheets.append(sheet)
    out = OUT
    out.write_bytes(review_image(stack_sheets(sheets)))
    print(f"cut zooms -> {out} ({out.stat().st_size // 1024}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
