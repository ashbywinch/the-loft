"""Both row proposals over the same scan, side by side with the reference.

The decision material for which engine the pipeline proposes rows from:
the reader's fitted writing lines (A) against the word grouping (`Page`, B),
both measured against the user's own adjudicated rows.

Run: `.venv/bin/python research/spike-word-segmentation/render_proposal_vs_grouping.py`
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import NamedTuple

from PIL import Image

from tools.page_visuals import captioned_sheet, stack_sheets
from tools.reader import reading_for_page
from tools.rectangle import Rectangle
from tools.render import render_rows
from tools.row import Row
from tools.rows import Rows
from tools.schemas import load_boxes, load_rows, load_words
from tools.word import Word

FIXTURE = Path("tests/fixtures/page01-rows-gold")
SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
OUT = Path("research/spike-word-segmentation/rows-proposal-vs-grouping.jpg")
ZOOM = Path("research/spike-word-segmentation/rows-proposal-vs-grouping-zoom.jpg")
SPACING = 67.6
PAGE_SIZE = (
    load_boxes(Path("tests/fixtures/page01-wordseg/boxes.json"))["page"]["width"],
    load_boxes(Path("tests/fixtures/page01-wordseg/boxes.json"))["page"]["height"],
)

spec = importlib.util.spec_from_file_location("gold", Path("research/render_rows_gold.py"))
assert spec is not None and spec.loader is not None
gold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gold)


def _zoom_panels(
    scan: Path,
    window: tuple[float, float],
    rowsets: list[tuple[str, list[Row]]],
    width: int = 1100,
) -> Image.Image:
    """The same comparison over one y-window, at a legible scale: the boxes
    are invisible on a whole page fitted to a phone."""

    page = Image.open(scan).convert("RGB")
    panels = []
    for title, rows in rowsets:
        drawn = render_rows(page, list(rows), [])
        top, bottom = max(0, int(window[0])), min(drawn.height, int(window[1]))
        crop = drawn.crop((0, top, drawn.width, bottom))
        fitted = crop.resize((width, int(crop.height * width / crop.width)), Image.Resampling.LANCZOS)
        sheet, _, _ = captioned_sheet(fitted, [title])
        panels.append(sheet)
    return stack_sheets(panels, max_width=width)


class _Comparison(NamedTuple):
    """The decision material: the captioned row sets (the user's own, A, B)
    and each engine's row bands."""

    rowsets: list[tuple[str, list[Row]]]
    a_boxes: list[Rectangle]
    b_boxes: list[Rectangle]


def _band_where_they_part(a_boxes: list, b_boxes: list, height: int = 600) -> tuple[float, float]:
    """The band of the page where B makes the most boxes A does not — the
    place the two engines visibly part company, so the zoom shows the
    decision rather than a stretch they agree on."""

    def extra(top: float) -> tuple[int, int]:
        bottom = top + height
        a_n = sum(1 for b in a_boxes if b.y0 >= top and b.y1 <= bottom)
        b_n = sum(1 for b in b_boxes if b.y0 >= top and b.y1 <= bottom)
        return b_n - a_n, b_n

    low = min(b.y0 for b in b_boxes)
    high = max(b.y1 for b in b_boxes)
    top = max((y for y in range(int(low), int(high) - height + 1, 100)), key=extra)
    return top, top + height


def _reference_rows(adjudicated: list, words: list, model_words: list[Word]) -> list[Row]:
    """The user's own rows: each adjudicated band's words, in the fixture's
    order — the panel the two engines are judged against."""
    return [
        gold._row(
            r + 1,
            [
                i
                for i, wd in enumerate(words)
                if adjudicated[r]["band"]["y0"] <= (wd["y0"] + wd["y1"]) / 2 <= adjudicated[r]["band"]["y1"]
            ],
            model_words,
        )
        for r in range(len(adjudicated))
    ]


def _both_proposals() -> _Comparison:
    """The two engines' rows over page-01, scored, with the user's own rows
    as the reference — the decision material, measured and captioned."""
    words = load_words(FIXTURE / "words.json")["words"]
    adjudicated = load_rows(FIXTURE / "rows.json")["rows"]
    word_adj = gold.adjudicated_words(words, adjudicated)
    model_words = [
        Word(w["x0"], w["y0"], w["x1"], w["y1"], font_size=w["baseline"] - w["waistline"], line=w["line"])
        for w in words
    ]

    # A — the reader's fitted writing lines, words assigned by their centres
    proposal = [{"index": line["index"], "box": line["box"]} for line in reading_for_page(Image.open(SCAN)).lines]
    proposal_row = gold._proposal_assignment(proposal, words)
    a_rows = [
        gold._row(k + 1, sorted(i for i, r in proposal_row.items() if r == k), model_words)
        for k in range(len(proposal))
    ]
    a_right, a_judged = gold.score("A  reader.reading_for_page", proposal_row, len(proposal), word_adj)

    # B — the drawn-lines builder with no lines (the words' own reading lines)
    b_rows = Rows.from_words(model_words, PAGE_SIZE).rows()
    b_row = {}
    for k, row in enumerate(b_rows):
        for i, w in enumerate(model_words):
            if any(b is w for b in row.word_boxes):
                b_row[i] = k
    b_right, b_judged = gold.score("B  rows.from_words (no lines)", b_row, len(b_rows), word_adj)

    reference = _reference_rows(adjudicated, words, model_words)
    rowsets = [
        (f"YOUR ROWS (rows.json, the reference)  |  {len(adjudicated)} rows", reference),
        (
            f"A — the line measurer (what the app shows today)  |  {len(a_rows)} rows, "
            f"{a_right}/{a_judged} words in your row ({100 * a_right / a_judged:.1f}%)",
            a_rows,
        ),
        (
            f"B — the word grouping (what the object model says)  |  {len(b_rows)} rows, "
            f"{b_right}/{b_judged} words in your row ({100 * b_right / b_judged:.1f}%)",
            b_rows,
        ),
    ]
    return _Comparison(rowsets, [row.band for row in a_rows], [row.band for row in b_rows])


def main() -> None:
    comparison = _both_proposals()
    rowsets, a_boxes, b_boxes = comparison

    contact = gold._panels(SCAN, [], rowsets)
    contact.save(OUT, quality=82)
    print(f"wrote {OUT}: {OUT.stat().st_size // 1024} KB, {contact.width}x{contact.height}")

    window = _band_where_they_part(a_boxes, b_boxes)
    here = [b for b in b_boxes if b.y0 >= window[0] and b.y1 <= window[1]]
    there = [b for b in a_boxes if b.y0 >= window[0] and b.y1 <= window[1]]
    print(f"the band y{window[0]:.0f}-{window[1]:.0f}: A makes {len(there)} boxes, B makes {len(here)}")
    zoom = _zoom_panels(SCAN, window, rowsets, width=1100)
    zoom.save(ZOOM, quality=85)
    print(
        f"wrote {ZOOM}: {ZOOM.stat().st_size // 1024} KB, {zoom.width}x{zoom.height}"
        f" | window y{window[0]:.0f}-{window[1]:.0f}"
    )


if __name__ == "__main__":
    main()
