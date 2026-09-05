"""The ink-measurement machinery (2026-08-22): the rec's detection
pieces are REAL ink — its recognition is garbage, its boxes are
measurements. The postcard's message boxes came out right by clustering
the pieces into rows and unioning each row. This module makes that
reusable (the letter's P.S. block, the whole letter, any region): the
cluster, the union, and the label matching. The labels come from the
transcription's lines in ORDER — the proportional assignment — because
the model's own boxes are schematic and cannot be trusted as positions.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def _median(values: list[float], fallback: float) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else fallback


def _split_by_x_gap(row: list[list[float]], gap: float = 300.0) -> list[list[list[float]]]:
    """Split one row at its x-gaps wider than ``gap`` - the rec's y-band
    clustering can merge pieces that are side by side (the postcard's
    date and the HERNSPETH sharing a band; a line whose words sit at
    the two ends with a blank middle). Each side becomes its own row -
    the union-boxes tighten to the ink, and the text-extent gates stop
    false-positives (2026-08-22)."""
    ordered = sorted(row, key=lambda b: b[0])
    parts: list[list[list[float]]] = []
    current = [ordered[0]]
    for b in ordered[1:]:
        if b[0] - current[-1][2] > gap:
            parts.append(current)
            current = [b]
        else:
            current.append(b)
    parts.append(current)
    return parts


ROW_HEIGHT_FACTOR = 2.5


def _split_tall_row(row: list[list[float]], factor: float = ROW_HEIGHT_FACTOR) -> list[list[list[float]]]:
    """Split an implausibly tall row at its internal y-gaps until every
    part could be ONE line (2026-08-25): single-linkage chaining merges
    pieces whose every ADJACENT gap is small into rows spanning many
    real lines — the birth certificate's form table chained 40 cells
    into one 290px row (6.2x its own piece scale), a photo's big
    handwriting 13 pieces into 1077px (6.3x). A line's extent stays
    within ~2.5x its own pieces' median height (ascenders, descenders,
    slant); past that the row splits at its widest center-gap,
    recursively. All thresholds are the row's OWN scale — invariant to
    scan resolution."""

    def extent(part: list[list[float]]) -> float:
        return max(b[3] for b in part) - min(b[1] for b in part)

    cap = factor * _median([b[3] - b[1] for b in row], 50.0)
    out: list[list[list[float]]] = []
    stack = [sorted(row, key=lambda b: (b[1] + b[3]) / 2)]
    while stack:
        part = stack.pop()
        if len(part) < 2 or extent(part) <= cap:
            out.append(part)
            continue
        best_i, best_gap = 1, -1.0
        for i in range(1, len(part)):
            gap = (part[i][1] + part[i][3]) / 2 - (part[i - 1][1] + part[i - 1][3]) / 2
            if gap > best_gap:
                best_i, best_gap = i, gap
        if best_gap <= 0:  # coincident centers: nothing to split on
            out.append(part)
            continue
        stack += [part[:best_i], part[best_i:]]
    return out


def offset_box(box: list[float], x0: float, y0: float) -> list[float]:
    """A crop-space box in PAGE space — the prep_panel crop's origin
    added back (2026-08-25): detection on a cropped panel measures in
    crop coordinates, and writing them verbatim served page-10 with
    every box shifted up by the stale layout's origin."""
    return [box[0] + x0, box[1] + y0, box[2] + x0, box[3] + y0]


def _band_parts(
    bands: list[tuple[int, int]], ink: Any, box: tuple[int, int, int, int], scales: tuple[float, float]
) -> list[list[float]]:
    """Each band's inked x-extent as a page-space box (extracted from
    split_by_bands 2026-08-29 for the complexity bar)."""
    x0, y0, x1, y1 = box
    scale_x, scale_y = scales
    cols = ink.getprojection()[0]
    parts: list[list[float]] = []
    for s, e in bands:
        xs = [i for i, c in enumerate(cols) if c]
        if not xs:
            continue
        pad = 2
        bx0 = x0 + (min(xs) - pad) * scale_x
        bx1 = x0 + (max(xs) + 1 + pad) * scale_x
        by0 = y0 + s * scale_y
        by1 = y0 + (e + 1) * scale_y
        parts.append([bx0, by0, min(bx1, x1), min(by1, y1)])
    return parts


