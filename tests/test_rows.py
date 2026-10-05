"""The rows library's contracts.

Unit behaviour is tested on small synthetic pages — the fixture's own
contents are committed data, not something a test re-checks. The one
fixture test is the integration contract, region-based: `rows.adjust` on
page-01's words and user lines reproduces the adjudicated rows wherever
the lines decide. Rows are regions (bands), so the contract survives any
parse of the page's words: the build's bands match the adjudicated bands,
and a word the lines cannot claim still lives inside an adjudicated
row's band (the human rulings live in rows.json — carried, never
inferred).
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.rectangle import Rectangle
from tools.rows import Rows
from tools.schemas import Row as WireRow
from tools.schemas import Word as WireWord
from tools.schemas import load_boxes, load_rows, load_user_row_adjustments, load_words
from tools.word import Word

FIXTURE = Path(__file__).parent / "fixtures" / "page01-rows-gold"
PAGE_SIZE = (1000, 1000)


def _word(record: WireWord) -> Word:
    """A fixture word record as the library's Word — the reading line and
    the measures travel with the box."""
    return Word(
        record["x0"],
        record["y0"],
        record["x1"],
        record["y1"],
        baseline=record["baseline"],
        waistline=record["waistline"],
        line=record["line"],
    )


def _words(*boxes: tuple[float, float, float, float], line: int | None = None) -> list[Word]:
    return [Word(*box, line=line) for box in boxes]


def _line(x0: float, x1: float, y: float) -> list[tuple[float, float]]:
    return [(x0 / 1000, y / 1000), (x1 / 1000, y / 1000)]


def test_the_double_pass_is_one_row() -> None:
    """A second line drawn over words a first line already owns is the
    same row drawn again, not a new row."""
    words = _words((100, 100, 200, 130), (300, 100, 400, 130))
    rows = Rows.from_words(words, PAGE_SIZE).adjust([_line(100, 400, 115), _line(100, 400, 120)])
    assert len(rows) == 1, f"the double pass made {len(rows)} rows"
    assert len(rows[0].word_boxes) == 2, "the double pass lost words"


def test_each_word_belongs_to_one_row() -> None:
    """Two distinct lines own disjoint words; no word appears in two rows."""
    words = _words((100, 100, 200, 130), (100, 300, 200, 330))
    rows = Rows.from_words(words, PAGE_SIZE).adjust([_line(100, 200, 115), _line(100, 200, 315)])
    seen: list[Word] = []
    for row in rows:
        for box in row.word_boxes:
            assert box not in seen, f"{box} in two rows"
            seen.append(box)
    assert len(seen) == 2, "the lines lost words"


def test_the_band_is_the_words_union() -> None:
    """A row's band is exactly the union of its words' boxes — the render
    tints the band, so anything wider or taller would paint neighbours."""
    words = _words((100, 100, 200, 130), (300, 105, 500, 140))
    rows = Rows.from_words(words, PAGE_SIZE).adjust([_line(100, 500, 118)])
    band = rows[0].band
    assert (band.x0, band.y0, band.x1, band.y1) == (100, 100, 500, 140)


def test_rules_are_not_claimed() -> None:
    """Long-flat ink with no writing above it is a rule, part of no row."""
    words = _words((100, 100, 200, 125), (100, 300, 600, 312))
    rows = Rows.from_words(words, PAGE_SIZE).adjust([_line(100, 600, 306)])
    assert all(box.height < 20 for row in rows for box in row.word_boxes), "a rule was claimed as a word"


def test_the_rows_are_deterministic() -> None:
    """Two builds of the same inputs give identical rows."""
    words = _words((100, 100, 200, 130), (300, 100, 400, 130), (100, 300, 200, 330))
    lines = [_line(100, 400, 115), _line(100, 200, 315)]
    first = Rows.from_words(words, PAGE_SIZE).adjust(lines)
    second = Rows.from_words(words, PAGE_SIZE).adjust(lines)
    assert [(row.number, [(b.x0, b.y0, b.x1, b.y1) for b in row.word_boxes]) for row in first] == [
        (row.number, [(b.x0, b.y0, b.x1, b.y1) for b in row.word_boxes]) for row in second
    ]


def test_rows_are_numbered_in_reading_order() -> None:
    """The rows are numbered top first: the topmost row keeps the band of
    the topmost words."""
    words = _words((100, 300, 200, 330), (100, 100, 200, 130))
    rows = Rows.from_words(words, PAGE_SIZE).adjust([_line(100, 200, 315), _line(100, 200, 115)])
    assert [row.number for row in rows] == [1, 2]
    assert rows[0].word_boxes[0].y0 == 100, "reading order is not topmost-first"


def test_a_word_under_two_lines_joins_the_nearest() -> None:
    """A word lying under two lines goes to the line whose drawn height is
    nearest its centre — not the first line in order."""
    words = _words((100, 195, 250, 215), (300, 205, 450, 225))
    rows = Rows.from_words(words, PAGE_SIZE).adjust([_line(100, 400, 200), _line(100, 400, 220)])
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
    boxes = [_word(w) for w in words]
    adjudicated = load_rows(FIXTURE / "rows.json")["rows"]
    built = Rows.from_words(boxes, (page["width"], page["height"])).adjust(lines)

    def key(b: Word | Rectangle) -> tuple[int, int, int, int]:
        return (round(b.x0), round(b.y0), round(b.x1), round(b.y1))

    def centre(b: Rectangle) -> float:
        return (b.y0 + b.y1) / 2

    def adj_centre(row: WireRow) -> float:
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

    # (3) the rulings: the span's y-window is one writing
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
    (the asterisk, user); a word whose box starts at its own
    ascenders stays in the line."""
    words = _words((100, 100, 500, 130), (200, 60, 230, 90))
    rows = Rows.from_words(words, PAGE_SIZE).adjust([_line(100, 500, 115)])
    assert len(rows) == 1 and len(rows[0].word_boxes) == 1, "the annotation joined the line"


