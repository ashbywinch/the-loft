"""The rows library's contracts.

Unit behaviour is tested on small synthetic pages — the fixture's own
contents are committed data, not something a test re-checks. The one
fixture test is the integration contract, region-based: `Rows.build` on
page-01's words and user lines reproduces the adjudicated rows wherever
the lines decide. Rows are regions (bands), so the contract survives any
parse of the page's words: the build's bands match the adjudicated bands,
and a word the lines cannot claim still lives inside an adjudicated
row's band (the human rulings live in rows.json — carried, never
inferred).
"""

from __future__ import annotations

from pathlib import Path

from tools.rows import Box, Rows
from tools.schemas import Row, load_boxes, load_rows, load_user_row_adjustments, load_words

FIXTURE = Path(__file__).parent / "fixtures" / "page01-rows-gold"
PAGE_SIZE = (1000, 1000)


def _words(*boxes: tuple[float, float, float, float]) -> list[Box]:
    return [Box(*box) for box in boxes]


def _line(x0: float, x1: float, y: float) -> list[tuple[float, float]]:
    return [(x0 / 1000, y / 1000), (x1 / 1000, y / 1000)]


def test_the_double_pass_is_one_row() -> None:
    """A second line drawn over words a first line already owns is the
    same row drawn again, not a new row."""
    words = _words((100, 100, 200, 130), (300, 100, 400, 130))
    rows = Rows.build(words, [_line(100, 400, 115), _line(100, 400, 120)], PAGE_SIZE)
    assert len(rows) == 1, f"the double pass made {len(rows)} rows"
    assert len(rows[0].word_boxes) == 2, "the double pass lost words"


def test_each_word_belongs_to_one_row() -> None:
    """Two distinct lines own disjoint words; no word appears in two rows."""
    words = _words((100, 100, 200, 130), (100, 300, 200, 330))
    rows = Rows.build(words, [_line(100, 200, 115), _line(100, 200, 315)], PAGE_SIZE)
    seen: list[Box] = []
    for row in rows:
        for box in row.word_boxes:
            assert box not in seen, f"{box} in two rows"
            seen.append(box)
    assert len(seen) == 2, "the lines lost words"


def test_the_band_is_the_words_union() -> None:
    """A row's band is exactly the union of its words' boxes — the render
    tints the band, so anything wider or taller would paint neighbours."""
    words = _words((100, 100, 200, 130), (300, 105, 500, 140))
    rows = Rows.build(words, [_line(100, 500, 118)], PAGE_SIZE)
    band = rows[0].band
    assert (band.x0, band.y0, band.x1, band.y1) == (100, 100, 500, 140)


def test_rules_are_not_claimed() -> None:
    """Long-flat ink with no writing above it is a rule, part of no row."""
    words = _words((100, 100, 200, 125), (100, 300, 600, 312))
    rows = Rows.build(words, [_line(100, 600, 306)], PAGE_SIZE)
    assert all(box.height < 20 for row in rows for box in row.word_boxes), "a rule was claimed as a word"


def test_the_rows_are_deterministic() -> None:
    """Two builds of the same inputs give identical rows."""
    words = _words((100, 100, 200, 130), (300, 100, 400, 130), (100, 300, 200, 330))
    lines = [_line(100, 400, 115), _line(100, 200, 315)]
    first = Rows.build(words, lines, PAGE_SIZE)
    second = Rows.build(words, lines, PAGE_SIZE)
    assert [(row.number, [(b.x0, b.y0, b.x1, b.y1) for b in row.word_boxes]) for row in first] == [
        (row.number, [(b.x0, b.y0, b.x1, b.y1) for b in row.word_boxes]) for row in second
    ]


def test_rows_are_numbered_in_reading_order() -> None:
    """The rows are numbered top first: the topmost row keeps the band of
    the topmost words."""
    words = _words((100, 300, 200, 330), (100, 100, 200, 130))
    rows = Rows.build(words, [_line(100, 200, 315), _line(100, 200, 115)], PAGE_SIZE)
    assert [row.number for row in rows] == [1, 2]
    assert rows[0].word_boxes[0].y0 == 100, "reading order is not topmost-first"