def _merge_gap_runs(runs: list[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    """Merge projection runs separated by less than ``gap`` rows - a thin
    descender touch must not split a line band (extracted from
    split_by_bands 2026-08-29 for the complexity bar)."""
    merged: list[tuple[int, int]] = []
    for s, e in runs:
        if merged and s - merged[-1][1] - 1 < gap:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def split_by_bands(box: Sequence[float], image: Any) -> list[list[float]]:
    """A multi-line union divided along its own ink bands (2026-08-26):
    when the projection shows several separated writing bands, their
    row ranges — and each band's inked x-extent — ARE the true line
    boxes. Splitting before label matching turns too-few-rows into
    accurate-rows (the birth certificates' 40-vs-25 mismatch) instead
    of refusing the page. Fewer than two bands: the box comes back
    unchanged — single-line and blank boxes are not this function's
    business."""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = image.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return [list(box)]
    gray = image.crop((x0, y0, x1, y1)).convert("L")
    norm_h = 100
    norm = gray.resize((max(1, round(gray.width * norm_h / max(1, gray.height))), norm_h))
    scale_x = gray.width / norm.width
    scale_y = gray.height / norm_h
    ink = norm.point(lambda p: 255 - p)
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
    merged = _merge_gap_runs(runs, 3)
    bands = [(s, e) for s, e in merged if e - s + 1 >= 3]
    if len(bands) < 2:
        return [list(box)]
    parts = _band_parts(bands, ink, (x0, y0, x1, y1), (scale_x, scale_y))
    return parts or [list(box)]


def cluster_rows(
    boxes: list[list[float]], gap: float | None = None, x_gap: float | None = None
) -> list[list[list[float]]]:
    """The rec's pieces clustered by y-proximity into ROWS — one text
    line's pieces share the y-band — then each row split at its wide
    x-gaps (side-by-side pieces are separate lines, or a line's words
    at the two ends — the union must not span the blank middle).

    The thresholds default to fractions of the MEASURED piece sizes
    (2026-08-22: the absolute pixel values were tuned on one batch's
    scan resolution — a half-scale scan merged every row, a double-
    scale split every line). y-gap defaults to 0.65× the median piece
    height (between within-line jitter and the next line's top);
    x-gap defaults to 1.5× the median piece width (word gaps stay,
    column gaps split). Rows that chained implausibly tall split
    before the x-split (the form-table case needs y-separation before
    any column gap exists)."""
    if not boxes:
        return []
    heights = [b[3] - b[1] for b in boxes]
    widths = [b[2] - b[0] for b in boxes]
    y_gap = gap if gap is not None else _median(heights, 50.0) * 0.65
    x_split = x_gap if x_gap is not None else _median(widths, 200.0) * 1.5
    ordered = sorted(boxes, key=lambda b: (b[1] + b[3]) / 2)
    rows: list[list[list[float]]] = []
    for b in ordered:
        cy = (b[1] + b[3]) / 2
        if rows and cy - (rows[-1][-1][1] + rows[-1][-1][3]) / 2 < y_gap:
            rows[-1].append(b)
        else:
            rows.append([b])
    treated = [sub for row in rows for sub in _split_tall_row(row)]
    return [part for row in treated for part in _split_by_x_gap(row, x_split)]


def union(boxes: list[list[float]]) -> list[float]:
    """The boxes' bounding box — the row's measured extent."""
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def transcription_line_count_plausible(line_count: int, row_count: int) -> bool:
    """Did the model's transcription plausibly cover the rows the rec
    measured? The collapse detector (2026-08-25): the birth certificate's
    read folded 26 measured rows into one 323-char line — every row then
    carried the same blob and Gate B refused the page. A page needs
    roughly two-fifths of its measured rows as transcription lines (the
    rec over-splits; the model merges some). Conservative: pages with
    fewer than 10 measured rows are photo-caption territory where the
    rec's row count is unreliable — any count is accepted."""
    if row_count < 10:
        return True
    return line_count * 5 >= row_count * 2


def match_labels(
    row_unions: list[list[float]],
    transcription_lines: list[str],
    model_bands: list[tuple[float, float, str]] | None = None,
) -> list[str]:
    """The rows' labels — the transcription's lines, in order. The
    PROPORTIONAL assignment: each row's y-center, as a fraction of the
    content's y-span, picks the line at the same fraction — no model
    boxes involved (2026-08-22: the y-overlap matching collapsed when
    the model's full-page boxes were schematic — every row matched the
    first band). When the model's bands are given AND their y-overlap
    assigns distinct bands to at least 60% of the rows (the model's
    boxes trustworthy — the rotated panel), the overlap labels refine
    the assignment; a degenerate overlap falls back to the
    proportional."""
    if not row_unions:
        return []
    centers = [(u[1] + u[3]) / 2 for u in row_unions]
    top = min(u[1] for u in row_unions)
    span = max(max(u[3] for u in row_unions) - top, 1)
    n = len(transcription_lines)
    proportional = [transcription_lines[min(n - 1, max(0, round(((c - top) / span) * (n - 1))))] for c in centers]
    if not model_bands or not transcription_lines:
        return proportional
    overlap_idx = _overlap_assignments(row_unions, model_bands)
    assigned = [i for i in overlap_idx if i >= 0]
    if assigned and len(set(assigned)) / len(overlap_idx) < 0.6:
        return proportional  # the model's boxes are schematic — fall back
    return [transcription_lines[i] if i >= 0 else "" for i in overlap_idx]


def _overlap_assignments(row_unions: list[list[float]], model_bands: list[tuple[float, float, str]]) -> list[int]:
    """Each row's best y-overlapping band's index — the model's boxes
    as positions, refined by the measured rows' extents."""
    overlap_idx: list[int] = []
    for u in row_unions:
        ry0, ry1 = u[1], u[3]
        best_i, best_ov = -1, 0.0
        for i, (my0, my1, _) in enumerate(model_bands):
            ov = max(0, min(ry1, my1) - max(ry0, my0))
            if ov > best_ov:
                best_i, best_ov = i, ov
        overlap_idx.append(best_i)
    return overlap_idx
