"""Tests for the box detector (tools/boxdet.py) on a synthetic page.

The page is drawn here, so its lines and words are known by construction: the
detector must find every line, cover every word, and never put two lines in one
box. Deterministic — no network, no model, no archive, no wall-clock.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from tools.boxdet import detect

PAGE_W, PAGE_H = 900, 1400
LINE_SPACING = 60
FIRST_BASELINE = 120
LINES = 18
WORDS_PER_LINE = 7
WORD_W, WORD_H = 46, 20
WORD_GAP = 34
MARGIN_X = 60


def synthetic_page(path: Path) -> tuple[list[tuple[int, int, int, int]], list[int]]:
    """A page of 'words' on evenly spaced lines; returns their boxes and baselines."""
    image = Image.new("L", (PAGE_W, PAGE_H), 255)
    draw = ImageDraw.Draw(image)
    words: list[tuple[int, int, int, int]] = []
    baselines: list[int] = []
    for line in range(LINES):
        baseline = FIRST_BASELINE + line * LINE_SPACING
        baselines.append(baseline)
        for word in range(WORDS_PER_LINE):
            x0 = MARGIN_X + word * (WORD_W + WORD_GAP)
            box = (x0, baseline - WORD_H, x0 + WORD_W, baseline)
            draw.rectangle(box, fill=0)
            words.append(box)
    image.save(path)
    return words, baselines


def inside(point: tuple[float, float], poly: list[list[float]]) -> bool:
    x, y = point
    hits = False
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hits = not hits
    return hits


@pytest.fixture()
def detected(tmp_path: Path) -> tuple[list[list[list[float]]], list[tuple[int, int, int, int]], list[int]]:
    page = tmp_path / "synthetic.png"
    words, baselines = synthetic_page(page)
    (tmp_path / "strokes.json").write_text(json.dumps({"strokes": []}), encoding="utf-8")
    detect(page, tmp_path)
    boxes = json.loads((tmp_path / "boxes.json").read_text(encoding="utf-8"))["boxes"]
    return boxes, words, baselines


def test_every_line_gets_exactly_one_box(detected) -> None:
    boxes, _, baselines = detected
    assert len(boxes) == len(baselines), f"{len(baselines)} lines drawn, {len(boxes)} boxes found"


def test_every_word_is_inside_exactly_one_box(detected) -> None:
    boxes, words, _ = detected
    for box in words:
        centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        hits = [one for one in boxes if inside(centre, one)]
        assert len(hits) == 1, f"word at {centre} is inside {len(hits)} boxes"


def test_no_box_holds_two_lines(detected) -> None:
    """A box whose height exceeds the line spacing has swallowed its neighbour."""
    boxes, _, _ = detected
    for box in boxes:
        ys = [corner[1] for corner in box]
        assert max(ys) - min(ys) < LINE_SPACING, f"box spans {max(ys) - min(ys):.0f}px, spacing is {LINE_SPACING}"


def test_a_line_with_no_ink_gets_no_box(tmp_path: Path) -> None:
    """The detector reports what it finds: a blank page yields no boxes."""
    blank = tmp_path / "blank.png"
    Image.new("L", (PAGE_W, PAGE_H), 255).save(blank)
    (tmp_path / "strokes.json").write_text(json.dumps({"strokes": []}), encoding="utf-8")
    assert detect(blank, tmp_path) == []


def test_the_baseline_is_the_row_the_letters_stand_on() -> None:
    """The baseline is where the letters stand, whatever ascenders and
    descenders do - measured on the component's own ink.

    The old estimator (the modal ink row) landed 26px high on a word whose
    letters are all x-height: the densest rows are the letter bodies, so the
    mode sits at their top. The bottom-contour mode is exact here: descender
    columns are a minority, so the most common bottom row IS the baseline.
    """
    from tools.boxdet import baseline_row

    baseline = 70
    ys: list[int] = []
    xs: list[int] = []
    for column in range(60):  # six 10-wide letters
        letter = column // 10
        top = baseline - 46 if letter in (1, 4) else baseline - 26  # two ascenders
        bottom = baseline + 26 if letter == 2 else baseline  # one descender
        for y in range(top, bottom + 1):
            ys.append(y)
            xs.append(column)
    import numpy as np

    assert baseline_row(np.array(ys), np.array(xs)) == baseline


def test_the_waistline_is_the_top_of_the_letters_bodies() -> None:
    """A word's font size is baseline minus waistline - the x-height - and is
    blind to ascenders and descenders, which is what box height gets wrong.

    Constructed ink: 26px letter bodies, two ascenders reaching to 46px, one
    descender to 26px below. The waistline must be the top of the bodies
    (baseline - 26), not the ascender tops.
    """
    import numpy as np

    from tools.boxdet import waistline_row

    baseline = 70
    ys: list[int] = []
    xs: list[int] = []
    for column in range(60):  # six 10-wide letters
        letter = column // 10
        top = baseline - 46 if letter in (1, 4) else baseline - 26
        bottom = baseline + 26 if letter == 2 else baseline
        for y in range(top, bottom + 1):
            ys.append(y)
            xs.append(column)
    assert waistline_row(np.array(ys), np.array(xs)) == baseline - 26
