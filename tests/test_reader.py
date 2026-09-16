"""Tests for the page reader (tools/reader.py) on a synthetic page.

The page is drawn here, so its lines and words are known by construction: the
detector must find every line, cover every word, and never put two lines in one
box. Deterministic — no network, no model, no archive, no wall-clock.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from tools.reader import read_page

PAGE_W, PAGE_H = 900, 1400
LINE_SPACING = 60
FIRST_BASELINE = 120
LINES = 18
WORDS_PER_LINE = 7
WORD_W, WORD_H = 46, 20
WORD_GAP = 34
MARGIN_X = 60
WORD_W = 46


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


@pytest.fixture(params=["split", "nosplit"])
def detected(request, tmp_path: Path) -> tuple:
    """Every pipeline test runs twice: with the splitter and without it.

    The nosplit run answers whether the mark finder alone already detects
    the words — any failure there is the detector's, not the cutter's."""
    page = tmp_path / "synthetic.png"
    words, baselines = synthetic_page(page)
    (tmp_path / "strokes.json").write_text(json.dumps({"strokes": []}), encoding="utf-8")
    read_page(page, tmp_path, split=request.param == "split")
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
    assert read_page(blank, tmp_path) == []


def test_the_baseline_is_the_row_the_letters_stand_on() -> None:
    """The baseline is where the letters stand, whatever ascenders and
    descenders do - measured on the component's own ink.

    The old estimator (the modal ink row) landed 26px high on a word whose
    letters are all x-height: the densest rows are the letter bodies, so the
    mode sits at their top. The bottom-contour mode is exact here: descender
    columns are a minority, so the most common bottom row IS the baseline.
    """
    import numpy as np

    from tools.mark import baseline_row

    baseline = 70
    ys, xs, _span = _letter_ink(baseline)
    assert baseline_row(np.array(ys, dtype=np.float32), np.array(xs, dtype=np.float32)) == baseline


def test_the_waistline_is_the_top_of_the_letters_bodies() -> None:
    """A word's font size is baseline minus waistline - the x-height - and is
    blind to ascenders and descenders, which is what box height gets wrong.

    Constructed ink: 26px letter bodies, two ascenders reaching to 46px, one
    descender to 26px below. The waistline must be the top of the bodies
    (baseline - 26), not the ascender tops.
    """
    import numpy as np

    from tools.mark import waistline_row

    baseline = 70
    ys, xs, _span = _letter_ink(baseline)
    assert waistline_row(np.array(ys, dtype=np.float32), np.array(xs, dtype=np.float32)) == baseline - 26


GAP = 4  # the whitespace between letters: a letter's rows never run full width


def _letter_ink(baseline: int, columns: int = 60, letter_w: int = 10) -> tuple[list[int], list[int], int]:
    """Letters standing on `baseline` with `GAP` whitespace between them;
    ascenders at letters 1 and 4, one descender at letter 2. Returns the ink
    and the word's total span (letters + gaps) - what an underline would span.

    The letters must not touch: welded boxes make every row run the full
    width, which no real word does and which is indistinguishable from an
    underline. The span lets a test draw an underline ACROSS the whole word."""
    ys: list[int] = []
    xs: list[int] = []
    letters = columns // letter_w
    for letter in range(letters):
        x_start = letter * (letter_w + GAP)
        top = baseline - 46 if letter in (1, 4) else baseline - 26
        bottom = baseline + 26 if letter == 2 else baseline
        for column in range(x_start, x_start + letter_w):
            for y in range(top, bottom + 1):
                ys.append(y)
                xs.append(column)
    return ys, xs, letters * letter_w + (letters - 1) * GAP


def test_an_underline_is_no_word_and_enters_no_words_measurement(tmp_path: Path) -> None:
    """An underline is NOT a word - and it never gets measured, because it is
    gone before any measurement: its component is a streak and is dropped when
    the page's words are found. The word above it therefore measures ITS OWN
    ink (the letters' bottom), and no word is emitted for the underline.

    The reviewer's ruling: 'It's not a word. We are calculating these
    measurements for words. Why are we including underlines at all?'"""
    from PIL import Image, ImageDraw

    page = tmp_path / "page.png"
    image = Image.new("L", (200, 200), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 100, 86, 120), fill=0)  # the word, standing on row 120
    draw.rectangle((40, 124, 86, 127), fill=0)  # the underline below it
    image.save(page)
    (tmp_path / "strokes.json").write_text(json.dumps({"strokes": []}), encoding="utf-8")
    read_page(page, tmp_path)

    words = json.loads((tmp_path / "words.json").read_text(encoding="utf-8"))["words"]
    assert len(words) == 1, f"underline must not be a word: {len(words)} words emitted"
    assert words[0]["baseline"] == 120, f"baseline {words[0]['baseline']} - the underline entered the word"


