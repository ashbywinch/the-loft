"""Myra-Hess darkness evidence: the joining stroke at reading size.

Domain content only (which window, which boxes); drawing is
tools.page_visuals primitives, except outlines: labeled_box pins its label
inside the box top-left, which would cover thin evidence rows, so outlines
are plain rectangles with labels placed beside them.
Usage: .venv/bin/python research/spike-word-segmentation/render_myra_bridge.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from tools.page_visuals import captioned_sheet, halo_text, review_image, scaled_crop

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
OUT = Path(__file__).resolve().parent / "evidence" / "myra-bridge.jpg"

# The two words and the guilty stroke between them, at reading scale.
X0, Y0, X1, Y1, SCALE_OUT = 1840.0, 2510.0, 1980.0, 2610.0, 6.0
STROKE = (1918.0, 2550.0, 1934.0, 2556.0)


def _main() -> int:
    page = Image.open(SCAN).convert("RGB")
    crop = scaled_crop(page, X0, Y0, X1, Y1, SCALE_OUT)
    caption = [
        "Myra Hess: one ink stroke joins the two words",
        "red box: the stroke, as dark as the letters themselves",
        "without it, two separate words; with it, the detector sees one",
    ]
    sheet, draw, bar_h = captioned_sheet(crop, caption)

    def px(v: float) -> float:
        return (v - X0) * SCALE_OUT

    def py(v: float) -> float:
        return (v - Y0) * SCALE_OUT + bar_h

    draw.rectangle(
        [px(STROKE[0]), py(STROKE[1]), px(STROKE[2]), py(STROKE[3])],
        outline=(200, 0, 0, 255),
        width=3,
    )
    halo_text(draw, (px(STROKE[2]) + 8, py(STROKE[1]) - 12), "this stroke", fill=(200, 0, 0))
    OUT.write_bytes(review_image(sheet))
    print(f"bridge -> {OUT} ({OUT.stat().st_size // 1024}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
