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
    column gaps split)."""
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
    return [part for row in rows for part in _split_by_x_gap(row, x_split)]


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
