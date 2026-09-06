"""The box geometry primitives — a line box is ``[x0, y0, x1, y1]`` in the
image's pixels (the JSON contract), and these functions are the pure math
over that shape: the area, the region overlap, the reading-axis extent,
and the aspect-consistency rule the orientation gates share.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

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


def _merge_gap_runs(merged: list[tuple[int, int]], min_gap_rows: int, runs: list[tuple[int, int]]) -> None:
    """Merge projection runs separated by less than ``min_gap_rows``
    rows into one band (extracted from text_line_count 2026-08-29 for
    the complexity bar)."""
    for s, e in runs:
        if merged and s - merged[-1][1] - 1 < min_gap_rows:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))


def projection_runs(rows: Sequence[int]) -> list[tuple[int, int]]:
    """Index runs where the projection is nonzero (extracted from the
    fragment gate 2026-08-29 — the band/cols scaffolding is shared by
    fragment_violation and fragment_regions; public because the
    ink-layout's band-finder in eval_batch uses the same runs)."""
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
    return runs


def _claimed_by_sibling(
    edge: float, span: tuple[int, int], siblings: Sequence[Sequence[float]], tolerance: float, box_w: int
) -> bool:
    """Is ``edge`` (an outside-ink column) claimed by a sibling box's
    x-span? Other text WITH ITS OWN BOX is not this line's
    continuation (extracted from the fragment gate 2026-08-29 — the
    closure hoisted for the closures rule)."""
    return any((s[0] - tolerance * box_w <= edge <= s[2] + tolerance * box_w) for s in siblings)


def _dominant_band(box: Sequence[float], image: Any) -> tuple[int, int, int, int, int, int, Any] | None:
    """The box's DOMINANT ink band + its row strip — a tall merged
    box's full-height strip would catch the neighbouring lines' ink
    and flag every box (page-01's 1404x221 rows: fragment=14 false
    positives). None when the box is blank (extracted from the
    fragment gate 2026-08-29)."""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = image.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if y1 <= y0:
        return None
    gray = image.crop((x0, y0, x1, y1)).convert("L")
    norm = gray.resize((max(1, round(gray.width * 100 / max(1, gray.height))), 100))
    runs = projection_runs(norm.point(lambda p: 255 - p).getprojection()[1])
    if not runs:
        return None  # blank — has_ink's business
    band = max(runs, key=lambda r: r[1] - r[0])
    scale_y = gray.height / 100
    band_y0 = y0 + int(band[0] * scale_y)
    band_y1 = y0 + int((band[1] + 1) * scale_y)
    strip = image.crop((0, band_y0, w, band_y1)).convert("L")
    return x0, y0, x1, y1, band_y0, band_y1, strip


def fragment_violation(
    box: Sequence[float], image: Any, siblings: Sequence[Sequence[float]] = (), tolerance: float = 0.4
) -> bool:
    """Is the box a FRAGMENT — covering part of a line whose ink
    continues outside it AND is not claimed by another box? (2026-08-26:
    071639 served a box over part of a caption while the rest sat
    outside — ink present, single band, plausible label, WRONG box.
    Fixed again for multi-region pages: the margin notes at the same y
    flagged every body row until the outside ink was checked against
    the SIBLING boxes — other text WITH ITS OWN BOX is not this line's
    continuation.) Outside ink in no box beyond the box's x-edges by
    more than ``tolerance`` x the box width = fragment. Blank strips
    are not fragments (has_ink's business)."""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = image.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    box_w = max(1, x1 - x0)
    if y1 <= y0:
        return True
    band = _dominant_band(box, image)
    if band is None:
        return False  # blank
    x0, y0, x1, y1, _band_y0, _band_y1, strip = band
    norm = strip.resize((max(1, round(strip.width * 100 / max(1, strip.height))), 100))
    # per-column DARK-row counts — the gate's ink is the raw darkness
    # (the text is genuinely dark; the paper is 250+). The 255-p sum
    # counted the paper's light pixels as ink; PIL's getprojection is
    # boolean. (2026-08-28: the ink-layout's boxes must cover the raw
    # ink's extent — the faint marks the adaptive threshold excluded
    # are still text, and the gate measures them honestly.)
    arr = np.asarray(norm)
    col_counts = (arr < 200).sum(axis=0)
    scale = strip.width / len(col_counts)
    # a column counts as inked only when TEXT-SIZED dark ink sits
    # there — the 100-row normalization + the page-wide specks (1-3px
    # marks) flagged 23 of 32 honest ink-layout boxes on page-01; a
    # 2px speck (2-10 rows) is not a line continuation. The
    # handwriting's stroke columns carry 50-100 of the band's rows.
    min_ink = max(3, 100 // 4)
    inked = [i for i, c in enumerate(col_counts) if c >= min_ink]
    if not inked:
        return False  # blank

    left_out = max(0, x0 - min(inked) * scale)
    right_out = max(0, (max(inked) + 1) * scale - x1)
    if left_out > tolerance * box_w and _claimed_by_sibling(min(inked) * scale, (x0, x1), siblings, tolerance, box_w):
        left_out = 0
    if right_out > tolerance * box_w and _claimed_by_sibling(
        (max(inked) + 1) * scale, (x0, x1), siblings, tolerance, box_w
    ):
        right_out = 0
    return left_out > tolerance * box_w or right_out > tolerance * box_w


def fragment_regions(
    box: Sequence[float], image: Any, siblings: Sequence[Sequence[float]] = (), tolerance: float = 0.4
) -> list[list[float]]:
    """The MISSED AREAS at the box's band — the outside ink NOT claimed
    by any sibling box (2026-08-26, the recall seam: page-01's margin
    notes the rec never detected sit at the body rows' bands; the
    fragment gate sees them, this returns their rectangles so a
    low-sensitivity detection pass can crop exactly those regions).
    Each region is the unclaimed ink run's x-extent across the box's
    dominant band's rows."""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = image.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    box_w = max(1, x1 - x0)
    if y1 <= y0:
        return []
    band = _dominant_band(box, image)
    if band is None:
        return []
    x0, y0, x1, y1, by0, by1, strip = band
    snorm = strip.resize((max(1, round(strip.width * 100 / max(1, strip.height))), 100))
    cols = snorm.point(lambda p: 255 - p).getprojection()[0]
    scale = strip.width / len(cols)
    inked = [i for i, c in enumerate(cols) if c]
    if not inked:
        return []
    box_w = max(1, x1 - x0)

    def claimed(edge: float) -> bool:
        return any(s[0] - tolerance * box_w <= edge <= s[2] + tolerance * box_w for s in siblings)

    regions: list[list[float]] = []
    left = min(inked) * scale
    right = (max(inked) + 1) * scale
    if x0 - left > tolerance * box_w and not claimed(left):
        regions.append([max(0, left - 8 * scale), float(by0), min(x0, right), float(by1)])
    if right - x1 > tolerance * box_w and not claimed(right):
        regions.append([max(x1, left), float(by0), min(w, right + 8 * scale), float(by1)])
    return regions
