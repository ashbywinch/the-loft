"""Boxed pieces for rulings: what the underline test would call, and where.

Each panel: a zoom of one mark with chosen split pieces outlined and labelled
(size + why it is boxed). Domain content only (which marks, which pieces);
drawing is tools.page_visuals primitives.
Usage: .venv/bin/python research/spike-word-segmentation/render_piece_boxes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from PIL import Image

from tools.mark import SCALE, find_marks
from tools.page_visuals import captioned_sheet, halo_text, review_image, scaled_crop, stack_sheets
from tools.pagescale import PageScale, line_ratio, traced_pitch, writing_scale
from tools.reader import LineFitter, artifacts, ink_mask, split_shapes

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "page01-wordseg"
OUT = Path(__file__).resolve().parent / "evidence" / "piece-boxes.jpg"

# mark id -> (window, scale, [(piece index, label)], caption lines)
PANELS: dict[str, tuple] = {
    "2875": (
        (1920, 2500, 2045, 2620, 6.0),
        [(0, "P1 16x10"), (1, "P2 52x42")],
        [
            "2875: P1 (red) 16x10 and P2 (blue) 52x42 — neither is a line",
            "the cut stands as the upper/lower word separation (you ruled 2 words)",
        ],
    ),
    "7105": (
        (950, 2975, 1550, 3075, 2.5),
        [(1, "P2 564x24")],
        [
            "7105: P1 (red) is a rule — 564px wide against 410px of text above",
            "not aligned, so a rule (and a rule is not a word)",
        ],
    ),
    "14187": (
        (1130, 3610, 1840, 3760, 2.5),
        [(0, "P0 448x56"), (1, "P1 618x20")],
        [
            "14187: P0 (448x56) is the five words — kept (too tall to be a line)",
            "P1 (618x20) is an underline: 618 wide vs 640 of text above",
        ],
    ),
    "9676": (
        (1415, 3195, 1850, 3300, 3.0),
        [(1, "P1 382x20")],
        [
            "9676: P1 (red) is an underline — 382 wide vs the text above",
            "aligned with the words, so a line, not a word",
        ],
    ),
    "683": (
        (1380, 2270, 1545, 2375, 6.0),
        [(2, "P3 26x8")],
        ["683: P3 (red) 26x8 is not a line (aspect 3.2, not 8)", "so it stays with its word — 683 is one piece"],
    ),
}


def _main() -> int:
    page = Image.open(SCAN).convert("RGB")
    strokes_raw = json.loads((FIXTURE / "strokes.json").read_text())["strokes"]
    mask = ink_mask(page)
    artifacts(mask)
    shapes = find_marks(mask)
    traced = sorted(float(np.median([p[1] for p in s])) * page.height / SCALE for s in strokes_raw)
    ratio = line_ratio(traced_pitch(traced), writing_scale([s.height for s in shapes]))
    scale = PageScale.of([s.height for s in shapes], ratio)
    lines = LineFitter(scale).fit(shapes)
    by_id = {s.id: s for s in shapes}
    sheets = []
    for mark_id, ((x0, y0, x1, y1, zoom), boxes, caption) in PANELS.items():
        pieces = split_shapes([by_id[mark_id]], lines, scale.unit)
        crop = scaled_crop(page, x0, y0, x1, y1, zoom)
        sheet, draw, bar_h = captioned_sheet(crop, caption)
        for index, label in boxes:
            piece = pieces[index]
            colour = (200, 0, 0) if index == boxes[0][0] else (0, 120, 200)
            rect = [
                (piece.x0 * SCALE - x0) * zoom,
                (piece.y0 * SCALE - y0) * zoom + bar_h,
                (piece.x1 * SCALE - x0) * zoom,
                (piece.y1 * SCALE - y0) * zoom + bar_h,
            ]
            draw.rectangle(rect, outline=colour + (255,), width=2)
            halo_text(draw, (rect[0] + 2, rect[1] - 26), label, fill=colour)
        sheets.append(sheet)
        print(f"{mark_id}: {len(pieces)} pieces, boxed {[b[0] for b in boxes]}")
    OUT.write_bytes(review_image(stack_sheets(sheets)))
    print(f"piece boxes -> {OUT} ({OUT.stat().st_size // 1024}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
