"""Whole-page raw marks in different colours: the detector baseline picture.

Domain content only (which page, which detector, which section); drawing is
tools.word_numbering stages + pipeline.rows.page_visuals.review_image. Stages the
numbering (render id -> raw mark id + box) to marks-wholepage-numbering.json
— the same file the image is drawn from, so a number on the page resolves
by lookup, never by re-deriving the sort.
Usage: .venv/bin/python research/spike-word-segmentation/render_marks_wholepage.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from document.colour import Colour
from document.rectangle import Rectangle
from pipeline.detect.mark import SCALE, find_marks
from pipeline.detect.reader import artifacts, ink_mask
from pipeline.rows.page_visuals import review_image
from tools.word_numbering import draw_numbering, number_words, place_numbering

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
if not SCAN.exists():
    raise SystemExit(f"render_* needs the adopt batch mounted - the scan is not at {SCAN}")
OUT = Path(__file__).resolve().parent / "evidence" / "marks-wholepage-review.jpg"
STAGED = Path(__file__).resolve().parent / "evidence" / "marks-wholepage-numbering.json"


@dataclass(frozen=True)
class StagedMark:
    """One mark as the numbering stage files it: the render id a number on the
    page resolves by, the raw mark's own id, its box in page px, and the hue it
    is drawn in.

    The wire is `marks-wholepage-numbering.json` — the same file the image is
    drawn from, so a number on the page is a lookup, never a re-derived sort."""

    render_id: int
    mark_id: str
    box: Rectangle
    colour: Colour

    def to_dict(self) -> dict[str, Any]:
        """The mark as its wire record: the four fields, the box as its four
        measures and the hue as its three channels."""
        return {
            "render_id": self.render_id,
            "mark_id": self.mark_id,
            "box": list(self.box),
            "colour": [self.colour.red, self.colour.green, self.colour.blue],
        }


def _main() -> int:
    page = Image.open(SCAN).convert("RGB")
    mask = ink_mask(page)
    artifacts(mask)
    shapes = find_marks(mask)
    boxes = [(s.x0 * SCALE, s.y0 * SCALE, s.x1 * SCALE, s.y1 * SCALE) for s in shapes]
    numbered = number_words(boxes)
    staged = [
        StagedMark(
            render_id=entry.render_id,
            mark_id=shapes[entry.page_index].id,
            box=Rectangle(*entry.box),
            colour=Colour(*entry.colour),
        )
        for entry in numbered
    ]
    STAGED.write_text(json.dumps({"words": [mark.to_dict() for mark in staged]}, indent=1), encoding="utf-8")
    section = Rectangle(x0=0.0, y0=0.0, x1=float(page.width), y1=float(page.height))
    layout = place_numbering(numbered, section, 1.0)
    img = draw_numbering(page, layout)
    OUT.write_bytes(review_image(img))
    print(f"marks wholepage: {len(shapes)} marks -> {OUT} ({OUT.stat().st_size // 1024}KB)")
    print(f"numbering staged -> {STAGED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
