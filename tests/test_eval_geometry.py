"""The geometry experiment's harness test (2026-08-20): the synthetic
fixture's truth is known BY CONSTRUCTION, so the candidate accuracy is
measured exactly. The 2026-08-22 arbitration (the Anchor choosing the
rec's ink-grounded match over the misplaced marker boxes) PREVENTED the
injected failings — the tests now pin the fix (the baseline anchors at
IoU 1.00) and the detection backstop (the gates fire when a failing
reaches the layout).

No model calls — the synthetic fixture runs the pure layout build; the
real-model candidates (the clip-location) extend the same harness.
"""

from __future__ import annotations

import pytest

from tools.eval_geometry import measure, synthetic_letter, synthetic_postcard
from tools.gates import validate_layout
from tools.text import normalize

pytestmark = pytest.mark.eval


def test_the_arbitration_anchors_the_misplaced_marker_fixture() -> None:
    """The single path's Anchor arbitration (2026-08-22) chooses the rec's
    ink-grounded content match over the misplaced marker boxes — the
    injected failing (page-01/03's marker geometry ~200-770px off) is
    PREVENTED, not patched: the baseline anchors at IoU 1.00."""
    fixture = synthetic_letter()
    metrics = measure(fixture.baseline(), fixture)
    assert metrics.coverage == 1.0
    assert metrics.anchor_iou == 1.0, f"the arbitration must choose the ink-grounded boxes: {metrics.anchor_iou}"


def test_the_rec_only_candidate_anchors_the_truth() -> None:
    """The candidate (the rec association's ink-grounded boxes) anchors
    every line at its true box — IoU 1.00 — the quantified case for the
    enhancement."""
    fixture = synthetic_letter()
    metrics = measure(fixture.rec_only(), fixture)
    assert metrics.anchor_iou == 1.0
    assert metrics.coverage == 1.0


def test_the_multi_path_resolves_the_postcard_fixture() -> None:
    """The synthetic postcard (the genuinely-multi case): the baseline
    single path anchors the boxes but loses the 90° message's
    orientations (0.57); the multi path with the located report resolves
    everything (IoU 1.00, orientation 1.00). The quantified case for the
    multi path."""
    fixture = synthetic_postcard()
    baseline = measure(fixture.baseline(), fixture)
    multi = measure(fixture.multi(), fixture)
    assert baseline.orientation_accuracy < 1.0, "the single path cannot resolve the multi orientations"
    assert multi.anchor_iou == 1.0 and multi.orientation_accuracy == 1.0


def test_the_gates_catch_the_failings_when_they_reach_the_layout() -> None:
    """The detection axis (2026-08-22): the duplicate-region and
    loose-box failings, WHEN PRESENT in a layout, are seen — the gates
    fire and the layout refuses (fail-loud, never silent bad data). The
    arbitration prevents them at the source; the gates are the backstop."""
    duplicate = {
        "width": 1000,
        "height": 1500,
        "lines": [
            {"text": "We are from", "box": [150, 200, 220, 700], "orientation": 90},
            {"text": "beauford & Mrs", "box": [150, 200, 220, 700], "orientation": 90},  # the same box
        ],
    }
    assert any("same region" in v for v in validate_layout(duplicate))
    loose = {
        "width": 1000,
        "height": 1500,
        "lines": [{"text": "POSTAGE", "box": [820, 200, 1500, 213], "orientation": 0}],  # 97 px/char
    }
    assert validate_layout(loose)


def test_the_crop_grid_candidate_anchors_the_truth() -> None:
    """The crop-grid candidate (2026-08-22): the page read as a grid of
    overlapping crops, each crop's lines measured in the crop's own
    frame, stitched into the page. The fixture's truth is known BY
    CONSTRUCTION; the model-perfect local boxes must anchor at IoU 1.00
    with full coverage — the quantified case for the geometry rework."""
    fixture = synthetic_letter()
    metrics = measure(fixture.crop_grid(), fixture)
    assert metrics.anchor_iou == 1.0, f"the stitched crop boxes must be the truth: {metrics.anchor_iou}"
    assert metrics.coverage == 1.0


def test_the_crop_grid_dedupes_the_boundary_lines() -> None:
    """The overlapping crops read the boundary lines TWICE — the stitched
    layout must carry each line once (the cross-crop duplicates drop)."""
    fixture = synthetic_letter()
    layout = fixture.crop_grid()
    texts = [normalize(ln["text"]) for ln in layout["lines"]]
    assert len(texts) == len(set(texts)), "every truth line appears exactly once"
    assert len(layout["lines"]) == len(fixture.truth)
