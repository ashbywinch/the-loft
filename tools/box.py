"""The box geometry primitives — a line box is ``[x0, y0, x1, y1]`` in the
image's pixels (the JSON contract), and these functions are the pure math
over that shape: the area, the region overlap, the reading-axis extent,
and the aspect-consistency rule the orientation gates share.
"""

from __future__ import annotations

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


# A line clip must carry >= 0.1% dark pixels — a blank clip has nothing
# to recognize (the clip guard) and a box whose region is blank is an
# estimate, not an anchor (Gate D).
INK_MIN = 0.001


def has_ink(box: list[float], image: Any) -> bool:
    """Does the box's region contain the ink it claims? (Gate D,
    2026-08-20: page-01's transcription boxes sat ~770px above the real
    text — a well-proportioned box in a blank region is an estimate, not
    an anchor.)"""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = image.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return False
    gray = image.crop((x0, y0, x1, y1)).convert("L")
    return sum(gray.histogram()[:128]) >= INK_MIN * gray.width * gray.height