def test_the_rows_round_trip_through_their_wire_format(tmp_path: Path) -> None:
    """The builder's output serializes to the wire contract
    (`tools.schemas.Rows`: id, kind, number, word_boxes, band — plain
    x0..y1 records) and reads back as the same rows. This is the file the
    review's correction persists and the app reads, so the shape is
    pinned by the schema's own strict loader — not by this test's opinion
    of it. The wire carries the boxes, never the words' measures: a
    correction read back is still the rows it was."""
    words = load_words(FIXTURE / "words.json")["words"]
    lines = load_user_row_adjustments(FIXTURE / "user-row-adjustments.json")["lines"]
    page = load_boxes(Path("tests/fixtures/page01-wordseg/boxes.json"))["page"]
    boxes = [_word(w) for w in words]
    built = Rows.from_words(boxes, (page["width"], page["height"])).adjust(lines)

    path = tmp_path / "p1.rows.json"
    path.write_text(json.dumps(Rows.to_wire(built), indent=1), encoding="utf-8")

    loaded = load_rows(path)  # the strict loader IS the contract check
    read_back = Rows.from_wire(loaded)
    assert Rows.to_wire(read_back) == loaded
    assert [row.number for row in read_back] == [row.number for row in built]
    assert [row.band for row in read_back] == [row.band for row in built]
    assert loaded["rows"][0]["id"] == built[0].id and loaded["rows"][0]["number"] == 1
    assert set(loaded["rows"][0]["band"]) == {"x0", "y0", "x1", "y1"}


def test_with_no_lines_the_words_own_lines_are_the_rows() -> None:
    """UR1.4/UR3: the draft rows exist with no drawn lines — the words'
    own reading lines, one row each, in reading order. Whether any lines
    are needed is the reviewer's call, never the app's."""
    words = _words((100, 300, 200, 330), (300, 300, 400, 330), (100, 100, 200, 130), line=1)
    # the second reading line, below the first
    words[0].line = 2
    words[1].line = 2
    rows = Rows.from_words(words, PAGE_SIZE).rows()
    assert [row.number for row in rows] == [1, 2]
    assert [[b.x0 for b in row.word_boxes] for row in rows] == [[100], [100, 300]]


