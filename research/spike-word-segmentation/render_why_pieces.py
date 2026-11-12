"""Why the two stacked pairs stay one box: the candidate pieces, boxed.

For each flagged mark: the pieces the cut proposes at each assignment flip,
outlined in different colours and labelled with their measured size and the
bar they fail. Domain content only (which marks, which windows); drawing is
pipeline.rows.page_visuals primitives.
Usage: .venv/bin/python research/spike-word-segmentation/render_why_pieces.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from PIL import Image

from document.colour import Colour
from document.point import Point
from pipeline.detect.mark import Components, Ink, Mark
from pipeline.detect.reader import Writing, artifacts, ink_mask, is_waist, piece_between
from pipeline.rows.page_visuals import CaptionSheet, Crop, PagePainter, halo_text, scaled_crop

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")


class Config:
    """This script's fixed inputs and outputs."""

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
    return f"h{(ys.max() - ys.min() + 1) * Components.SCALE:.0f} w{(xs.max() - xs.min() + 1) * Components.SCALE:.0f}"


class SheetMap:
    """Page pixels -> the captioned sheet's pixels: the crop's origin, the
    zoom, and the caption bar the crop starts below."""

    def __init__(self, x0: float, y0: float, zoom: float, bar: float) -> None:
        self.x0 = x0
        self.y0 = y0
        self.zoom = zoom
        self.bar = bar

    def x(self, value: float) -> float:
        return (value * Components.SCALE - self.x0) * self.zoom

    def y(self, value: float) -> float:
        return (value * Components.SCALE - self.y0) * self.zoom + self.bar


def _verdict(piece, unit: float) -> str:
    return "WORD" if piece.is_word_shaped(unit) else "NOT a word"


def _main() -> int:
    page = Image.open(SCAN).convert("RGB")
    strokes = json.loads((Config.FIXTURE / "strokes.json").read_text())["strokes"]
    mask = ink_mask(page)
    artifacts(mask)
    traced = sorted(
        float(np.median([point[1] for point in stroke])) * page.height / Components.SCALE for stroke in strokes
    )
    writing = Writing.of(mask, traced)
    unit = writing.scale.unit
    min_h = Mark.WORD_MIN_HEIGHT * unit * Components.SCALE
    min_w = Mark.WORD_MIN_WIDTH * unit * Components.SCALE
    print(f"bars: height >= {min_h:.0f} px, width >= {min_w:.0f} px (page px)")

    for name, ((px, py), window, zoom) in Config.CASES.items():
        x0, y0, x1, y1 = window
        mark = next(
            m
            for m in writing.marks
            if m.x0 * Components.SCALE <= px <= m.x1 * Components.SCALE
            and m.y0 * Components.SCALE <= py <= m.y1 * Components.SCALE
        )
        per_row = mark.rows()
        runs = Ink(np.asarray(mark.pix[0]), np.asarray(mark.pix[1])).longest_runs()
        segments = writing._candidate_segments(mark)
        pieces = [piece_between(mark, segment) for segment in segments]

        crop = scaled_crop(page, Crop(x0, y0, x1, y1, zoom))
        caption = [
            f"mark {mark.id}: x{mark.x0 * Components.SCALE:.0f}-{mark.x1 * Components.SCALE:.0f}"
            f" y{mark.y0 * Components.SCALE:.0f}-{mark.y1 * Components.SCALE:.0f}",
            f"the cut proposes {len(segments)} piece(s) — each boxed and labelled",
        ]
        sheet = CaptionSheet.captioned_sheet(crop, caption)
        draw = sheet.draw
        bar_h = sheet.bar_height

        mapping = SheetMap(x0, y0, zoom, bar_h)
        draw.rectangle(
            [mapping.x(mark.x0), mapping.y(mark.y0), mapping.x(mark.x1), mapping.y(mark.y1)],
            outline=(0, 0, 0, 255),
            width=2,
        )
        for index, piece in enumerate(pieces):
            colour = Config.COLOURS[index % len(Config.COLOURS)]
            draw.rectangle(
                [mapping.x(piece.x0), mapping.y(piece.y0), mapping.x(piece.x1), mapping.y(piece.y1)],
                outline=colour + (255,),
                width=3,
            )
            label = f"P{index + 1} {_size(piece)} {_verdict(piece, unit)}"
            halo_text(draw, Point(x=mapping.x(piece.x0) + 4, y=mapping.y(piece.y0) - 26), label, fill=Colour(*colour))
            print(f"  {name} P{index + 1}: {_size(piece)} {_verdict(piece, unit)}")

        for above, below in zip(segments, segments[1:], strict=False):
            waist = is_waist(per_row, runs, above.y1, below.y0)
            note = "waist: cut" if waist else f"no waist (runs {runs.get(above.y1, 0)}/{runs.get(below.y0, 0)}): merged"
            halo_text(
                draw,
                Point(x=mapping.x(mark.x0) + 4, y=mapping.y(below.y0) - 26),
                note,
                fill=Colour(red=120, green=60, blue=0),
            )
            print(f"  {name} boundary y{above.y1 * Components.SCALE:.0f}->{below.y0 * Components.SCALE:.0f}: {note}")

        out = Config.OUT / f"{name}.jpg"
        out.write_bytes(PagePainter.review_image(sheet.sheet, width=1300, quality=78))
        print(f"{name} -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
