"""Why the two stacked pairs stay one box: the candidate pieces, boxed.

For each flagged mark: the pieces the cut proposes at each assignment flip,
outlined in different colours and labelled with their measured size and the
bar they fail. Domain content only (which marks, which windows); drawing is
tools.page_visuals primitives.
Usage: .venv/bin/python research/spike-word-segmentation/render_why_pieces.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from PIL import Image

from tools.mark import (
    SCALE,
    WORD_MIN_HEIGHT,
    WORD_MIN_WIDTH,
    Ink,
)
from tools.page_visuals import captioned_sheet, halo_text, review_image, scaled_crop
from tools.reader import Writing, _is_waist, _piece_between, artifacts, ink_mask

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "page01-wordseg"
OUT = Path(__file__).resolve().parent / "evidence"

# label -> the point inside the flagged box (page px), the window to show, the zoom
CASES = {
    "why-47": ((1975.0, 2570.0), (1910.0, 2510.0, 2030.0, 2620.0), 8.0),
    "why-334": ((1470.0, 4520.0), (1380.0, 4410.0, 1560.0, 4600.0), 5.0),
}
COLOURS = ((0, 0, 200), (0, 150, 0), (200, 0, 0), (150, 0, 180))


def _size(piece) -> str:
    ys, xs = np.asarray(piece.pix[0]), np.asarray(piece.pix[1])
    return f"h{(ys.max() - ys.min() + 1) * SCALE:.0f} w{(xs.max() - xs.min() + 1) * SCALE:.0f}"


def _verdict(piece, unit: float) -> str:
    return "WORD" if piece.is_word_shaped(unit) else "NOT a word"


def _main() -> int:
    page = Image.open(SCAN).convert("RGB")
    strokes = json.loads((FIXTURE / "strokes.json").read_text())["strokes"]
    mask = ink_mask(page)
    artifacts(mask)
    traced = sorted(float(np.median([point[1] for point in stroke])) * page.height / SCALE for stroke in strokes)
    writing = Writing.of(mask, traced)
    unit = writing.scale.unit
    min_h, min_w = WORD_MIN_HEIGHT * unit * SCALE, WORD_MIN_WIDTH * unit * SCALE
    print(f"bars: height >= {min_h:.0f} px, width >= {min_w:.0f} px (page px)")

    for name, ((px, py), window, zoom) in CASES.items():
        x0, y0, x1, y1 = window
        mark = next(
            m for m in writing.marks if m.x0 * SCALE <= px <= m.x1 * SCALE and m.y0 * SCALE <= py <= m.y1 * SCALE
        )
        per_row = mark.rows()
        runs = Ink(np.asarray(mark.pix[0]), np.asarray(mark.pix[1])).longest_runs()
        segments = writing._candidate_segments(mark)
        pieces = [_piece_between(mark, segment) for segment in segments]

        crop = scaled_crop(page, x0, y0, x1, y1, zoom)
        caption = [
            f"mark {mark.id}: x{mark.x0 * SCALE:.0f}-{mark.x1 * SCALE:.0f}"
            f" y{mark.y0 * SCALE:.0f}-{mark.y1 * SCALE:.0f}",
            f"the cut proposes {len(segments)} piece(s) — each boxed and labelled",
        ]
        sheet, draw, bar_h = captioned_sheet(crop, caption)

        def bx(value: float, _x0: float = x0, _zoom: float = zoom) -> float:
            return (value * SCALE - _x0) * _zoom

        def by(value: float, _y0: float = y0, _zoom: float = zoom, _bar: float = bar_h) -> float:
            return (value * SCALE - _y0) * _zoom + _bar

        draw.rectangle([bx(mark.x0), by(mark.y0), bx(mark.x1), by(mark.y1)], outline=(0, 0, 0, 255), width=2)
        for index, piece in enumerate(pieces):
            colour = COLOURS[index % len(COLOURS)]
            draw.rectangle([bx(piece.x0), by(piece.y0), bx(piece.x1), by(piece.y1)], outline=colour + (255,), width=3)
            label = f"P{index + 1} {_size(piece)} {_verdict(piece, unit)}"
            halo_text(draw, (bx(piece.x0) + 4, by(piece.y0) - 26), label, fill=colour)
            print(f"  {name} P{index + 1}: {_size(piece)} {_verdict(piece, unit)}")

        for above, below in zip(segments, segments[1:], strict=False):
            waist = _is_waist(per_row, runs, above[2], below[1])
            note = "waist: cut" if waist else f"no waist (runs {runs.get(above[2], 0)}/{runs.get(below[1], 0)}): merged"
            halo_text(draw, (bx(mark.x0) + 4, by(below[1]) - 26), note, fill=(120, 60, 0))
            print(f"  {name} boundary y{above[2] * SCALE:.0f}->{below[1] * SCALE:.0f}: {note}")

        out = OUT / f"{name}.jpg"
        out.write_bytes(review_image(sheet, width=1300, quality=78))
        print(f"{name} -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
