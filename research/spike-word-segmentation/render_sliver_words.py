"""A mark's window with the detected WORDS outlined: what the reader sees.

For the block-sized welded marks (4847), the splitter's pieces are horizontal
bands and say nothing about the words; this draws the word boxes instead.
Domain content only (which window, which word file); drawing is
tools.page_visuals primitives.
Usage: .venv/bin/python research/spike-word-segmentation/render_sliver_words.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from tools.page_visuals import captioned_sheet, halo_text, review_image, scaled_crop

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
WORDS = Path("/tmp/reparse-sept14/words.json")
OUT = Path(__file__).resolve().parent / "evidence" / "sliver-words.jpg"

# the window around 4847's slivers (its own box spans x1484-2010 y2276-2768)
X0, Y0, X1, Y1, SCALE_OUT = 1900.0, 2520.0, 2070.0, 2720.0, 5.0
# the slivers (page px, from the splitter)
SLIVERS = [(2006.0, 2554.0, 2008.0, 2614.0), (2008.0, 2616.0, 2010.0, 2672.0)]


def _main() -> int:
    page = Image.open(SCAN).convert("RGB")
    words = json.loads(WORDS.read_text())["words"]
    crop = scaled_crop(page, X0, Y0, X1, Y1, SCALE_OUT)
    caption = [
        "4847's window: every detected word boxed (yellow) — the mark is one",
        "welded blob, so the splitter's pieces are horizontal bands, not words",
        "red = the two slivers it cut off (2px wide, 60px tall)",
    ]
    sheet, draw, bar_h = captioned_sheet(crop, caption)

    def px(v: float) -> float:
        return (v - X0) * SCALE_OUT

    def py(v: float) -> float:
        return (v - Y0) * SCALE_OUT + bar_h

    for word in words:
        wy0, wy1 = word["y0"], word["y1"]
        if wy1 < Y0 or wy0 > Y1 or word["x1"] < X0 or word["x0"] > X1:
            continue
        draw.rectangle([px(word["x0"]), py(wy0), px(word["x1"]), py(wy1)], outline=(200, 160, 0, 255), width=1)
    for sx0, sy0, sx1, sy1 in SLIVERS:
        draw.rectangle([px(sx0), py(sy0), px(sx1), py(sy1)], outline=(200, 0, 0, 255), width=2)
    halo_text(draw, (px(SLIVERS[0][0]) - 130, py(SLIVERS[0][1]) + 10), "the slivers", fill=(200, 0, 0))
    OUT.write_bytes(review_image(sheet))
    print(f"sliver words -> {OUT} ({OUT.stat().st_size // 1024}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
