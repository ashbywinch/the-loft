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


def cluster_rows(boxes: list[list[float]], gap: float = 50.0) -> list[list[list[float]]]:
    """The rec's pieces clustered by y-proximity into ROWS — one text
    line's pieces share the y-band. Returns the rows' piece-lists, top
    to bottom. (2026-08-22: the first attempt clustered by x — the
    wrong axis for the rotated panel's horizontal lines — and merged
    the whole message.)"""
    ordered = sorted(boxes, key=lambda b: (b[1] + b[3]) / 2)
    rows: list[list[list[float]]] = []
    for b in ordered:
        cy = (b[1] + b[3]) / 2
        if rows and cy - (rows[-1][-1][1] + rows[-1][-1][3]) / 2 < gap:
            rows[-1].append(b)
        else:
            rows.append([b])
    return rows


def union(boxes: list[list[float]]) -> list[float]:
    """The boxes' bounding box — the row's measured extent."""
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


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
