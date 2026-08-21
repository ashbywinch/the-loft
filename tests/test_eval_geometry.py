"""The geometry experiment's harness test (2026-08-20): the synthetic
fixture's truth is known BY CONSTRUCTION, so the candidate accuracy is
measured exactly. This pins the harness (the metrics + the candidate
builders) and the quantified evidence that motivated it: the baseline's
misplaced transcription boxes anchor nothing (IoU 0.44), while the
rec-only candidate's ink-grounded boxes anchor everything (IoU 1.00).

No model calls — the synthetic fixture runs the pure layout build; the
real-model candidates (the clip-location) extend the same harness.
"""

from __future__ import annotations

import pytest

from tools.eval_geometry import measure, synthetic_letter

pytestmark = pytest.mark.eval


def test_the_harness_measures_the_baselines_misplaced_boxes() -> None:
    """The baseline (the transcription's own boxes) carries the injected
    failing: the margin lines' boxes sit 200px above the truth, so their
    anchors contribute no IoU — 0.44 overall. The metric quantifies the
    page-03/01 class the pure gates cannot see."""
    fixture = synthetic_letter()
    layout = fixture.baseline()
    metrics = measure(layout, fixture)
    assert metrics.coverage == 1.0  # every truth line is present
    assert metrics.orientation_accuracy == 1.0
    assert metrics.anchor_iou < 0.5, f"the misplaced boxes must drag the IoU down: {metrics.anchor_iou}"


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
    from tools.eval_geometry import synthetic_postcard

    fixture = synthetic_postcard()
    baseline = measure(fixture.baseline(), fixture)
    multi = measure(fixture.multi(), fixture)
    assert baseline.orientation_accuracy < 1.0, "the single path cannot resolve the multi orientations"
    assert multi.anchor_iou == 1.0 and multi.orientation_accuracy == 1.0


def test_the_detectors_fire_on_the_injected_failings() -> None:
    """The detection axis: the injected duplicate-region and loose-box
    failings are SEEN — the gates fire and the layout refuses (the
    fail-loud behavior, never silent bad data)."""
    from tools.eval_geometry import duplicate_region_fixture, loose_box_fixture
    from tools.gates import validate_layout

    for fixture in (duplicate_region_fixture(), loose_box_fixture()):
        findings = validate_layout(fixture.baseline())
        assert findings, f"{fixture.name}: the injected failing must be detected"