def _letter_ink(baseline: int, columns: int = 60, letter_w: int = 10) -> tuple[list[int], list[int], int]:
    """Letters standing on `baseline` with `GAP` whitespace between them;
    ascenders at letters 1 and 4, one descender at letter 2. Returns the ink
    and the word's total span (letters + gaps) - what an underline would span.

    The letters must not touch: welded boxes make every row run the full
    width, which no real word does and which is indistinguishable from an
    underline. The span lets a test draw an underline ACROSS the whole word."""
    ys: list[int] = []
    xs: list[int] = []
    letters = columns // letter_w
    for letter in range(letters):
        x_start = letter * (letter_w + GAP)
        top = baseline - 46 if letter in (1, 4) else baseline - 26
        bottom = baseline + 26 if letter == 2 else baseline
        for column in range(x_start, x_start + letter_w):
            for y in range(top, bottom + 1):
                ys.append(y)
                xs.append(column)
    return ys, xs, letters * letter_w + (letters - 1) * GAP


def _underline_row(ink: list[list[int]]) -> int:
    """The row of the longest continuous ink run in the word's ink - an
    underline is a flat stroke running most of the word's width, which no
    letter row is. In box height terms: the row, in the word's box, whose
    run is longest."""
    rows: dict[int, set[int]] = {}
    for dx, dy in ink:
        rows.setdefault(dy, set()).add(dx)
    best, best_len = 0, 0
    for y, cols in rows.items():
        ordered = sorted(cols)
        run = 1
        longest = 1
        for c1, c2 in zip(ordered, ordered[1:], strict=False):
            run = run + 1 if c2 == c1 + 1 else 1
            longest = max(longest, run)
        if longest > best_len:
            best, best_len = y, longest
    return best


