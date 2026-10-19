"""page-01: the two row algorithms against the adjudication, one image.

- THE PROPOSAL — tools/reader.py rows_for_page (the ink/fitted-lines chain;
  what the pipeline writes before any user line exists).
- THE CORRECTION — tools/rows.py rows.adjust (the drawn lines decide).

Both are scored by the same rule: for every word with an adjudicated row
(the gold's own boxes, IoU-matched to the re-parsed words), is the word in
the row the adjudication gives it? Rows pair by word content.

Run: .venv/bin/python research/render_rows_gold.py
Output: research/spike-word-segmentation/rows-gold-vs-library.jpg
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from document.page_size import PageSize
from document.rectangle import Rectangle
from document.row import Row
from document.row_adjustments import RowAdjustments
from document.word import Word
from pipeline.detect.reader import reading_for_page
from pipeline.layout_line import LayoutLine
from pipeline.rows.page_visuals import captioned_sheet, review_image, stack_sheets
from pipeline.rows.render import render_rows
from pipeline.rows.row_score import RowScore
from pipeline.rows.row_set import RowSet
from pipeline.rows.rows import Rows
from pipeline.transcribe.transcripts import drawn_lines, words_from

FIXTURE = Path("tests/fixtures/page01-rows-gold")
BOXES = Path("tests/fixtures/page01-wordseg/boxes.json")
SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
OUT = Path("research/spike-word-segmentation/rows-gold-vs-library.jpg")
SPACING = 67.6


def iou(a: Rectangle, b: Rectangle) -> float:
    ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    aa = a.width * a.height
    bb = b.width * b.height
    return inter / (aa + bb - inter)


def adjudicated_words(words: Sequence[Word], gold: Sequence[Row]) -> dict[int, int]:
    """word index -> adjudicated row, via the gold's own boxes (IoU)."""
    out: dict[int, int] = {}
    for r_i, row in enumerate(gold):
        for bx in row.word_boxes:
            best, bi = 0.0, None
            for i, wd in enumerate(words):
                v = iou(bx.rect, wd.rect)
                if v > best:
                    best, bi = v, i
            if best >= 0.5 and bi is not None:
                out[bi] = r_i
    return out


def score(label: str, word_row: dict[int, int], n_rows: int, word_adj: dict[int, int]) -> RowScore:
    """Rows pair by content; returns the words in the right row, of those judged."""
    pair: dict[int, int | None] = {}
    for r in range(n_rows):
        held = {i for i, x in word_row.items() if x == r}
        best, bo = None, 0
        for a_i in set(word_adj.values()):
            ov = len(held & {i for i, y in word_adj.items() if y == a_i})
            if ov > bo:
                best, bo = a_i, ov
        pair[r] = best
    judged = {i: a for i, a in word_adj.items() if word_row.get(i) is not None}
    right = sum(1 for i, a in judged.items() if pair.get(word_row[i]) == a)
    print(
        f"{label}: rows={n_rows} | words in the correct row: {right}/{len(judged)} ({100 * right / len(judged):.1f}%)"
    )
    return RowScore(correct=right, judged=len(judged))


def _proposal_assignment(proposal: Sequence[LayoutLine], words: Sequence[Word]) -> dict[int, int]:
    """Every word -> the proposal row whose box holds its centre in both axes
    (the nearest by centre when boxes overlap)."""
    assigned: dict[int, int] = {}
    for i, wd in enumerate(words):
        hits = [
            (abs((line.box[1] + line.box[3]) / 2 - wd.cy), k)
            for k, line in enumerate(proposal)
            if line.box is not None and line.box[0] <= wd.cx <= line.box[2] and line.box[1] <= wd.cy <= line.box[3]
        ]
        if hits:
            assigned[i] = min(hits)[1]
    return assigned


def _correction_assignment(words: Sequence[Word], adjustments: RowAdjustments, page_size: PageSize) -> list[Row]:
    """`rows.adjust` on the page's words and the drawn lines -> the built rows."""
    return Rows.from_words(list(words), page_size).adjust(adjustments)


def _word_rows(rows: Sequence[Row], words: Sequence[Word]) -> dict[int, int]:
    """Every word's row among `rows`, by identity — the rows hold the very
    words they claimed."""
    index = {word: i for i, word in enumerate(words)}
    out: dict[int, int] = {}
    for r_i, row in enumerate(rows):
        for bx in row.word_boxes:
            if bx in index:
                out[index[bx]] = r_i
    return out


