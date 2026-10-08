"""The reading sheet: the whole page, each row highlighted and numbered, the
reading aligned in a column beside it.

The page is NOT cut up: it stays one continuous image, so the eye can follow
the writing down the sheet while the transcript for each row sits level with
the row it reads. Every row's band is tinted and carries its number in the
gutter, the same convention the review surface uses.

Run: PYTHONPATH=. .venv/bin/python research/spike-word-segmentation/render_transcript_sheet.py
Reads: work/eval-rows-transcript/page-01.answer.json (the eval's last answer)
Writes: research/spike-word-segmentation/rows-transcript-sheet.jpg
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from document.colour import Colour
from document.numbered_rows import NumberedRows
from document.schemas import load_user_row_adjustments
from document.word import Word
from pipeline.rows.render import render_rows
from pipeline.rows.rows import Rows

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
ANSWER = Path("work/eval-rows-transcript/page-01.answer.json")
FIXTURE = Path("tests/fixtures/page01-rows-gold")
LINES = FIXTURE / "user-row-adjustments.json"
WORDS = FIXTURE / "words.json"
OUT = Path("research/spike-word-segmentation/rows-transcript-sheet.jpg")

MARGIN = 18  # px: air around the reading's column
COLUMN = 1400  # px: the reading's column — wide enough for most lines, and lines
# that do not fit wrap UNDER their own entry, never clipped and never overlapping
TEXT_SIZE = 36  # px: the reading's own size, level with its row
NUMBER_SIZE = 40  # px: the row number in the gutter


def _width(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, text: str) -> int:
    """The pixels a line of text occupies at this font — the column is sized
    to the widest line, so nothing is ever clipped."""
    box = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), text, font=font)
    return int(box[2] - box[0])


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _texts(answer: str, rows: int) -> tuple[dict[int, str], dict[int, str]]:
    """The reading per row number, and its kind. A refused answer is still
    worth seeing, so an answer that fails the contract is read as it parses."""
    segments = json.loads(answer)["segments"]
    texts: dict[int, str] = {}
    kinds: dict[int, str] = {}
    for segment in segments:
        for number in segment.get("rows", []):
            texts[number] = segment.get("transcript", "")
            kinds[number] = segment.get("type", "body")
    return texts, kinds


def main() -> None:
    answer = json.loads(ANSWER.read_text())["answer"]
    page = Image.open(SCAN).convert("RGB")
    # the CORRECT rows: the rows the reviewer's drawn lines make — the reading
    # and the highlight are both about those, never the geometry's draft
    rows = Rows.from_words(
        [
            Word(
                w["x0"],
                w["y0"],
                w["x1"],
                w["y1"],
                baseline=w.get("baseline"),
                waistline=w.get("waistline"),
                line=w.get("line"),
            )
            for w in json.loads(WORDS.read_text(encoding="utf-8"))["words"]
        ],
        (page.width, page.height),
    ).adjust(load_user_row_adjustments(LINES)["lines"])
    texts, kinds = _texts(answer, len(rows))
    print(f"the rows are the correction's: {len(rows)} from {LINES.name}")

    # the highlight is the house renderer's (each row's words tinted in its own
    # hue, joined by the minimal bands) and the numbers are the document
    # package's own drawing — no second convention lives in this script
    highlighted = NumberedRows.draw_numbers(render_rows(page, rows), rows)
    text_font = _font(TEXT_SIZE)
    height = TEXT_SIZE + 8
    entries: list[list[str]] = []
    for row in rows:
        text = texts.get(row.number) or "(no reading)"
        prefix = f"{row.number}   "
        wrapped = textwrap.wrap(text, max(1, (COLUMN - 2 * MARGIN - _width(text_font, prefix)) // (TEXT_SIZE // 2)))
        entries.append([prefix + (wrapped[0] if wrapped else "")] + [" " * 6 + line for line in wrapped[1:]])
    sheet = Image.new(
        "RGB",
        (page.width + COLUMN, max(page.height, sum(len(e) for e in entries) * height + 2 * MARGIN)),
        (255, 255, 255),
    )
    sheet.paste(highlighted.image, (0, 0))
    draw = ImageDraw.Draw(sheet)
    y = MARGIN
    for entry in entries:
        for line in entry:
            draw.text((page.width + MARGIN, y), line, fill=Colour(red=20, green=20, blue=20), font=text_font)
            y += height

    sheet.save(OUT, quality=84)
    print(f"wrote {OUT}: {sheet.width}x{sheet.height}, {len(rows)} rows highlighted and numbered")


if __name__ == "__main__":
    main()
