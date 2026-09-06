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


def split_by_column_gaps(box: list[float], image: Any, min_gap_fraction: float = 0.12) -> list[list[float]]:
    """A wide row divided at its COLUMN gaps (2026-08-26, the form-
    header class): the birth cert's column headers merged into one
    rec row — "Name, if any" in a 2927px box, "Sex" in 1988px. Cell
    gaps are far wider than word gaps; splitting at empty column runs
    longer than ``min_gap_fraction`` of the crop width gives each cell
    its own box. Word gaps inside a cell stay below the threshold. The
    crop is normalized to 1000 columns, so the fraction is
    scale-invariant."""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = image.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return [list(box)]
    gray = image.crop((x0, y0, x1, y1)).convert("L")
    norm = gray.resize((1000, max(1, round(gray.height * 1000 / max(1, gray.width)))))
    scale_x = gray.width / norm.width
    ink = norm.point(lambda p: 255 - p)
    cols = ink.getprojection()[0]
    min_gap = int(min_gap_fraction * len(cols))
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, c in enumerate(cols):
        if c and start is None:
            start = i
        elif not c and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(cols) - 1))
    parts: list[list[float]] = []
    if not runs:
        return [list(box)]
    cur_s, cur_e = runs[0]
    for s, e in runs[1:]:
        if s - cur_e - 1 >= min_gap:
            parts.append([x0 + cur_s * scale_x, float(y0), x0 + cur_e * scale_x, float(y1)])
            cur_s, cur_e = s, e
        else:
            cur_e = e  # a word gap — the run joins the current cell
    parts.append([x0 + cur_s * scale_x, float(y0), x0 + cur_e * scale_x, float(y1)])
    return parts


def split_row_at_piece_gaps(pieces: list[list[float]], x_gap: float | None = None) -> list[list[list[float]]]:
    """A row's pieces divided at their measured x-gaps (2026-08-26,
    the form-header fix): ink-column projections fail on header rows
    because a full-width printed rule touches every column — the rec's
    PIECES are the structure, each cell a detection. Groups split at
    gaps wider than 1.5x the median piece width, the same
    scale-invariant rule as cluster_rows' x-split."""
    if not pieces:
        return []
    widths = [b[2] - b[0] for b in pieces]
    gap = x_gap if x_gap is not None else _median(widths, 200.0) * 1.5
    ordered = sorted(pieces, key=lambda b: b[0])
    groups: list[list[list[float]]] = [[ordered[0]]]
    for b in ordered[1:]:
        if b[0] - groups[-1][-1][2] > gap:
            groups.append([b])
        else:
            groups[-1].append(b)
    return groups


def merge_near_duplicate_rows(
    rows: list[list[list[float]]], y_overlap: float = 0.3, x_overlap: float = 0.9
) -> list[list[list[float]]]:
    """The double-read merge (2026-08-26): the coverage gate quantified
    33 overlapping box pairs on one page at IoU 0.3-0.5 — wide boxes
    whose y-bands overlap heavily = the SAME line detected twice with
    a y jitter (the LONDON BOROUGH class from the first diagnosis).
    Rows whose x-spans overlap ``x_overlap`` of the narrower AND whose
    y-intervals overlap ``y_overlap`` of the shorter are one physical
    line; their pieces merge. Different columns at the same y are
    untouched."""
    merged: list[list[list[float]]] = []
    for row in rows:
        rx0 = min(b[0] for b in row)
        rx1 = max(b[2] for b in row)
        ry0 = min(b[1] for b in row)
        ry1 = max(b[3] for b in row)
        joined = False
        for existing in merged:
            ex0 = min(b[0] for b in existing)
            ex1 = max(b[2] for b in existing)
            ey0 = min(b[1] for b in existing)
            ey1 = max(b[3] for b in existing)
            x_ov = min(rx1, ex1) - max(rx0, ex0)
            y_ov = min(ry1, ey1) - max(ry0, ey0)
            if x_ov >= x_overlap * min(rx1 - rx0, ex1 - ex0) and y_ov >= y_overlap * min(ry1 - ry0, ey1 - ey0):
                existing.extend(row)
                joined = True
                break
        if not joined:
            merged.append(list(row))
    return merged


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
    treated = merge_near_duplicate_rows(rows)
    treated = [sub for row in treated for sub in _split_tall_row(row)]
    return [part for row in treated for part in _split_by_x_gap(row, x_split)]


def coverage_violations(
    boxes: list[list[float]], pieces: list[list[float]], noise_ratio: float = 2.0
) -> tuple[list[list[float]], int]:
    """The box-coverage gate (2026-08-26): every rec detection piece
    must be covered by EXACTLY ONE final box — the user's reframe:
    wrong text is fixable in review, an uncovered text region or a
    double claim is not (the surface has no box-fixing interaction).
    A piece is covered when its center lies inside a box. Uncovered
    pieces are missed text ONLY when they are significant — bigger
    than ``noise_ratio`` x the median piece area (the rec over-
    detects small specks; a large unboxed region is real text the
    pipeline dropped). Returns the significant uncovered pieces and
    the count of double-claimed pieces."""
    areas = [(b[2] - b[0]) * (b[3] - b[1]) for b in pieces]
    median = sorted(areas)[len(areas) // 2] if areas else 0.0

    def covered(p: list[float]) -> int:
        cx = (p[0] + p[2]) / 2
        cy = (p[1] + p[3]) / 2
        return sum(1 for b in boxes if b[0] < cx < b[2] and b[1] < cy < b[3])

    uncovered: list[list[float]] = []
    double = 0
    for p in pieces:
        n = covered(p)
        if n == 0:
            area = (p[2] - p[0]) * (p[3] - p[1])
            if median <= 0 or area > noise_ratio * median:
                uncovered.append(p)
        elif n > 1:
            double += 1
    return uncovered, double


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