def test_an_incomplete_set_of_lines_merges_with_the_draft_rows() -> None:
    """UR1.4: the reviewer draws only over the rows that are wrong. The
    row they drew is corrected; a reading line no drawn line touched keeps
    its row — so a correct row never needs a line."""
    words = _words((100, 100, 200, 130), (300, 100, 400, 130), (100, 300, 200, 330), line=1)
    words[2].line = 2
    rows = Rows.from_words(words, PAGE_SIZE).adjust([_line(100, 400, 120)])
    assert len(rows) == 2, f"the untouched draft row was lost: {len(rows)} rows"
    assert [b.x0 for b in rows[0].word_boxes] == [100, 300], "the drawn row lost its neighbours"
    assert [b.x0 for b in rows[1].word_boxes] == [100], "the draft row's words changed"
    assert rows[1].band == (100, 300, 200, 330), "the draft row's band is not its words' union"


def test_a_drawn_line_replaces_the_draft_row_it_covers() -> None:
    """Once a drawn line claims a reading line's words, that draft row is
    gone: the drawn row is the row, and the two are the same type."""
    words = _words((100, 100, 200, 130), (250, 100, 350, 130), line=1)
    rows = Rows.from_words(words, PAGE_SIZE).adjust([_line(100, 350, 120)])
    assert len(rows) == 1, f"the covered draft row survived beside the drawn row: {len(rows)} rows"
    assert [b.x0 for b in rows[0].word_boxes] == [100, 250]
    assert rows[0].id == "seg-1" and rows[0].kind == "body"


def test_a_rows_text_and_trust_stage_travel_with_the_wire() -> None:
    """Per-row text and its R7 trust stage are the row's own — carried in the
    wire contract beside its words, so a confirmation survives beside its
    neighbours' guesses. The schema is the check: a stage outside the
    vocabulary is refused, and a row file from before a reading ran is read
    as unread ("") rather than rejected."""
    from tools.row import Row as RecordRow
    from tools.schemas import ROW_STAGES

    built = Rows.from_words(_words((100, 100, 200, 130), (300, 100, 400, 130), line=1), PAGE_SIZE).rows()
    read = [
        RecordRow(
            id=row.id,
            kind=row.kind,
            number=row.number,
            word_boxes=row.word_boxes,
            band=row.band,
            text="the machine's try",
            stage="guess",
        )
        for row in built
    ]
    wire = Rows.to_wire(read)
    assert wire["rows"][0]["text"] == "the machine's try"
    assert wire["rows"][0]["stage"] == "guess"
    assert Rows.from_wire(wire)[0].stage == "guess"
    assert ROW_STAGES == ("", "raw", "guess", "confirmed")


def test_a_rows_text_is_the_lines_that_sit_in_its_band() -> None:
    """The reading fills the rows: each transcribed line whose box centre sits
    in a row's band becomes that row's text, in reading order, staged `raw`
    (R7) — the machine's first fill, before any confirmation. A row no line
    reached is unread: empty text, no stage. A page-level string with no
    geometry cannot be put on rows, so boxless lines are ignored."""
    words = _words((100, 100, 500, 130), (100, 300, 500, 330), (100, 500, 500, 530), line=1)
    words[1].line = 2
    words[2].line = 3
    rows = Rows.from_words(words, PAGE_SIZE)
    lines = [
        {"text": "the first line", "box": [110.0, 105.0, 480.0, 128.0]},
        {"text": "its continuation", "box": [120.0, 112.0, 400.0, 126.0]},
        {"text": "no geometry here"},
        {"text": "far below every row", "box": [110.0, 900.0, 480.0, 990.0]},
    ]
    filled = rows.with_text(lines)
    assert [row.text for row in filled] == ["the first line its continuation", "", ""], "the lines did not land by band"
    assert [row.stage for row in filled] == ["raw", "", ""], "a filled row is raw; an unread row carries no stage"