def _row(number: int, words: Sequence[int], page_words: Sequence[Word]) -> Row:
    """One record row from word indices: the words' boxes and their union."""
    boxes = [page_words[i] for i in words]
    xs0 = [w.rect.x0 for w in boxes]
    ys0 = [w.rect.y0 for w in boxes]
    xs1 = [w.rect.x1 for w in boxes]
    ys1 = [w.rect.y1 for w in boxes]
    return Row(
        id=f"seg-{number}",
        kind="body",
        number=number,
        word_boxes=list(boxes),
        band=Rectangle(min(xs0), min(ys0), max(xs1), max(ys1)),
    )


def _panels(
    scan: Path,
    strokes: Sequence[Sequence[tuple[float, float]]],
    rowsets: Sequence[RowSet],
) -> Image.Image:
    """The comparison image: one captioned full-page panel per row set, at
    the same window and scale (captioned AFTER the fit to the phone — a
    22px caption on a 2544px page is an illegible 8px in the delivered
    file)."""
    page = Image.open(scan).convert("RGB")
    panels = []
    for rowset in rowsets:
        drawn = render_rows(page, list(rowset.rows), strokes)
        fitted = drawn.resize((1000, int(drawn.height * 1000 / drawn.width)), Image.Resampling.LANCZOS)
        sheet = captioned_sheet(fitted, [rowset.title])
        panels.append(sheet.sheet)
    return stack_sheets(panels, max_width=1000)


# a report script: main is a flat sequence of measurement + panel steps over
# one fixture; a parameter object would carry the same six names once
# lucidlint: ignore latent-class one fixture, one flat report body — a carrier object is one-use ceremony
def main() -> None:
    words = words_from(FIXTURE / "words.json")
    adjustments = drawn_lines(FIXTURE / "user-row-adjustments.json")
    lines = adjustments.lines
    gold = Rows.from_dict(json.loads((FIXTURE / "rows.json").read_text(encoding="utf-8")))
    page_size = PageSize.from_dict(json.loads(BOXES.read_text(encoding="utf-8"))["page"])
    word_adj = adjudicated_words(words, gold)
    proposal = [LayoutLine.from_dict(line) for line in reading_for_page(Image.open(SCAN)).lines]
    proposal_row = _proposal_assignment(proposal, words)
    built = _correction_assignment(words, adjustments, page_size)
    built_row = _word_rows(built, words)
    print(f"words: {len(words)} | adjudicated rows: {len(gold)}")
    p = score("PROPOSAL  (reader.reading_for_page)", proposal_row, len(proposal), word_adj)
    c = score("CORRECTION (rows.py rows.adjust)", built_row, len(built), word_adj)

    def built_words(r_i: int) -> list[int]:
        return sorted(i for i, r in built_row.items() if r == r_i)

    strokes = [[(x * page_size.width, y * page_size.height) for x, y in line] for line in lines]
    rowsets = [
        RowSet(
            title=f"THE ADJUDICATED ROWS (your rulings, rows.json)  |  {len(gold)} rows — the reference",
            rows=[
                _row(
                    r + 1,
                    [i for i, wd in enumerate(words) if gold[r].band.y0 <= wd.cy <= gold[r].band.y1],
                    words,
                )
                for r in range(len(gold))
            ],
        ),
        RowSet(
            title=(
                f"THE PROPOSAL — tools/reader.py reading_for_page (no lines drawn)  |  {len(proposal)} rows, "
                f"{p.correct}/{p.judged} words in the correct row ({100 * p.correct / p.judged:.1f}%)"
            ),
            rows=[
                _row(k + 1, sorted(i for i, r in proposal_row.items() if r == k), words) for k in range(len(proposal))
            ],
        ),
        RowSet(
            title=(
                f"THE CORRECTION — tools/rows.py rows.adjust (your {len(lines)} drawn lines)  |  "
                f"{len(built)} rows, {c.correct}/{c.judged} words in the correct row "
                f"({100 * c.correct / c.judged:.1f}%)"
            ),
            rows=[_row(k + 1, built_words(k), words) for k in range(len(built))],
        ),
    ]
    contact = _panels(SCAN, strokes, rowsets)
    OUT.write_bytes(review_image(contact))
    print(f"wrote {OUT}: {OUT.stat().st_size // 1024} KB, {contact.width}x{contact.height}")


if __name__ == "__main__":
    main()