@pytest.fixture(scope="module")
def page01_marks() -> dict:
    """The mark finder alone: ink_mask + artifacts + find_marks. No line
    fitting, no box splitting. User 2026-09-14: the four-word block
    (upper pair over Myra Hess) must arrive as left and right marks apart,
    each spanning both lines (the vertical weld is the splitter's job)."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from PIL import Image

    from tools.mark import find_marks
    from tools.reader import artifacts, ink_mask

    scan = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
    page = Image.open(scan)
    mask = ink_mask(page)
    artifacts(mask)
    return {s.id: s for s in find_marks(mask)}


def test_marks_separate_the_blocks_left_and_right_pair(page01_marks) -> None:
    """Left mark (Myra stack) and right mark (Hess stack) are apart: no one
    small mark covers both middles (x~1900 and x~1975 at y~2570)."""
    left_ids = _covering(page01_marks, 1900, 2570)
    right_ids = _covering(page01_marks, 1975, 2570)
    assert left_ids, "no small mark covers the left pair's middle"
    assert right_ids, "no small mark covers the right pair's middle"
    assert left_ids.isdisjoint(right_ids), f"left and right share mark(s): {left_ids & right_ids}"


def test_each_mark_spans_both_lines(page01_marks) -> None:
    """Each side's mark welds the upper word to the lower: the left mark
    covering (1900, 2570) also reaches the upper line (y <= 2540), and so
    does the right mark covering (1975, 2570)."""
    from tools.mark import SCALE

    for x, y in ((1900, 2570), (1975, 2570)):
        covering = list(_covering(page01_marks, x, y))
        assert covering, f"no small mark covers ({x}, {y})"
        tops = [page01_marks[sid].y0 * SCALE for sid in covering]
        assert min(tops) <= 2545, f"mark(s) {covering} start at {min(tops):.0f}, reach no upper word"


def _covering(page01_marks, x: float, y: float) -> set[str]:
    """Ids of small marks covering point (x, y) in page px — the giant
    welded shape 4847 spans the whole block and is excluded by area."""
    from tools.mark import SCALE

    found = set()
    for s in page01_marks.values():
        if s.area >= 2000:
            continue
        if s.x0 * SCALE <= x <= s.x1 * SCALE and s.y0 * SCALE <= y <= s.y1 * SCALE:
            found.add(s.id)
    return found


@pytest.fixture(scope="module")
def page01_shapes() -> tuple:
    """The real page-01 detector state: connected marks + fitted lines.

    The splitter's inputs, run once per session — the user-verified one-word
    cases below pin its outputs against these, so a change in find_marks or
    fit_lines that moves a case fails loudly here, not silently in a sheet.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from PIL import Image

    from tools.mark import find_marks
    from tools.pagescale import PageScale, line_ratio, traced_pitch, writing_scale
    from tools.reader import artifacts, fit_lines, ink_mask

    scan = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
    fixture = Path(__file__).parent / "fixtures" / "page01-wordseg"
    page = Image.open(scan)
    strokes = json.loads((fixture / "strokes.json").read_text())["strokes"]
    mask = ink_mask(page)
    artifacts(mask)
    shapes = find_marks(mask)
    traced = sorted(float(np.median([p[1] for p in s])) * page.height / 2 for s in strokes)
    ratio = line_ratio(traced_pitch(traced), writing_scale([s.height for s in shapes]))
    scale = PageScale.of([s.height for s in shapes], ratio)
    return {s.id: s for s in shapes}, fit_lines(shapes, scale), scale


# Live splitter status, measured 2026-09-14 against the min-overlap waist
# rule (WAIST_RUN=10, WAIST_OVERLAP=0.5) — the status each pin below asserts.
# Whole (1 piece): 19583, 3780, 22082. Split: 4503→2, 9690→2, 6475→2,
# 5555→3, 1970→2, 683→3, 2723→2, 2875→2, 2911→2, 5514→2, 23194→3, 23150→2,
# 4847→4. The one-word pins below FAIL on this code: that is the open defect
# the waist-rule tunings chase, not a passing suite. Do not mark them green
# until the splitter earns it.
_ONE_WORD_CASES = {
    "19583": 1,
    "4503": 1,
    "9690": 1,
    "6475": 1,
    "5555": 1,
    "3780": 1,
    "1970": 1,
    "683": 1,
}


@pytest.mark.parametrize("raw_id", sorted(_ONE_WORD_CASES))
def test_one_word_is_never_split(page01_shapes, raw_id: str) -> None:
    """A connected word stays one mark: the row-to-line assignment may wobble
    mid-body, but the ink never narrows to a waist there, so no cut is real."""
    from tools.reader import split_shapes

    by_id, lines, scale = page01_shapes
    got = split_shapes([by_id[raw_id]], lines, scale.unit)
    assert len(got) == _ONE_WORD_CASES[raw_id], (
        f"id={raw_id}: {len(got)} pieces ({[(int(p.y0 * 2), int(p.y1 * 2)) for p in got]}), want one whole word"
    )


