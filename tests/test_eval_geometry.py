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

from tools.eval_geometry import baseline_builder, measure, rec_only_builder, synthetic_letter

pytestmark = pytest.mark.eval


def test_the_harness_measures_the_baselines_misplaced_boxes() -> None:
    """The baseline (the transcription's own boxes) carries the injected
    failing: the margin lines' boxes sit 200px above the truth, so their
    anchors contribute no IoU — 0.44 overall. The metric quantifies the
    page-03/01 class the pure gates cannot see."""
    fixture = synthetic_letter()
    layout = baseline_builder(fixture)
    metrics = measure(layout, fixture)
    assert metrics.coverage == 1.0  # every truth line is present
    assert metrics.orientation_accuracy == 1.0
    assert metrics.anchor_iou < 0.5, f"the misplaced boxes must drag the IoU down: {metrics.anchor_iou}"


def test_the_rec_only_candidate_anchors_the_truth() -> None:
    """The candidate (the rec association's ink-grounded boxes) anchors
    every line at its true box — IoU 1.00 — the quantified case for the
    enhancement."""
    fixture = synthetic_letter()
    metrics = measure(rec_only_builder(fixture), fixture)
    assert metrics.anchor_iou == 1.0
    assert metrics.coverage == 1.0
