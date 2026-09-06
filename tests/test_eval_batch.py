"""Tests for the batch ink-column runner (2026-08-25).

Written AFTER the first run exposed three bugs (37 pages skipped for
want of a full-page fallback; good layouts overwritten by worse re-runs;
hardcoded orientation 0 failing Gate A). These pin the fixes so they
cannot regress silently; the orientation rule lives beside its inverse
(aspect_consistent) so the two cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from tools.box import aspect_consistent, orientation_from_aspect
from tools.eval_batch import normalized_bands, prep_panel


def _write_png(tmp_path: Path, name: str = "page-01.png", size: tuple[int, int] = (2000, 1500)) -> Path:
    p = tmp_path / name
    Image.new("RGB", size, "white").save(p)
    return p


def test_clearly_wide_box_is_horizontal() -> None:
    assert orientation_from_aspect([0.0, 0.0, 1000.0, 100.0]) == 0


def test_clearly_tall_box_is_vertical() -> None:
    # the postcard-message shape: 65x396 refused as 'orientation 0.0'
    assert orientation_from_aspect([0.0, 0.0, 65.0, 396.0]) == 90


def test_near_square_box_defaults_horizontal() -> None:
    assert orientation_from_aspect([0.0, 0.0, 300.0, 200.0]) == 0


def test_every_answer_passes_its_own_gate() -> None:
    # the property that failed in production: whatever this returns,
    # aspect_consistent must accept it — else Gate A refuses the page.
    boxes = [
        [0.0, 0.0, 1000.0, 100.0],
        [0.0, 0.0, 65.0, 396.0],
        [0.0, 0.0, 300.0, 200.0],
        [0.0, 0.0, 149.0, 487.0],  # '1.85' refusal shape
        [0.0, 0.0, 16.0, 111.0],  # 'EDUCATION OFFICER' refusal shape
        [0.0, 0.0, 500.0, 501.0],  # square-ish
    ]
    for box in boxes:
        assert aspect_consistent(orientation_from_aspect(box), box)


def test_no_layout_uses_the_full_page(tmp_path) -> None:
    # 37 of 38 photo pages were skipped because this raised instead.
    image_path = _write_png(tmp_path, size=(2000, 1500))
    prep = prep_panel(image_path, None, tmp_path, "p1")
    assert prep is not None
    assert (prep["x0"], prep["y0"]) == (0, 0)
    assert (prep["w"], prep["h"]) == (2000, 1500)
    assert Path(prep["path"]).exists()


def test_layout_boxes_define_the_crop(tmp_path) -> None:
    image_path = _write_png(tmp_path)
    layout = {"lines": [{"box": [100, 200, 800, 400]}], "unmatched": [{"box": [50, 900, 600, 1100]}]}
    prep = prep_panel(image_path, layout, tmp_path, "p1")
    assert prep is not None
    assert (prep["x0"], prep["y0"]) == (50, 200)
    assert (prep["w"], prep["h"]) == (750, 900)


def test_layout_without_any_box_returns_none(tmp_path) -> None:
    image_path = _write_png(tmp_path)
    assert prep_panel(image_path, {"lines": [], "unmatched": []}, tmp_path, "p1") is None


def test_bands_scale_to_the_panel_s_true_height() -> None:
    # The model returns NORMALIZED 0-1000 bands; matching compares them
    # against the measured unions in PANEL PIXELS (_overlap_assignments).
    # The first run hardcoded 1600 — every other panel height silently
    # shifted every overlap onto the wrong row.
    lines = ["one", "two"]
    boxes = {0: [0.0, 0.0, 1000.0, 250.0], 1: [0.0, 500.0, 1000.0, 750.0]}
    bands = normalized_bands(lines, boxes, frame_h=2000)
    assert bands[0][:2] == (0.0, 500.0)
    assert bands[1][:2] == (1000.0, 1500.0)
    assert [b[2] for b in bands] == ["one", "two"]


def test_band_indexes_align_with_their_lines() -> None:
    # A band whose index exceeds the line count is dropped (the model
    # sometimes emits a box for a line it did not return text for).
    bands = normalized_bands(["only"], {0: [0.0, 0.0, 1000.0, 100.0], 5: [0.0, 500.0, 1000.0, 600.0]}, frame_h=1000)
    assert len(bands) == 1


def test_page_10_offset_bug_crop_space_becomes_page_space() -> None:
    """The crop-path offset bug (2026-08-25): prep_panel crops to a stale
    layout's bounds, detection runs in CROP space, and the assembly wrote
    those coordinates verbatim — page-10 served every box shifted up by
    the crop origin while the handwriting sat lower. Unions must be
    translated into page space."""
    from tools.ink import offset_box

    assert offset_box([10.0, 20.0, 110.0, 60.0], 500, 900) == [510.0, 920.0, 610.0, 960.0]
    assert offset_box([0.0, 0.0, 10.0, 10.0], 0, 0) == [0.0, 0.0, 10.0, 10.0]


def test_fill_unlabeled_labels_reads_only_inky_empty_rows() -> None:
    """The label-completeness lever (2026-08-26): pages like page-12 and
    the birth certs refuse on EMPTY-LABEL rows although the ink is
    there — the VLM under-read. Each such row gets one targeted read of
    its own clip; the single-line reading fills the label. Reads happen
    ONLY for inky, unlabeled rows; a failed read leaves the row empty
    (the page refuses honestly rather than inventing)."""
    from PIL import Image, ImageDraw

    from tools.eval_batch import fill_unlabeled_labels

    im = Image.new("L", (400, 300), 255)
    d = ImageDraw.Draw(im)
    d.rectangle([10, 10, 150, 40], fill=0)  # row 0 ink
    d.rectangle([10, 62, 150, 92], fill=0)  # row 1 ink (the empty one)
    d.rectangle([10, 110, 150, 140], fill=0)  # row 2 ink

    unions = [
        [5.0, 5.0, 155.0, 45.0],
        [5.0, 60.0, 155.0, 100.0],
        [5.0, 105.0, 155.0, 145.0],
        [5.0, 160.0, 155.0, 200.0],
    ]
    calls: list[tuple[int, int, int, int]] = []

    def read(box):
        calls.append((int(box[0]), int(box[1]), int(box[2]), int(box[3])))
        return "filled line"

    labels = fill_unlabeled_labels(["first", "", "third"], unions, im, read)
    assert labels == ["first", "filled line", "third"]
    assert len(calls) == 1, calls  # only the empty INKY row was read

    # a blank-region empty row is not read (the gates refuse it anyway)
    fill_unlabeled_labels(["", "", "x", ""], unions, im, read)
    assert len(calls) == 3  # rows 0+1 (inky empties) read; row 3 (blank) skipped

    # a failed read leaves the row empty — honesty over invention
    def failing_read(box):
        return None

    labels3 = fill_unlabeled_labels(["first", "", "third"], unions, im, failing_read)
    assert labels3 == ["first", "", "third"]


def test_fill_survives_a_failing_clip_read() -> None:
    """The crash class (2026-08-26): a clip read that RAISES (the model
    spent the whole budget on reasoning — VlmError) must not abort the
    batch; the row stays empty and the page refuses honestly."""
    from PIL import Image, ImageDraw

    from tools.eval_batch import fill_unlabeled_labels

    im = Image.new("L", (400, 300), 255)
    ImageDraw.Draw(im).rectangle([10, 62, 150, 92], fill=0)
    unions = [[5.0, 60.0, 155.0, 100.0]]

    def exploding_read(box):
        raise RuntimeError("vision model produced only reasoning tokens")

    labels = fill_unlabeled_labels(["", "second"], unions, im, exploding_read)
    assert labels == ["", "second"]  # no crash, no invented label


def test_needs_row_reads_detects_the_under_read() -> None:
    """The birth-cert class (2026-08-26): 40 measured rows but 16 VLM
    lines — the model under-read the dense form and proportional
    matching smeared 16 lines over 40 rows (a 21px-tall box holding a
    20-char label). When the model's line count falls far below the
    measured rows, matching cannot be trusted: every row gets its own
    clip read instead. A healthy letter (21 rows, 25 lines) stays on
    the cheap path."""
    from tools.eval_batch import needs_row_reads

    assert needs_row_reads(40, 16)
    assert needs_row_reads(20, 6)
    assert not needs_row_reads(21, 25)
    assert not needs_row_reads(5, 2)  # tiny pages: the rec over-splits
    assert not needs_row_reads(40, 30)  # within reach of matching


def test_tile_detect_offsets_and_dedupes(tmp_path) -> None:
    """The tile pass (2026-08-28): a page refusing on fragments may have
    handwriting the full-page detection under-segments (the 4000px
    max_side_limit caps the internal resize; small line extensions
    merge into the body words — page-01's 'margin notes' are the
    lines' own starts). A 2D grid of ~1300px tiles gets the short side
    upscaled to the 2000px limit while the long side stays under the
    4000px cap: ~1.4-1.5x effective resolution. Crop-local boxes offset
    to page space; the overlap zones' duplicates dedupe."""
    from PIL import Image as PILImage

    from tools.eval_batch import _tile_detect

    image = PILImage.new("L", (1000, 2500), 255)

    def fake_detect(_engine, crop_path):
        # tile-0 reports (10,1200,50,1250); tile-1 reports the SAME
        # physical box (its crop-local y 100-150): the horizontal
        # overlap zone's duplicate. Both map to page (10,1200,50,1250).
        if crop_path.name == "tile-0.png":
            return [[10.0, 1200.0, 50.0, 1250.0]]
        if crop_path.name == "tile-1.png":
            return [[10.0, 100.0, 50.0, 150.0]]
        return []

    pieces = _tile_detect(image, fake_detect, tmp_path, overlap=300)
    # 1000x2500 -> one column, two horizontal tiles (y 0-1400, 1100-2500);
    # the duplicate dedupes to exactly ONE page-space piece
    assert pieces == [[10.0, 1200.0, 50.0, 1250.0]], pieces


def test_tile_detect_drops_noise_slivers(tmp_path) -> None:
    """The upscaled tiles over-detect page specks (2026-08-28: 17x3px
    boxes clustered into absurd rows on page-01). The tile pass drops
    sub-20px pieces — real text at this scan scale is 40-70px tall."""
    from PIL import Image as PILImage

    from tools.eval_batch import _tile_detect

    image = PILImage.new("L", (1000, 2500), 255)

    def fake_detect(_engine, crop_path):
        if crop_path.name == "tile-0.png":
            return [[10.0, 10.0, 27.0, 13.0], [100.0, 100.0, 160.0, 160.0]]
        return [[10.0, 10.0, 27.0, 13.0]]  # a sliver in the overlap zone

    pieces = _tile_detect(image, fake_detect, tmp_path)
    # the 17x3 slivers (both tiles) are dropped; the 60x60 text piece
    # survives exactly once
    assert pieces == [[100.0, 100.0, 160.0, 160.0]], pieces


def test_ink_layout_boxes_split_item_and_annotation(tmp_path) -> None:
    """The ink-layout (2026-08-28): a letter's dense cursive has margin
    notes (annotations) interleaving with the main text — boxing them
    together as a paragraph mixes their sense. The ink-layout extracts
    the lines from the ADAPTIVE ink (local median - 35: the scan's
    shading is not ink), then x-segments each line: a line whose ink
    has a real gap (the item's end vs the annotation's start) becomes
    TWO boxes; a continuous line stays ONE box."""
    from PIL import Image as PILImage

    from tools.eval_batch import ink_layout_boxes

    image = PILImage.new("L", (1000, 400), 250)
    px = image.load()
    assert px is not None

    # 1px strokes at every y (a 4x4 block median stays at the paper
    # level — the real handwriting's thin strokes) — the projection
    # through the MID column is contiguous so the lines band cleanly
    def dashes(y_band: tuple[int, int], x_runs: list[tuple[int, int]]) -> None:
        # every FOURTH row: the real handwriting's strokes are sparse
        # enough that a 4x4 block median stays at the paper level AND
        # has_ink's box median does too (a >50% dark box makes the ink
        # its own paper) — real cursive strokes cover ~10-15% of the box
        for y in range(y_band[0], y_band[1], 4):
            for x0, x1 in x_runs:
                for x in range(x0, x1 + 1):
                    px[x, y] = 90

    dashes((102, 134), [(50, 100), (150, 200), (250, 300), (350, 400)])  # line 1's item
    dashes((102, 134), [(600, 650), (700, 750), (800, 850), (880, 900)])  # line 1's annotation
    # a thin descender bridge touching line 2's ascender (the dense-cursive
    # interleaving: 3px wide, connecting y 133 to y 162)
    for y in range(134, 162):
        for x in range(304, 307):
            px[x, y] = 90
    dashes((162, 194), [(x0, x1) for x0 in range(50, 900, 100) for x1 in (x0 + 50,)])  # line 2: continuous

    boxes = ink_layout_boxes(image)
    # the two lines separate despite the bridge; line 1 splits at the gap
    line1 = sorted(b for b in boxes if b[1] >= 100 and b[3] <= 141)
    line2 = sorted(b for b in boxes if b[1] >= 159)
    assert len(line1) == 2, line1  # the item + the annotation
    assert len(line2) == 1, line2  # the continuous line
    assert abs(line1[0][0] - 50) < 5 and abs(line1[0][2] - 400) < 5, line1
    assert abs(line1[1][0] - 600) < 5 and abs(line1[1][2] - 900) < 5, line1
    assert abs(line2[0][0] - 50) < 5 and abs(line2[0][2] - 900) < 5, line2


def test_ink_layout_boxes_drop_noise_slivers() -> None:
    """The ink-layout's x-runs keep the 40px minimum — a lone speck or a
    thin stray mark never becomes a box (2026-08-28: the upscaled tile
    detections produced 17x3px boxes; the ink runs have the same noise
    class at the low end)."""
    from PIL import Image as PILImage

    from tools.eval_batch import ink_layout_boxes

    image = PILImage.new("L", (1000, 400), 250)
    px = image.load()
    assert px is not None
    for y in range(102, 134, 4):
        for x in range(50, 401):
            px[x, y] = 90  # a real line
    for y in range(200, 202):  # a 30px-wide speck run
        for x in range(600, 631):
            px[x, y] = 90

    boxes = ink_layout_boxes(image)
    assert len(boxes) == 1, boxes  # only the real line
    assert abs(boxes[0][0] - 50) < 5 and abs(boxes[0][2] - 400) < 5, boxes


def test_fill_unlabeled_labels_tolerates_none_labels() -> None:
    """The ink-layout path crashed the whole batch (2026-08-28): its
    labels come from _safe_row_read, which returns None on a failed
    read — fill_unlabeled_labels called label.strip() on it. None is
    an empty label: the inky row gets its targeted read."""
    from PIL import Image, ImageDraw

    from tools.eval_batch import fill_unlabeled_labels

    im = Image.new("L", (400, 300), 255)
    d = ImageDraw.Draw(im)
    d.rectangle([10, 10, 150, 40], fill=0)
    d.rectangle([10, 62, 150, 92], fill=0)  # the None row's ink

    unions = [[5.0, 5.0, 155.0, 45.0], [5.0, 60.0, 155.0, 100.0]]
    calls: list[tuple[int, int, int, int]] = []

    def read(box):
        calls.append((int(box[0]), int(box[1]), int(box[2]), int(box[3])))
        return "filled"

    labels = fill_unlabeled_labels(["first", None], unions, im, read)
    assert labels == ["first", "filled"], labels
    assert len(calls) == 1, calls  # only the None row was read


def test_fill_unlabeled_labels_failed_read_leaves_empty_not_none() -> None:
    """The ink-layout's second crash (2026-08-28): a FAILED read left
    the label None (the fill's 'row stays empty' promise was broken —
    the gates called text.strip() on it). The row must become an empty
    string: the page refuses honestly, the batch survives."""
    from PIL import Image, ImageDraw

    from tools.eval_batch import fill_unlabeled_labels

    im = Image.new("L", (400, 300), 255)
    ImageDraw.Draw(im).rectangle([10, 62, 150, 92], fill=0)

    unions = [[5.0, 60.0, 155.0, 100.0]]

    def failing_read(box):
        raise RuntimeError("the VLM budget ran out")

    labels = fill_unlabeled_labels([None], unions, im, failing_read)
    assert labels == [""], labels  # empty, never None


def test_ink_layout_boxes_drop_shading_regions() -> None:
    """The raw-ink x-runs catch the scan's SHADING band (light-gray
    pixels 180-200, no dark text) and made no_ink boxes (2026-08-28:
    9 of 60 on page-01). has_ink (median - 35) is the honest test: a
    region whose pixels are all near its own median is shading, not
    text. The dark text line survives."""
    from PIL import Image as PILImage

    from tools.eval_batch import ink_layout_boxes

    image = PILImage.new("L", (1000, 400), 250)
    px = image.load()
    assert px is not None
    for y in range(102, 134, 4):  # the real dark line
        for x in range(400, 701):
            px[x, y] = 90
    # a light-gray shading region at the SAME y-bands, x-separated from
    # the text (gap > the word-merge): the x-run makes a box of it —
    # has_ink must drop it (its pixels are all near its own median)
    for y in range(102, 134):
        for x in range(0, 221):
            px[x, y] = 190

    boxes = ink_layout_boxes(image)
    assert len(boxes) == 1, boxes  # only the dark line; the shading dropped
    assert abs(boxes[0][0] - 400) < 5 and abs(boxes[0][2] - 700) < 5, boxes


def test_ink_layout_boxes_drop_decoration_strips() -> None:
    """The underlines/swirls (2026-08-28: the page's 'Bottom
    Decoration' read as '—' by the VLM) are flat-wide strips (h=14-20
    vs the letter's 27-70px text lines) — the ink-layout drops runs
    shorter than 25px: they are ink, but not text."""
    from PIL import Image as PILImage

    from tools.eval_batch import ink_layout_boxes

    image = PILImage.new("L", (1000, 400), 250)
    px = image.load()
    assert px is not None
    for y in range(102, 134, 4):  # the real dark line
        for x in range(50, 401):
            px[x, y] = 90
    # a 22px-tall decoration band: staggered 5px dashes at every row (a
    # swirl/underline — the box's median stays at the paper level,
    # has_ink passes; the band forms): the min-height drops it
    for y in range(200, 222):
        for x in range(100 + (y % 3) * 7, 700, 40):
            for xx in range(x, min(x + 5, 700)):
                px[xx, y] = 90

    boxes = ink_layout_boxes(image)
    assert len(boxes) == 1, boxes  # only the text line; the strip dropped
    assert abs(boxes[0][0] - 50) < 5 and abs(boxes[0][2] - 400) < 5, boxes


def test_gate_layout_glyph_check_can_be_disabled_for_ink_truth_boxes() -> None:
    """The ink-layout's boxes ARE the ink (2026-08-28) — a label-vs-
    extent mismatch can only be the VLM read's fault (page-01's ditto
    item read as '1 a'), and text errors are the reviewer's to fix.
    The glyph gate's box-error purpose is meaningless for ink-truth
    boxes; the pieces-based paths keep it."""
    from PIL import Image as PILImage

    from tools.eval_batch import _gate_layout

    im = PILImage.new("L", (1000, 100), 255)
    for y in range(25, 56, 2):  # ink in the box (the box is not no_ink)
        for x in range(110, 290):
            im.putpixel((x, y), 60)
    boxes = [[100.0, 20.0, 300.0, 60.0]]  # a 200x40 box with a short label
    labels = ["1 a"]  # the under-read: 2 glyphs in a 200px axis
    out, counts, bad = _gate_layout(boxes, labels, [], im)
    assert bad, counts  # the glyph gate flags the mismatch...
    out, counts, bad = _gate_layout(boxes, labels, [], im, glyph_check=False)
    assert not bad, counts  # ...but the ink-truth path skips it


def test_drop_unreadable_boxes_keeps_only_labeled() -> None:
    """The ink-layout's edge artifacts (2026-08-28): the scan's
    right-edge marks (x 2005+) and stray left-edge specks pass has_ink
    but the VLM reads NOTHING — they are not text. The empty-labeled
    boxes drop after the fills; their ink stays unboxed and visible,
    the page's honest boxes serve."""
    from tools.eval_batch import _drop_unreadable

    boxes = [[10.0, 10.0, 100.0, 50.0], [200.0, 10.0, 300.0, 50.0]]
    labels = ["real line", ""]
    kept_boxes, kept_labels = _drop_unreadable(boxes, labels)
    assert kept_boxes == [boxes[0]] and kept_labels == ["real line"], (kept_boxes, kept_labels)
    # None labels drop too (the failed reads)
    kept_boxes, kept_labels = _drop_unreadable(boxes, ["real line", None])
    assert kept_boxes == [boxes[0]], kept_boxes
