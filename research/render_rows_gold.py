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

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image

from document.rectangle import Rectangle
from document.row import Row
from document.schemas import load_boxes, load_rows, load_user_row_adjustments, load_words
from document.word import Word
from pipeline.detect.reader import reading_for_page
from pipeline.rows.page_visuals import captioned_sheet, review_image, stack_sheets
from pipeline.rows.render import render_rows
from pipeline.rows.rows import Rows

FIXTURE = Path("tests/fixtures/page01-rows-gold")
SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
OUT = Path("research/spike-word-segmentation/rows-gold-vs-library.jpg")
SPACING = 67.6


def iou(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    ix = max(0.0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
    iy = max(0.0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    aa = (a["x1"] - a["x0"]) * (a["y1"] - a["y0"])
    bb = (b["x1"] - b["x0"]) * (b["y1"] - b["y0"])
    return inter / (aa + bb - inter)


def adjudicated_words(words: Sequence[Mapping[str, Any]], gold: Sequence[Mapping[str, Any]]) -> dict[int, int]:
    """word index -> adjudicated row, via the gold's own boxes (IoU)."""
    out: dict[int, int] = {}
    for r_i, row in enumerate(gold):
        for bx in row["word_boxes"]:
            best, bi = 0.0, None
            for i, wd in enumerate(words):
                v = iou(bx, wd)
                if v > best:
                    best, bi = v, i
            if best >= 0.5 and bi is not None:
                out[bi] = r_i
    return out


def score(label: str, word_row: dict[int, int], n_rows: int, word_adj: dict[int, int]) -> tuple[int, int]:
    """Rows pair by content; returns (correct, judged) for one algorithm."""
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
    return right, len(judged)


def _proposal_assignment(proposal: Sequence[Mapping[str, Any]], words: Sequence[Mapping[str, Any]]) -> dict[int, int]:
    """Every word -> the proposal row whose box holds its centre in both axes
    (the nearest by centre when boxes overlap)."""
    assigned: dict[int, int] = {}
    for i, wd in enumerate(words):
        cx, cy = (wd["x0"] + wd["x1"]) / 2, (wd["y0"] + wd["y1"]) / 2
        hits = [
            (abs((line["box"][1] + line["box"][3]) / 2 - cy), k)
            for k, line in enumerate(proposal)
            if line["box"][0] <= cx <= line["box"][2] and line["box"][1] <= cy <= line["box"][3]
        ]
        if hits:
            assigned[i] = min(hits)[1]
    return assigned


def _word(record) -> Word:
    return Word(
        record["x0"],
        record["y0"],
        record["x1"],
        record["y1"],
        baseline=record.get("baseline"),
        waistline=record.get("waistline"),
        line=record.get("line"),
    )


def _correction_assignment(
    words: Sequence[Mapping[str, Any]], lines: Sequence[Sequence[tuple[float, float]]], page_size: tuple[int, int]
) -> tuple[list[Any], dict[int, int]]:
    """`rows.adjust` on the page's words and the drawn lines -> the built
    rows and every word's built row."""
    boxes = [_word(w) for w in words]
    built = Rows.from_words(boxes, page_size).adjust([list(line) for line in lines])
    box_index = {b: i for i, b in enumerate(boxes)}
    built_row: dict[int, int] = {}
    for r_i, row in enumerate(built):
        for bx in row.word_boxes:
            if bx in box_index:
                built_row[box_index[bx]] = r_i
    return list(built), built_row


def _row(number: int, words: Sequence[int], model_words: Sequence[Word]) -> Row:
    """One record row from word indices: the words' boxes and their union."""
    boxes = [model_words[i] for i in words]
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
    rowsets: Sequence[tuple[str, Sequence[Row]]],
) -> Image.Image:
    """The comparison image: one captioned full-page panel per row set, at
    the same window and scale (captioned AFTER the fit to the phone — a
    22px caption on a 2544px page is an illegible 8px in the delivered
    file)."""
    page = Image.open(scan).convert("RGB")
    panels = []
    for title, rows in rowsets:
        drawn = render_rows(page, list(rows), strokes)
        fitted = drawn.resize((1000, int(drawn.height * 1000 / drawn.width)), Image.Resampling.LANCZOS)
        sheet, _, _ = captioned_sheet(fitted, [title])
        panels.append(sheet)
    return stack_sheets(panels, max_width=1000)


# a report script: main is a flat sequence of measurement + panel steps over
# one fixture; a parameter object would carry the same six names once
# lucidlint: ignore latent-class one fixture, one flat report body — a carrier object is one-use ceremony
def main() -> None:
    words = load_words(FIXTURE / "words.json")["words"]
    lines = load_user_row_adjustments(FIXTURE / "user-row-adjustments.json")["lines"]
    gold = load_rows(FIXTURE / "rows.json")["rows"]
    page_size = load_boxes(Path("tests/fixtures/page01-wordseg/boxes.json"))["page"]
    width, height = page_size["width"], page_size["height"]
    word_adj = adjudicated_words(words, gold)
    proposal = reading_for_page(Image.open(SCAN)).lines
    proposal_row = _proposal_assignment(proposal, words)
    built, built_row = _correction_assignment(words, lines, (width, height))

    print(f"words: {len(words)} | adjudicated rows: {len(gold)}")
    p_right, p_judged = score("PROPOSAL  (reader.reading_for_page)", proposal_row, len(proposal), word_adj)
    c_right, c_judged = score("CORRECTION (rows.py rows.adjust)", built_row, len(built), word_adj)

    def built_words(r_i: int) -> list[int]:
        return sorted(i for i, r in built_row.items() if r == r_i)

    model_words = [Word(w["x0"], w["y0"], w["x1"], w["y1"], font_size=w["baseline"] - w["waistline"]) for w in words]
    strokes = [[(x * width, y * height) for x, y in line] for line in lines]
    rowsets = [
        (
            f"THE ADJUDICATED ROWS (your rulings, rows.json)  |  {len(gold)} rows — the reference",
            [
                _row(
                    r + 1,
                    [
                        i
                        for i, wd in enumerate(words)
                        if gold[r]["band"]["y0"] <= (wd["y0"] + wd["y1"]) / 2 <= gold[r]["band"]["y1"]
                    ],
                    model_words,
                )
                for r in range(len(gold))
            ],
        ),
        (
            f"THE PROPOSAL — tools/reader.py reading_for_page (no lines drawn)  |  {len(proposal)} rows, "
            f"{p_right}/{p_judged} words in the correct row ({100 * p_right / p_judged:.1f}%)",
            [
                _row(k + 1, sorted(i for i, r in proposal_row.items() if r == k), model_words)
                for k in range(len(proposal))
            ],
        ),
        (
            f"THE CORRECTION — tools/rows.py rows.adjust (your {len(lines)} drawn lines)  |  {len(built)} rows, "
            f"{c_right}/{c_judged} words in the correct row ({100 * c_right / c_judged:.1f}%)",
            [_row(k + 1, built_words(k), model_words) for k in range(len(built))],
        ),
    ]
    contact = _panels(SCAN, strokes, rowsets)
    OUT.write_bytes(review_image(contact))
    print(f"wrote {OUT}: {OUT.stat().st_size // 1024} KB, {contact.width}x{contact.height}")


if __name__ == "__main__":
    main()
