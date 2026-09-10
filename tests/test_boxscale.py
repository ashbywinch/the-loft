"""Tests for the page's writing scale (tools/boxscale.py).

Deterministic: synthetic pages whose scale is known by construction, plus the
real letter's properties where the fixture exists in the checkout. No network,
no model, no wall-clock.
"""

from __future__ import annotations

import random

import pytest

from tools.boxscale import (
    LINE_RATIO_BOUNDS,
    LINE_RATIO_DEFAULT,
    line_ratio,
    line_spacing,
    traced_pitch,
    traced_spacings,
    writing_scale,
)


def synthetic_page(
    height: float, spacing: float, lines: int = 20, words_per_line: int = 8, seed: int = 7
) -> tuple[list[float], list[float]]:
    """Heights and baselines of words on evenly spaced lines, with writing jitter."""
    rng = random.Random(seed)
    heights: list[float] = []
    baselines: list[float] = []
    for line in range(lines):
        for _ in range(words_per_line):
            heights.append(height * rng.uniform(0.8, 1.2))
            baselines.append(line * spacing + rng.uniform(-height * 0.3, height * 0.3))
    return heights, baselines


@pytest.mark.parametrize(("height", "spacing"), [(38.0, 60.0), (26.0, 40.0), (55.0, 90.0), (70.0, 110.0)])
def test_writing_scale_is_the_writing_height(height: float, spacing: float) -> None:
    heights, _ = synthetic_page(height, spacing)
    assert writing_scale(heights) == pytest.approx(height, rel=0.1)


@pytest.mark.parametrize(("height", "spacing"), [(38.0, 60.0), (26.0, 40.0), (55.0, 90.0), (70.0, 110.0)])
def test_spacing_follows_the_writing_height_and_the_traced_lines(height: float, spacing: float) -> None:
    """The traced lines measure the ratio; the spacing is then the height × that ratio."""
    heights, baselines = synthetic_page(height, spacing)
    one_per_line = baselines[::8]  # a reviewer traces one line, not every word
    assert line_spacing(heights, one_per_line) == pytest.approx(spacing, rel=0.15)


def test_spacing_falls_back_to_the_typographic_default_without_traces() -> None:
    heights, _ = synthetic_page(38.0, 60.0)
    assert line_spacing(heights) == pytest.approx(38.0 * LINE_RATIO_DEFAULT, rel=0.1)


def test_traced_pitch_needs_enough_traces() -> None:
    assert traced_pitch([100.0, 160.0]) is None
    assert traced_pitch([100.0, 160.0, 220.0]) == pytest.approx(60.0)


def test_traced_spacings_ignore_impossible_pairs() -> None:
    """Two traces 5px apart (one line, drawn twice) or 400px apart (a skipped line)
    are not a line spacing."""
    assert traced_spacings([100.0, 105.0, 165.0, 565.0]) == pytest.approx([60.0])


def test_a_measured_ratio_outside_the_plausible_band_is_rejected() -> None:
    """A trace measuring 0.3 × the writing height is two traces on one line, not a page scale."""
    assert line_ratio(0.3 * 40.0, 40.0) == LINE_RATIO_DEFAULT
    assert line_ratio(4.0 * 40.0, 40.0) == LINE_RATIO_DEFAULT
    measured = 1.5 * 40.0
    assert line_ratio(measured, 40.0) == pytest.approx(1.5)
    assert LINE_RATIO_BOUNDS[0] <= 1.5 <= LINE_RATIO_BOUNDS[1]
