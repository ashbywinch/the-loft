"""The box geometry primitives — a line box is ``[x0, y0, x1, y1]`` in the
image's pixels (the JSON contract), and these functions are the pure math
over that shape: the area, the region overlap, the reading-axis extent,
and the aspect-consistency rule the orientation gates share.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# The float tolerance for division-underflow protection: a zero-area box
# must not divide by zero.
_AREA_EPSILON = 1e-9


def area(box: list[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def overlap(a: list[float], b: list[float]) -> float:
    """The intersection over the SMALLER box — a tall strip inside a wide
    box still claims the same region. (2026-08-20: the zero-division
    guard was once ``min(area_a, area_b, eps)`` — the epsilon is the
    minimum of the three, so every overlap divided by 1e-9 and any 1px
    intersection read as ~1e12; the dedupe, the anchor arbitration and
    the gates all consumed the inflated value.)"""
    x = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    y = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return (x * y) / max(min(area(a), area(b)), _AREA_EPSILON)


def reading_axis(box: list[float], orientation: float | None) -> float:
    """The box extent along the text's reading direction: the width for
    horizontal text (axis near 0/180), the height for vertical (axis near
    90/270) — the length the recognized text must fit."""
    axis = (orientation or 0) % 180
    return box[2] - box[0] if (axis <= 45 or axis >= 135) else box[3] - box[1]


def aspect_consistent(orientation: float, box: list[float] | None) -> bool:
    """Is the orientation consistent with the box's aspect — Gate A's rule,
    shared by the orientation resolution (a line's orientation must come
    from geometry-validated data, 2026-08-20): a clearly-wide box is
    horizontal text, a clearly-tall box is vertical. Near-square boxes
    and diagonal angles (45°) are always consistent (lenient — a diagonal
    line is genuinely diagonal). A ``None`` box (no geometry) is always
    consistent."""
    if not box:
        return True
    box_w = box[2] - box[0]
    box_h = box[3] - box[1]
    if box_w <= 2 * box_h and box_h <= 2 * box_w:
        return True  # near-square — no aspect constraint
    axis = orientation % 180
    vertical = 60 <= axis <= 120
    horizontal = axis <= 30 or axis >= 150
    if box_w > 2 * box_h:
        return not vertical  # clearly wide: horizontal text only
    return not horizontal  # clearly tall: vertical text only


def orientation_from_aspect(box: list[float] | None) -> int:
    """The reading direction the box's shape implies — aspect_consistent's
    inverse, used when labelling ink-measured rows (the batch runner,
    2026-08-25): a clearly-tall union is vertical text (90°), everything
    else defaults horizontal. Near-square boxes are lenient under Gate A,
    so the horizontal default is always safe there. Hardcoding 0 for
    every row refused seven photo pages ('orientation 0.0° inconsistent
    with a 65x396 box')."""
    if not box:
        return 0
    box_w = box[2] - box[0]
    box_h = box[3] - box[1]
    return 90 if box_h > box_w * 1.5 else 0


# A line clip must carry >= 0.1% dark pixels — a blank clip has nothing
# to recognize (the clip guard) and a box whose region is blank is an
# estimate, not an anchor (Gate D).
INK_MIN = 0.001


def has_ink(box: Sequence[float], image: Any) -> bool:
    """Does the box's region contain ink relative to its OWN paper
    level? (Gate D, 2026-08-20: page-01's transcription boxes sat
    ~770px above the real text — a well-proportioned box in a blank
    region is an estimate, not an anchor. 2026-08-26: the fixed <128
    cutoff was tuned for pen on white and called every pencil note on
    cream photo-card blank; the threshold is now the crop's median
    level minus 35, so faint-but-darker-than-paper marks count and
    blank paper never does.)"""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = image.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return False
    gray = image.crop((x0, y0, x1, y1)).convert("L")
    hist = gray.histogram()
    total = gray.width * gray.height
    median = total / 2
    level = 0
    acc = 0
    for value in range(256):
        acc += hist[value]
        if acc >= median:
            level = value
            break
    ink_level = max(1, level - 35)
    return sum(hist[:ink_level]) >= INK_MIN * total


def text_line_count(box: Sequence[float], image: Any, *, min_band_rows: int = 3, min_gap_rows: int = 3) -> int:
    """How many separated ink bands the box's region holds — the cheap
    multi-line gate (2026-08-25): the vision audit caught stale boxes
    enclosing 3-4 handwriting lines apiece. The crop's row-projection
    (PIL getprojection — no numpy, no model) counts bands; runs merged
    across gaps shorter than ``min_gap_rows`` are one band, and only
    bands of at least ``min_band_rows`` rows count (noise filter). The
    crop is normalized to 100 rows first, so the thresholds are
    scale-invariant."""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = image.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return 0
    gray = image.crop((x0, y0, x1, y1)).convert("L")
    norm = gray.resize((max(1, round(gray.width * 100 / max(1, gray.height))), 100))
    ink = norm.point(lambda p: 255 - p)  # ink becomes nonzero for getprojection
    rows = ink.getprojection()[1]
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, r in enumerate(rows):
        if r and start is None:
            start = i
        elif not r and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(rows) - 1))
    merged: list[tuple[int, int]] = []
    _merge_gap_runs(merged, min_gap_rows, runs)
    return sum(1 for s, e in merged if e - s + 1 >= min_band_rows)


def _merge_gap_runs(merged, min_gap_rows, runs):
    for s, e in runs:
        if merged and s - merged[-1][1] - 1 < min_gap_rows:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