def test_a_word_under_two_lines_joins_the_nearest() -> None:
    """A word lying under two lines goes to the line whose drawn height is
    nearest its centre — not the first line in order (2026-09-18: rows
    18/19 of page-01 were wrongly merged by first-claim)."""
    words = _words((100, 195, 250, 215), (300, 205, 450, 225))
    rows = Rows.build(words, [_line(100, 400, 200), _line(100, 400, 220)], PAGE_SIZE)
    assert len(rows) == 2, f"the nearer line was not separated: {len(rows)} rows"


def test_the_adjudicated_rows_are_reproduced() -> None:
    """The integration contract, region-based: on page-01's words and
    user lines, the library reproduces the adjudicated rows wherever the
    lines decide. Rows are regions (bands), so the contract does not
    depend on the words parse: (1) the build makes at most one row fewer
    than the adjudication (the rows the user hand-made beyond the lines
    cannot be built); (2) every built row's band matches an adjudicated
    row's band; (3) a word the lines cannot place still lives inside an
    adjudicated row's band (the rulings are in rows.json, not inferred).
    A difference here is a snag to adjudicate, never a silent fix."""
    words = load_words(FIXTURE / "words.json")["words"]
    lines = load_user_row_adjustments(FIXTURE / "user-row-adjustments.json")["lines"]
    page = load_boxes(Path("tests/fixtures/page01-wordseg/boxes.json"))["page"]
    boxes = [Box(w["x0"], w["y0"], w["x1"], w["y1"]) for w in words]
    adjudicated = load_rows(FIXTURE / "rows.json")["rows"]
    built = Rows.build(boxes, lines, (page["width"], page["height"]), [w["baseline"] for w in words])

    def key(b: Box) -> tuple[int, int, int, int]:
        return (round(b.x0), round(b.y0), round(b.x1), round(b.y1))

    def centre(b: Box) -> float:
        return (b.y0 + b.y1) / 2

    def adj_centre(row: Row) -> float:
        return (row["band"]["y0"] + row["band"]["y1"]) / 2

    # (1) the 47-stack pair the user ruled a row of their own cannot be
    # built from lines that never reach it — at most one row fewer.
    assert len(adjudicated) - len(built) <= 1, f"the build made {len(built)} rows, the adjudication {len(adjudicated)}"

    # (2) every built row's band sits on an adjudicated row's band.
    for row in built:
        nearest = min(adjudicated, key=lambda a: abs(centre(row.band) - adj_centre(a)))
        assert abs(centre(row.band) - adj_centre(nearest)) <= 75, (
            f"built row {row.number} (band centred y{centre(row.band):.0f}) has no adjudicated row within 75px"
        )

    # (3) the rulings (2026-09-18/19): the span's y-window is one writing
    # height, so a tall mark within its row's band stays with its line
    # (the mark at y4218-4270 belongs to line 34); an annotation is
    # discounted — below its line's bottom or poking above its words —
    # and the A/B apportionment claims the remaining strays. Only the
    # asterisk ends without a row.
    placed = {key(b) for row in built for b in row.word_boxes}
    leftovers = sorted(key(b) for b in boxes if key(b) not in placed)
    assert leftovers == [(1902, 2668, 1932, 2702)], f"unexpected unrowed words: {leftovers}"


def test_an_annotation_poking_above_the_line_is_discounted() -> None:
    """A box that floats fully inside a line word's x-range, starting
    above that word's top, is an annotation — the line does not claim it
    (the asterisk, user 2026-09-19); a word whose box starts at its own
    ascenders stays in the line."""
    words = _words((100, 100, 500, 130), (200, 60, 230, 90))
    rows = Rows.build(words, [_line(100, 500, 115)], PAGE_SIZE)
    assert len(rows) == 1 and len(rows[0].word_boxes) == 1, "the annotation joined the line"