@pytest.fixture(scope="module")
def page01_writing() -> tuple:
    """The writing as the pipeline finds it: ink_mask + artifacts + the
    find_writing fixpoint (which strips the rules and underlines)."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from PIL import Image

    from tools.reader import artifacts, find_writing, ink_mask

    scan = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
    fixture = Path(__file__).parent / "fixtures" / "page01-wordseg"
    strokes = json.loads((fixture / "strokes.json").read_text())["strokes"]
    page = Image.open(scan)
    mask = ink_mask(page)
    artifacts(mask)
    traced = sorted(float(np.median([p[1] for p in s])) * page.height / 2 for s in strokes)
    writing = find_writing(mask, traced)
    return {s.id: s for s in writing.marks}, writing.lines, writing.scale, writing.stripped


def test_an_underline_does_not_join_words(page01_writing) -> None:
    """User 2026-09-16: 'the words are only joined by the underline. We
    shouldn't consider an underline as joining anything.' The ink that arrived
    as one mark holding five words under one underline therefore comes back as
    five separate marks — the underline's ink is out of the raster."""
    from tools.mark import SCALE

    marks, _lines, _scale, _stripped = page01_writing
    window = [
        s
        for s in marks.values()
        if s.x0 * SCALE >= 1164 and s.x1 * SCALE <= 1802 and s.y0 * SCALE >= 3640 and s.y1 * SCALE <= 3718
    ]
    assert len(window) == 5, f"{len(window)} marks in the five-word window, want 5"


def test_the_bug_keeps_its_main_piece_whole(page01_shapes) -> None:
    """id=4847's lower body (y2680–2768 today): the waist rule merges the
    mid-body flip at y2710 (ink widening 71→89→115 straight through it), so
    the body stays one piece. The y2680 cut stands: 1–2px rows above it."""
    from tools.mark import SCALE
    from tools.reader import split_shapes

    by_id, lines, scale = page01_shapes
    got = split_shapes([by_id["4847"]], lines, scale.unit)
    main = [p for p in got if p.y1 * SCALE >= 2760]
    assert len(main) == 1, f"lower body split in {len(main)}: {[int(p.y0 * SCALE) for p in main]}"
    assert main[0].y0 * SCALE <= 2700, f"main piece starts at {main[0].y0 * SCALE:.0f}, cut ate its crown"


def test_the_split_pair_is_one_word(page01_shapes) -> None:
    """User 2026-09-16, ruled on the zoomed cut rows: raw 5514 is a SINGLE
    word and must not be divided. This supersedes the 2026-09-13 pin ('renders
    75 + 81 are two parts of ONE word... the splitter must keep them apart'),
    which was taken from the render boxes rather than from the ink."""
    from tools.reader import split_shapes

    by_id, lines, scale = page01_shapes
    got = split_shapes([by_id["5514"]], lines, scale.unit)
    assert len(got) == 1, f"id=5514: {len(got)} pieces, want one whole word"


def test_the_pupil_block_reads_four_words(page01_shapes) -> None:
    """User 2026-09-16: the block reads 'Pupil of / Myra Hess' — four words.
    Rulings from the case sheets: raw 2723 is ONE digit (the mid-body cut
    y2556 is a chop, must refuse). Raw 2875's upper piece is a word fragment
    that must NOT be split off (user 2026-09-16: 'that upper piece is indeed a
    word fragment that shouldn't be split. That's unrelated to the fact that
    the picture contains two words'), so 2875 stays one piece. Raw 2911 welds
    the word on the line above to the word below and that separation is
    correct (2 pieces). No rule/underline is claimed in 2875."""
    from tools.reader import split_shapes

    by_id, lines, scale = page01_shapes
    pupil = split_shapes([by_id["2723"]], lines, scale.unit)
    of = split_shapes([by_id["2875"]], lines, scale.unit)
    myra_hess = split_shapes([by_id["2911"]], lines, scale.unit)
    assert len(pupil) == 1, f"2723 (one digit) split in {len(pupil)}"
    assert len(of) == 1, f"2875 gave {len(of)} piece(s), want 1 (the fragment stays with its word)"
    assert len(myra_hess) == 2, f"2911 (upper word + lower word) gave {len(myra_hess)} piece(s), want 2"


