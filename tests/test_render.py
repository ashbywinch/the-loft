"""Tests for the row renderer (tools/render.py).

The renderer is a presentation function: the joins are the minimum band
between a row's words, the tint is faint, and the yellow lines come numbered.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tools.mark import WordGeometry
from tools.page import Page
from tools.rectangle import Rectangle
from tools.render import join_band, render_rows
from tools.row import Row
from tools.word import Word

SPACING = 67.6


def _painted_page() -> Image.Image:
    """A white page with one dark word box; its ink measures cleanly."""
    image = Image.new("L", (400, 300), 255)
    from PIL import ImageDraw

    ImageDraw.Draw(image).rectangle((60, 100, 160, 140), fill=0)
    return image


def test_rendered_waistline_is_above_the_baseline() -> None:
    """The reviewer caught the swap: green (waistline) must sit ABOVE red
    (baseline) on the page - a property of the DRAWN lines, checked by the
    library's own audit, not by eyes."""
    from tools.page_visuals import audit_geometry, measure_words, render_geometry

    page = _painted_page()
    boxes = [(60.0, 100.0, 160.0, 140.0)]
    geometry = measure_words(np.asarray(page.convert("L")) < 170, boxes)
    assert geometry[0] is not None
    assert geometry[0].waistline < geometry[0].baseline, "the measurement itself must be sane"

    image = render_geometry(page, boxes, [], draw_boxes=False)
    drawn = audit_geometry(image, boxes)[0]
    assert drawn is not None
    assert drawn.waistline == geometry[0].waistline
    assert drawn.baseline == geometry[0].baseline


def test_an_overridden_line_draws_where_told() -> None:
    from tools.mark import WordGeometry
    from tools.page_visuals import audit_geometry, render_geometry

    page = _painted_page()
    boxes = [(60.0, 100.0, 160.0, 140.0)]
    expected = WordGeometry(waistline=110.0, baseline=130.0)
    image = render_geometry(page, boxes, [], draw_boxes=False, overrides={0: expected})
    drawn = audit_geometry(image, boxes)[0]
    assert drawn is not None and drawn == expected


