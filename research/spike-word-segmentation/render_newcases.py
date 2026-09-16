"""Welded-word cases: one sheet each — scan words, render id, raw mark ids.

Domain content only (which render id, which window, which caption); drawing
is tools.page_visuals primitives, except outlines: labeled_box pins its
label inside the box top-left, which would cover thin evidence rows, so
outlines are plain rectangles with labels placed beside them.
Usage: .venv/bin/python research/spike-word-segmentation/render_newcases.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from tools.mark import SCALE, find_marks
from tools.page_visuals import captioned_sheet, halo_text, review_image, scaled_crop
from tools.reader import artifacts, ink_mask

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
OUTDIR = Path(__file__).resolve().parent / "evidence"
STAGED = OUTDIR / "marks-wholepage-numbering.json"

# render id (wholepage numbering) -> window (x0, y0, x1, y1, scale) page px
CASES = {
    248: (968, 3882, 1262, 4128, 4.0),
    227: (962, 3800, 1086, 3954, 6.0),
    97: (918, 2936, 1582, 3114, 4.0),
    206: (1114, 3590, 1852, 3768, 4.0),
}


def _main() -> int:
    page = Image.open(SCAN).convert("RGB")
    mask = ink_mask(page)
    artifacts(mask)
    shapes = find_marks(mask)
    staged = {w["render_id"]: w for w in json.loads(STAGED.read_text())["words"]}
    for render_id, (x0, y0, x1, y1, scale) in CASES.items():
        entry = staged[render_id]
        red = [float(v) for v in entry["box"]]
        mark_id = entry["mark_id"]
        band = [
            s for s in shapes if not (s.x1 * SCALE < x0 or s.x0 * SCALE > x1 or s.y1 * SCALE < y0 or s.y0 * SCALE > y1)
        ]
        crop = scaled_crop(page, x0, y0, x1, y1, scale)
        caption = [
            f"render {render_id} (red) lives in raw mark {mark_id} (green)",
            "read the words: how many share that green mark?",
        ]
        sheet, draw, bar_h = captioned_sheet(crop, caption)

        def px(v: float, _x0: float = x0, _s: float = scale) -> float:
            return (v - _x0) * _s

        def py(v: float, _y0: float = y0, _s: float = scale, _b: float = bar_h) -> float:
            return (v - _y0) * _s + _b

        draw.rectangle([px(red[0]), py(red[1]), px(red[2]), py(red[3])], outline=(200, 0, 0, 255), width=3)
        halo_text(draw, (px(red[0]) + 2, py(red[1]) - 28), f"render {render_id}", fill=(200, 0, 0))
        for s in sorted(band, key=lambda s: s.x0):
            bx0, by0, bx1, by1 = s.x0 * SCALE, s.y0 * SCALE, s.x1 * SCALE, s.y1 * SCALE
            colour = (0, 140, 0) if s.id == mark_id else (140, 140, 140)
            draw.rectangle([px(bx0), py(by0), px(bx1), py(by1)], outline=colour + (255,), width=2)
            halo_text(draw, (px(bx0) + 2, py(by0) - 26), s.id, fill=colour)
        out = OUTDIR / f"newcase-{render_id}.jpg"
        out.write_bytes(review_image(sheet))
        print(f"render {render_id} in mark {mark_id} -> {out} ({out.stat().st_size // 1024}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
