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
