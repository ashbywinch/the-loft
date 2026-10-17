"""The row-snag windows, both assignments shown with the house renderer.

Each question is two maps side by side — left: the user's confirmed rows;
right: `rows.adjust` — both drawn by `render_map` (the
library's generic renderer: `tint_row` over each row's words, the ink
staying loudest). The words a question concerns carry their reading-order
numbers; yellow strokes are the user's line indications.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from document.rectangle import Rectangle
from document.word import Word
from pipeline.rows.page_visuals import captioned_sheet, review_image
from pipeline.rows.rows import MapView, Row, Rows, render_map
from tools.word_numbering import numbered_order

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "page01-rows-gold"
FIXTURE_WORDSEG = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "page01-wordseg"
OUT = Path(__file__).resolve().parent / "evidence"
PAGE = json.loads((FIXTURE_WORDSEG / "boxes.json").read_text(encoding="utf-8"))["page"]

WORDS = json.loads((FIXTURE / "words.json").read_text(encoding="utf-8"))["words"]
LINES = json.loads((FIXTURE / "user-row-adjustments.json").read_text(encoding="utf-8"))["lines"]
ROWS = json.loads((FIXTURE / "rows.json").read_text(encoding="utf-8"))["rows"]
RENDER_ID = {
    page: render
    for render, page in enumerate(numbered_order([(w["x0"], w["y0"], w["x1"], w["y1"]) for w in WORDS]), start=1)
}
BOX_OF = {
    render: (round(WORDS[i]["x0"]), round(WORDS[i]["y0"]), round(WORDS[i]["x1"]), round(WORDS[i]["y1"]))
    for i, render in RENDER_ID.items()
}


def adjudicated_rows() -> list[Row]:
    return [
        Row(
            id=row["id"],
            kind=row["kind"],
            number=row["number"],
            word_boxes=[Word(b["x0"], b["y0"], b["x1"], b["y1"]) for b in row["word_boxes"]],
            band=Rectangle(row["band"]["x0"], row["band"]["y0"], row["band"]["x1"], row["band"]["y1"]),
        )
        for row in ROWS
    ]


def library_rows() -> list[Row]:
    return Rows.from_words(
        [Word(w["x0"], w["y0"], w["x1"], w["y1"], baseline=w.get("baseline"), line=w.get("line")) for w in WORDS],
        (PAGE["width"], PAGE["height"]),
    ).adjust(LINES)


def numbers_of(word_ids: list[int]) -> dict[tuple[float, float, float, float], int]:
    return {BOX_OF[rid]: rid for rid in word_ids}


def pair(name: str, window: Rectangle, scale: float, word_ids: list[int]) -> None:
    page = Image.open(SCAN).convert("RGB")
    view = MapView(window, scale, word_numbers=numbers_of(word_ids))
    user_map = render_map(page, adjudicated_rows(), OUT / (name + ".u.jpg"), view)
    lib_map = render_map(page, library_rows(), OUT / (name + ".l.jpg"), view)
    user_cap = captioned_sheet(user_map, ["your rows (confirmed 2026-09-12)"])
    user_sheet = user_cap.sheet
    lib_cap = captioned_sheet(lib_map, ["the library's rows (`rows.adjust)`"])
    lib_sheet = lib_cap.sheet
    width = user_sheet.width + lib_sheet.width + 10
    height = max(user_sheet.height, lib_sheet.height)
    sheet = Image.new("RGB", (width, height), (255, 255, 255))
    sheet.paste(user_sheet, (0, 0))
    sheet.paste(lib_sheet, (user_sheet.width + 8, 0))
    (OUT / (name + ".jpg")).write_bytes(review_image(sheet))
    print("saved", name)


pair("row-snag-q1-v3", Rectangle(x0=500, y0=3180, x1=1960, y1=3270), 2.5, list(range(174, 191)))
pair("row-snag-q2-v3", Rectangle(x0=1900, y0=2520, x1=2060, y1=2640), 5.0, [60, 68, 69, 70])
pair(
    "row-snag-q3-v3",
    Rectangle(x0=540, y0=4470, x1=2010, y1=4640),
    2.2,
    [306, 415, 413, 416, 425, 428, 430, 455, 419, 422, 426],
)
