"""Both row proposals over the same scan, side by side with the reference.

The decision material for which engine the pipeline proposes rows from:
the reader's fitted writing lines (A) against the word grouping (`Page`, B),
both measured against the user's own adjudicated rows.

Run: `.venv/bin/python research/spike-word-segmentation/render_proposal_vs_grouping.py`
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import NamedTuple

from PIL import Image

from document.page_size import PageSize
from document.rectangle import Rectangle
from document.row import Row
from document.span import Span
from document.word import Word
from pipeline.detect.reader import reading_for_page
from pipeline.layout_line import LayoutLine
from pipeline.rows.box_difference import BoxDifference
from pipeline.rows.page_visuals import captioned_sheet, stack_sheets
from pipeline.rows.render import render_rows
from pipeline.rows.row_set import RowSet
from pipeline.rows.rows import Rows
from pipeline.transcribe.transcripts import words_from

FIXTURE = Path("tests/fixtures/page01-rows-gold")
BOXES = Path("tests/fixtures/page01-wordseg/boxes.json")
SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
OUT = Path("research/spike-word-segmentation/rows-proposal-vs-grouping.jpg")
ZOOM = Path("research/spike-word-segmentation/rows-proposal-vs-grouping-zoom.jpg")
SPACING = 67.6
PAGE_SIZE = PageSize.from_dict(json.loads(BOXES.read_text(encoding="utf-8"))["page"])

spec = importlib.util.spec_from_file_location("gold", Path("research/render_rows_gold.py"))
assert spec is not None and spec.loader is not None
gold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gold)


def _zoom_panels(
    scan: Path,
    window: Span,
    rowsets: list[RowSet],
    width: int = 1100,
) -> Image.Image:
    """The same comparison over one y-window, at a legible scale: the boxes
    are invisible on a whole page fitted to a phone."""

    page = Image.open(scan).convert("RGB")
    panels = []
    for rowset in rowsets:
        drawn = render_rows(page, list(rowset.rows), [])
        top, bottom = max(0, int(window.start)), min(drawn.height, int(window.end))
        crop = drawn.crop((0, top, drawn.width, bottom))
        fitted = crop.resize((width, int(crop.height * width / crop.width)), Image.Resampling.LANCZOS)
        sheet = captioned_sheet(fitted, [rowset.title])
        panels.append(sheet.sheet)
    return stack_sheets(panels, max_width=width)


class _Comparison(NamedTuple):
    """The decision material: the captioned row sets (the user's own, A, B)
    and each engine's row bands."""

    rowsets: list[RowSet]
    a_boxes: list[Rectangle]
    b_boxes: list[Rectangle]


def _band_where_they_part(a_boxes: list[Rectangle], b_boxes: list[Rectangle], height: int = 600) -> Span:
    """The band of the page where B makes the most boxes A does not — the
    place the two engines visibly part company, so the zoom shows the
    decision rather than a stretch they agree on."""

    def extra(top: float) -> BoxDifference:
        bottom = top + height
        a_n = sum(1 for b in a_boxes if b.y0 >= top and b.y1 <= bottom)
        b_n = sum(1 for b in b_boxes if b.y0 >= top and b.y1 <= bottom)
        return BoxDifference(extra=b_n - a_n, boxes=b_n)

    low = min(b.y0 for b in b_boxes)
    high = max(b.y1 for b in b_boxes)
    top = max((y for y in range(int(low), int(high) - height + 1, 100)), key=extra)
    return Span(start=top, end=top + height)


def _reference_rows(adjudicated: list[Row], words: list[Word]) -> list[Row]:
    """The user's own rows: each adjudicated band's words, in the fixture's
    order — the panel the two engines are judged against."""
    return [
        gold._row(
            r + 1,
            [i for i, wd in enumerate(words) if adjudicated[r].band.y0 <= wd.cy <= adjudicated[r].band.y1],
            words,
        )
        for r in range(len(adjudicated))
    ]


def _both_proposals() -> _Comparison:
    """The two engines' rows over page-01, scored, with the user's own rows
    as the reference — the decision material, measured and captioned."""
    words = words_from(FIXTURE / "words.json")
    adjudicated = Rows.from_dict(json.loads((FIXTURE / "rows.json").read_text(encoding="utf-8")))
    word_adj = gold.adjudicated_words(words, adjudicated)

    # A — the reader's fitted writing lines, words assigned by their centres
    proposal = [LayoutLine.from_dict(line) for line in reading_for_page(Image.open(SCAN)).lines]
    proposal_row = gold._proposal_assignment(proposal, words)
    a_rows = [
        gold._row(k + 1, sorted(i for i, r in proposal_row.items() if r == k), words) for k in range(len(proposal))
    ]
    a = gold.score("A  reader.reading_for_page", proposal_row, len(proposal), word_adj)

    # B — the drawn-lines builder with no lines (the words' own reading lines)
    b_rows = Rows.from_words(words, PAGE_SIZE).rows()
    b_row: dict[int, int] = {}
    for k, row in enumerate(b_rows):
        for i, w in enumerate(words):
            if any(b is w for b in row.word_boxes):
                b_row[i] = k
    b = gold.score("B  rows.from_words (no lines)", b_row, len(b_rows), word_adj)

    reference = _reference_rows(adjudicated, words)
    rowsets = [
        RowSet(
            title=f"YOUR ROWS (rows.json, the reference)  |  {len(adjudicated)} rows",
            rows=reference,
        ),
        RowSet(
            title=(
                f"A — the line measurer (what the app shows today)  |  {len(a_rows)} rows, "
                f"{a.correct}/{a.judged} words in your row ({100 * a.correct / a.judged:.1f}%)"
            ),
            rows=a_rows,
        ),
        RowSet(
            title=(
                f"B — the word grouping (what the object model says)  |  {len(b_rows)} rows, "
                f"{b.correct}/{b.judged} words in your row ({100 * b.correct / b.judged:.1f}%)"
            ),
            rows=b_rows,
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
    here = [b for b in b_boxes if b.y0 >= window.start and b.y1 <= window.end]
    there = [b for b in a_boxes if b.y0 >= window.start and b.y1 <= window.end]
    print(f"the band y{window.start:.0f}-{window.end:.0f}: A makes {len(there)} boxes, B makes {len(here)}")
    zoom = _zoom_panels(SCAN, window, rowsets, width=1100)
    zoom.save(ZOOM, quality=85)
    print(
        f"wrote {ZOOM}: {ZOOM.stat().st_size // 1024} KB, {zoom.width}x{zoom.height}"
        f" | window y{window.start:.0f}-{window.end:.0f}"
    )


if __name__ == "__main__":
    main()