def test_stacked_pair_stays_two_words(page01_shapes) -> None:
    """User 2026-09-13: render 327 (raw 23194's upper piece) sits above a
    separate lower word with clean paper between — the split is correct and
    the pieces must stay two words, never merged."""
    from tools.mark import SCALE
    from tools.reader import split_shapes

    by_id, lines, scale = page01_shapes
    got = split_shapes([by_id["23194"]], lines, scale.unit)
    assert len(got) == 2, f"id=23194: {len(got)} pieces, want the two words apart"
    assert got[0].y1 * SCALE < got[1].y0 * SCALE, "the stacked pieces overlap"


def test_the_gapped_marks_keep_their_own_pieces(page01_shapes) -> None:
    """User 2026-09-16, ruled against each mark's OWN outlined sheet: raw
    22082 (render 324) is ONE piece; raw 23150 (render 332) is TWO — its cut
    stands. The earlier 'each raw shape stays its own piece' ruling was given
    against a sheet that outlined 22082 while the question named 23150."""
    from tools.reader import split_shapes

    by_id, lines, scale = page01_shapes
    assert len(split_shapes([by_id["22082"]], lines, scale.unit)) == 1, "render 324 (22082) split"
    assert len(split_shapes([by_id["23150"]], lines, scale.unit)) == 2, "render 332 (23150) did not split in two"


# Marks the user ruled hold more than one word (2026-09-16): welded ink the
# detector reports as one word. 18092 = "life" over "facilities"; 7105 =
# "some composition". 14187's five words are covered by the underline test
# below — they were welded by the underline, not by each other.
_WELDED_CASES = {
    "18092": 2,
    "7105": 2,
}


@pytest.mark.parametrize("raw_id", sorted(_WELDED_CASES))
def test_a_welded_mark_yields_its_words(page01_shapes, raw_id: str) -> None:
    """A mark holding several words comes back as several pieces: the words
    are welded (no clean column gap), so the splitter must find them anyway.
    User rulings 2026-09-16."""
    from tools.reader import split_shapes

    by_id, lines, scale = page01_shapes
    got = split_shapes([by_id[raw_id]], lines, scale.unit)
    assert len(got) == _WELDED_CASES[raw_id], f"id={raw_id}: {len(got)} piece(s), want {_WELDED_CASES[raw_id]}"


def test_a_detached_line_is_a_rule_or_an_underline_and_a_fragment_is_neither(page01_shapes) -> None:
    """A line the writer drew cedes from the words; a word's fragment does not.

    User 2026-09-16, on the boxed pieces: 7105's lower piece is a rule (it is
    not directly aligned with the words above), 9676's is an underline (it is),
    and 683's bottom fragment, 2875's upper piece and 6475's first piece are not
    lines at all — they stay with their words."""
    from tools.reader import split_shapes

    by_id, lines, scale = page01_shapes
    pieces = split_shapes(list(by_id.values()), lines, scale.unit)

    def kinds(mark_id: str) -> list[str | None]:
        family = [piece for piece in pieces if piece.id.split("_")[0] == mark_id]
        return [piece.classify_line([o for o in family if o is not piece], pieces, scale.unit) for piece in family]

    assert kinds("7105") == [None, "rule"], f"7105: {kinds('7105')}, want its lower piece a rule"
    assert kinds("9676") == [None, "underline"], f"9676: {kinds('9676')}, want its lower piece an underline"
    for mark_id in ("683", "2875", "6475"):
        assert not any(kinds(mark_id)), f"{mark_id}: {kinds(mark_id)} — none of that ink is a line"