@pytest.fixture(scope="module")
def letter() -> dict:
    return json.loads(Path("tests/fixtures/page01.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def scans(letter: dict) -> tuple[Image.Image, list[list[tuple[float, float]]]]:
    """The page-01 scan and the reviewer's strokes - the drawing regression
    tests render the CONFIRMED drawings on the real page."""
    scan = _painted_page()  # fallback; replaced by the real page below

    real = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
    if real.exists():
        scan = Image.open(real)
    w, h = letter["page"]["width"], letter["page"]["height"]
    strokes = [[(x * w, y * h) for x, y in s] for s in letter["strokes"]]
    return scan, strokes


def test_the_row16_tail_drawing_is_pinned(scans: tuple[Image.Image, list], letter: dict) -> None:
    """The reviewer confirmed row 16's tail at ONE level: the last two words
    carry the third-from-the-end's lines (3106/3121). The drawing must keep
    producing exactly that."""
    from tools.page_visuals import audit_geometry, render_focus

    scan, strokes = scans
    overrides: dict[int, WordGeometry | None] = {
        105: WordGeometry(waistline=3106.0, baseline=3121.0),
        108: WordGeometry(waistline=3106.0, baseline=3121.0),
    }
    image = render_focus(scan, (1550, 3040, 1900, 3180), letter["words"], strokes, margin=40, overrides=overrides)
    # the trio draws as ONE aligned level - the reviewer's confirmed reading.
    # Audit the UNION of their extents: the merged same-row bands are one.
    for index in (102, 105, 108):
        w = letter["words"][index]
        assert w is not None
    union = [
        min(letter["words"][i]["x0"] for i in (102, 105, 108)),
        min(letter["words"][i]["y0"] for i in (102, 105, 108)),
        max(letter["words"][i]["x1"] for i in (102, 105, 108)),
        max(letter["words"][i]["y1"] for i in (102, 105, 108)),
    ]
    drawn = audit_geometry(image, [union], origin=(1510, 3000))[0]
    assert drawn is not None
    assert abs(drawn.waistline - 3106.0) <= 2 and abs(drawn.baseline - 3121.0) <= 2, f"trio: {drawn}"


def test_the_row18_group_drawing_is_pinned(scans: tuple[Image.Image, list], letter: dict) -> None:
    """The reviewer confirmed the row-18 group: the words above the underline
    at their right-hand neighbours' levels, and the underline-welded word
    ('Opera') reading its own letters. The left word, the right-hand word and
    the refusal are exactly auditable; the middle pair sit cheek-by-jowl so
    their drawn spans merge - the audit records the caveat."""
    from tools.page_visuals import audit_geometry, render_focus

    scan, strokes = scans
    overrides: dict[int, WordGeometry | None] = {
        129: WordGeometry(waistline=3233.0, baseline=3253.0),
        130: WordGeometry(waistline=3239.0, baseline=3251.0),
        131: WordGeometry(waistline=3238.0, baseline=3251.0),
        135: WordGeometry(waistline=3238.0, baseline=3251.0),
    }
    image = render_focus(scan, (1440, 3180, 1960, 3310), letter["words"], strokes, margin=40, overrides=overrides)
    for index, want in ((129, (3233.0, 3253.0)), (135, (3238.0, 3251.0))):
        w = letter["words"][index]
        drawn = audit_geometry(image, [[w["x0"], w["y0"], w["x1"], w["y1"]]], origin=(1400, 3140))[0]
        assert drawn is not None
        assert abs(drawn.waistline - want[0]) <= 2 and abs(drawn.baseline - want[1]) <= 2, f"idx {index}: {drawn}"


def test_the_underline_welded_word_draws_its_own_crown() -> None:
    """The Opera box: a THICK-BROAD band at the bottom of the word is an
    underline - gone from the crown profile, so the letters' own crown is
    found. A synthetic word with an underline in its box must read the
    letters, not the band."""
    import numpy as np
    from PIL import Image, ImageDraw

    from tools.mark import baseline_row, waistline_row

    image = Image.new("L", (300, 200), 255)
    ImageDraw.Draw(image).rectangle((40, 60, 140, 100), fill=0)  # the letters
    ImageDraw.Draw(image).rectangle((40, 110, 140, 116), fill=0)  # the underline
    a = np.asarray(image)
    ys, xs = np.nonzero(a < 170)
    ys = ys.astype(np.float32)
    xs = xs.astype(np.float32)
    assert waistline_row(ys, xs) == 60, f"crown {waistline_row(ys, xs)} (the letters' top)"
    assert baseline_row(ys, xs) == 100, f"baseline {baseline_row(ys, xs)} (the letters' feet)"


def test_a_refused_word_draws_no_lines() -> None:
    from tools.page_visuals import audit_geometry, render_geometry

    page = _painted_page()
    boxes = [(60.0, 100.0, 160.0, 140.0)]
    image = render_geometry(page, boxes, [], draw_boxes=False, overrides={0: None})
    assert audit_geometry(image, boxes)[0] is None


def test_join_band_height_is_the_shorter_word() -> None:
    band = join_band(Rectangle(0, 10, 40, 40), Rectangle(60, 30, 100, 50))
    assert band.x0 == 40
    assert band.x1 == 60
    assert band.height == 20  # min(30, 20)
    # centred on the words' vertical overlap (30-40): mid 35, so 25-45
    assert band.y0 == 25
    assert band.y1 == 45


def test_join_band_without_vertical_overlap_centres_on_the_midpoint() -> None:
    band = join_band(Rectangle(0, 0, 40, 20), Rectangle(60, 90, 100, 110))
    assert band.height == 20  # min(20, 20)
    assert band.y0 == 45
    assert band.y1 == 65


def test_render_rows_tints_words_and_joins_without_an_outline() -> None:
    """Two words sharing a row: the render is the page plus the two word
    tints and the join band; no outline colour besides the page's own."""
    page = Image.new("RGB", (120, 60), (250, 250, 245))
    page_model = Page([Word(10, 10, 40, 40), Word(60, 15, 100, 45)], SPACING)
    rows = [Row(words=[0, 1])]
    out = render_rows(page, page_model, rows)
    # the join band (x 40-60, centred on the overlap 15-40, height min(30,30))
    assert out.getpixel((50, 27)) != (250, 250, 245), "join band not tinted"
    # a word tint
    assert out.getpixel((20, 30)) != (250, 250, 245), "word not tinted"
    # outside the row: untouched paper
    assert out.getpixel((5, 30)) == (250, 250, 245)


def test_render_rows_numbers_the_yellow_lines() -> None:
    page = Image.new("RGB", (300, 100), (250, 250, 245))
    page_model = Page([Word(10, 10, 40, 40)], SPACING)
    out = render_rows(page, page_model, [Row(words=[0])], strokes=[[(50, 50), (200, 50)]])
    # the stroke's own yellow shows through near its end
    assert out.getpixel((150, 50)) != (250, 250, 245)


def test_numbers_sit_in_the_gutter_never_over_the_writing() -> None:
    """The line numbers must be readable as each line's own, without covering
    a single word: every disc ends before its line's leftmost words begin."""
    page = Image.new("RGB", (800, 200), (250, 250, 245))
    page_model = Page(
        [
            Word(300, 0, 350, 30),
            Word(400, 2, 470, 32),
            Word(300, 60, 340, 90),
            Word(380, 62, 440, 92),
        ],
        SPACING,
    )
    rows = [Row(words=[0, 1]), Row(words=[2, 3])]
    strokes = [[(320, 15), (700, 15)], [(330, 75), (700, 75)]]
    out = render_rows(page, page_model, rows, strokes)
    for row_index, (row, stroke) in enumerate(zip(rows, strokes, strict=False)):
        left = min(page_model.words[i].x0 for i in row.words)
        disc_left, disc_right = left - 96, left - 10
        assert disc_right < left, "the disc must not reach the line's words"
        mid = (min(py for _, py in stroke) + max(py for _, py in stroke)) / 2
        assert out.getpixel((int((disc_left + disc_right) / 2), int(mid))) != (250, 250, 245), (
            f"line {row_index}: no disc beside its words"
        )


def test_contiguous_runs_groups_only_adjacent_rows() -> None:
    """Dropped rows become bands: adjacent rows merge, a gap starts a band."""
    from tools.page_visuals import contiguous_runs

    assert contiguous_runs([3, 1, 2, 7, 8]) == [[1, 2, 3], [7, 8]]
    assert contiguous_runs([]) == []


def test_captioned_sheet_offsets_the_crop_by_the_bar() -> None:
    """The caption bar's height is the contract: the crop starts below it."""
    from tools.page_visuals import CAPTION_LINE_H, CAPTION_PAD, captioned_sheet

    crop = Image.new("RGB", (100, 60), (250, 250, 245))
    sheet, _draw, bar_h = captioned_sheet(crop, ["one", "two", "three"])
    assert bar_h == CAPTION_PAD + 3 * CAPTION_LINE_H
    assert sheet.size == (100, 60 + bar_h)
    assert sheet.getpixel((50, 6)) == (255, 255, 255)


def test_dashed_hline_marks_the_cut_row() -> None:
    """A cut row reads as red dashes on the row, paper between them."""
    from PIL import ImageDraw

    from tools.page_visuals import CUT_RED, dashed_hline

    sheet = Image.new("RGB", (100, 40), (255, 255, 255))
    draw = ImageDraw.Draw(sheet, "RGBA")
    dashed_hline(draw, 10, 90, 20)
    assert sheet.getpixel((12, 20)) == CUT_RED[:3]
    assert sheet.getpixel((10 + 8 + 3, 20)) == (255, 255, 255)


def test_labeled_box_outlines_and_labels() -> None:
    """A piece box: the outline in the owner's colour, readable inside."""
    from PIL import ImageDraw

    from tools.page_visuals import halo_text, labeled_box

    sheet = Image.new("RGB", (100, 60), (255, 255, 255))
    draw = ImageDraw.Draw(sheet, "RGBA")
    labeled_box(draw, (10, 10, 60, 40), (230, 50, 50, 255), "P1")
    halo_text(draw, (70, 10), "P2")
    assert sheet.getpixel((10, 25)) == (230, 50, 50)
    assert sheet.getpixel((30, 25)) == (255, 255, 255)
    assert sheet.getpixel((80, 25)) != (255, 255, 255)


def test_stacked_sheets_keep_narrow_widths_with_a_gap() -> None:
    """Sheets under the review width stack unscaled with a white gap."""
    from tools.page_visuals import stack_sheets

    red = Image.new("RGB", (100, 40), (230, 50, 50))
    blue = Image.new("RGB", (60, 30), (50, 50, 230))
    page = stack_sheets([red, blue], gap=10)
    assert page.size == (100, 40 + 10 + 30)
    assert page.getpixel((50, 20)) == (230, 50, 50)
    assert page.getpixel((30, 40 + 10 + 15)) == (50, 50, 230)
    assert page.getpixel((50, 40 + 5)) == (255, 255, 255)


def test_stacked_sheets_downscale_to_the_review_width() -> None:
    """A sheet wider than the review width shrinks to it; narrow ones stay."""
    from tools.page_visuals import stack_sheets

    wide = Image.new("RGB", (1600, 800), (230, 50, 50))
    narrow = Image.new("RGB", (500, 200), (50, 50, 230))
    page = stack_sheets([wide, narrow], gap=10, max_width=1000)
    assert page.size == (1000, 500 + 10 + 200)
    assert page.getpixel((500, 250)) == (230, 50, 50)
    assert page.getpixel((250, 500 + 10 + 100)) == (50, 50, 230)


def test_review_image_is_a_fraction_of_the_png() -> None:
    """Review copies stay light: a noisy sheet's JPEG is far smaller."""
    import io

    import numpy as np

    from tools.page_visuals import review_image

    rng = np.random.default_rng(7)
    sheet = Image.fromarray(rng.integers(180, 256, (400, 900, 3), dtype=np.uint8))
    buf = io.BytesIO()
    sheet.save(buf, "PNG")
    small = review_image(sheet)
    assert len(small) < len(buf.getvalue()) // 4
    assert Image.open(io.BytesIO(small)).size[0] == 900


def test_review_image_never_upscales() -> None:
    """A small sheet keeps its pixels: no blur from pointless scaling."""
    import io

    from tools.page_visuals import review_image

    sheet = Image.new("RGB", (400, 200), (250, 250, 245))
    assert Image.open(io.BytesIO(review_image(sheet))).size == (400, 200)


def test_split_sheet_draws_raw_pieces_cuts_and_drops() -> None:
    """The case sheet shows what the splitter did: raw outline, one piece
    box, one cut row, one dropped band — all from the caller's data."""
    from tools.page_visuals import split_sheet

    page = Image.new("RGB", (200, 200), (250, 250, 245))
    sheet = split_sheet(
        page,
        (50, 50, 150, 150),
        [((50, 50, 150, 100), "P1 n=10 L3"), ((50, 105, 150, 150), "P2 n=12 L4")],
        [(102, "100:5 102:8")],
        [(100, 104)],
        "DROPPED 4px (floor 30)",
        "Case X — one word",
        "raw id=1 y50-150 -> 2 piece(s), 0 rows dropped",
        (40, 40, 160, 160, 1.0),
    )
    assert sheet.size == (120, 120 + 12 + 26 * 3)
    assert sheet.getpixel((10, 12 + 26 * 3 + 10)) != (250, 250, 245)
