"""The row-snag windows, both assignments shown with the house renderer.

Each question is two maps side by side — left: the user's confirmed rows
(2026-09-12); right: `Rows.build` — both drawn by `render_map` (the
library's generic renderer: `tint_row` over each row's words, the ink
staying loudest). The words a question concerns carry their reading-order
numbers; yellow strokes are the user's line indications.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from tools.page_visuals import captioned_sheet, review_image
from tools.rows import Box, Row, Rows, render_map
from tools.word_numbering import numbered_order

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "page01-rows-gold"
FIXTURE_WORDSEG = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "page01-wordseg"
OUT = Path(__file__).resolve().parent / "evidence"
PAGE = json.loads((FIXTURE_WORDSEG / "boxes.json").read_text(encoding="utf-8"))["page"]

WORDS = json.loads((FIXTURE / "words.json").read_text(encoding="utf-8"))["words"]
LINES = json.loads((FIXTURE / "user-lines.json").read_text(encoding="utf-8"))["lines"]
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
            word_boxes=[Box(b["x0"], b["y0"], b["x1"], b["y1"]) for b in row["word_boxes"]],
            band=Box(row["band"]["x0"], row["band"]["y0"], row["band"]["x1"], row["band"]["y1"]),
        )
        for row in ROWS
    ]


def library_rows() -> list[Row]:
    return Rows.build(
        [Box(w["x0"], w["y0"], w["x1"], w["y1"]) for w in WORDS],
        LINES,
        (PAGE["width"], PAGE["height"]),
    )


def numbers_of(word_ids: list[int]) -> dict[tuple[float, float, float, float], int]:
    return {BOX_OF[rid]: rid for rid in word_ids}


def pair(name: str, window: Box, scale: float, word_ids: list[int]) -> None:
    page = Image.open(SCAN).convert("RGB")
    user_map = render_map(page, adjudicated_rows(), OUT / (name + ".u.jpg"), window, scale, numbers_of(word_ids))
    lib_map = render_map(page, library_rows(), OUT / (name + ".l.jpg"), window, scale, numbers_of(word_ids))
    user_sheet, _, _ = captioned_sheet(user_map, ["your rows (confirmed 2026-09-12)"])
    lib_sheet, _, _ = captioned_sheet(lib_map, ["the library's rows (Rows.build)"])
    width = user_sheet.width + lib_sheet.width + 10
    height = max(user_sheet.height, lib_sheet.height)
    sheet = Image.new("RGB", (width, height), (255, 255, 255))
    sheet.paste(user_sheet, (0, 0))
    sheet.paste(lib_sheet, (user_sheet.width + 8, 0))
    (OUT / (name + ".jpg")).write_bytes(review_image(sheet))
    print("saved", name)


pair("row-snag-q1-v3", Box(500, 3180, 1960, 3270), 2.5, list(range(174, 191)))
pair("row-snag-q2-v3", Box(1900, 2520, 2060, 2640), 5.0, [60, 68, 69, 70])
pair("row-snag-q3-v3", Box(540, 4470, 2010, 4640), 2.2, [306, 415, 413, 416, 425, 428, 430, 455, 419, 422, 426])
