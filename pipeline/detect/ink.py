"""The ink-measurement machinery: the rec's detection pieces are REAL
ink — its recognition is garbage, its boxes are measurements. The
postcard's message boxes came out right by clustering the pieces into
rows and unioning each row. This module makes that reusable (the
letter's P.S. block, the whole letter, any region): the cluster, the
union, and the label matching. The labels come from the transcription's
lines in ORDER — the proportional assignment — because the model's own
boxes are schematic and cannot be trusted as positions.
"""

from __future__ import annotations

from typing import Any

from document.rectangle import Rectangle
from pipeline.detect.model_band import ModelBand
from pipeline.detect.piece_row import PieceRow
from pipeline.detect.projection_scale import ProjectionScale
from pipeline.detect.row_band import RowBand


def _median(values: list[float], fallback: float) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else fallback


def _split_by_x_gap(row: PieceRow, gap: float = 300.0) -> list[PieceRow]:
    """Split one row at its x-gaps wider than ``gap`` - the rec's y-band
    clustering can merge pieces that are side by side (the postcard's
    date and the HERNSPETH sharing a band; a line whose words sit at
    the two ends with a blank middle). Each side becomes its own row -
    the union-boxes tighten to the ink, and the text-extent gates stop
    false-positives."""
    ordered = sorted(row.pieces, key=lambda piece: piece.x0)
    parts: list[PieceRow] = []
    current = [ordered[0]]
    for piece in ordered[1:]:
        if piece.x0 - current[-1].x1 > gap:
            parts.append(PieceRow(current))
            current = [piece]
        else:
            current.append(piece)
    parts.append(PieceRow(current))
    return parts


ROW_HEIGHT_FACTOR = 2.5


def _split_tall_row(row: PieceRow, factor: float = ROW_HEIGHT_FACTOR) -> list[PieceRow]:
    """Split an implausibly tall row at its internal y-gaps until every
    part could be ONE line: single-linkage chaining merges pieces whose
    every ADJACENT gap is small into rows spanning many real lines — the
    birth certificate's form table chained 40 cells into one 290px row
    (6.2x its own piece scale), a photo's big
    handwriting 13 pieces into 1077px (6.3x). A line's extent stays
    within ~2.5x its own pieces' median height (ascenders, descenders,
    slant); past that the row splits at its widest center-gap,
    recursively. All thresholds are the row's OWN scale — invariant to
    scan resolution."""
    cap = factor * _median([piece.height for piece in row.pieces], 50.0)
    out: list[PieceRow] = []
    stack = [PieceRow(sorted(row.pieces, key=lambda piece: piece.cy))]
    while stack:
        part = stack.pop()
        if len(part.pieces) < 2 or part.union().height <= cap:
            out.append(part)
            continue
        best_i, best_gap = 1, -1.0
        for i in range(1, len(part.pieces)):
            gap = part.pieces[i].cy - part.pieces[i - 1].cy
            if gap > best_gap:
                best_i, best_gap = i, gap
        if best_gap <= 0:  # coincident centers: nothing to split on
            out.append(part)
            continue
        stack += [PieceRow(part.pieces[:best_i]), PieceRow(part.pieces[best_i:])]
    return out


def _band_parts(bands: list[RowBand], ink: Any, box: Rectangle, scale: ProjectionScale) -> list[Rectangle]:
    """Each band's inked x-extent as a page-space box (extracted from
    split_by_bands 2026-08-29 for the complexity bar)."""
    cols = ink.getprojection()[0]
    parts: list[Rectangle] = []
    for band in bands:
        xs = [i for i, c in enumerate(cols) if c]
        if not xs:
            continue
        pad = 2
        parts.append(
            Rectangle(
                scale.page_x(box.x0, min(xs) - pad),
                scale.page_y(box.y0, band.top),
                min(scale.page_x(box.x0, max(xs) + 1 + pad), box.x1),
                min(scale.page_y(box.y0, band.bottom + 1), box.y1),
            )
        )
    return parts


def _merge_gap_runs(runs: list[RowBand], gap: int) -> list[RowBand]:
    """Merge projection runs separated by less than ``gap`` rows - a thin
    descender touch must not split a line band (extracted from
    split_by_bands 2026-08-29 for the complexity bar)."""
    merged: list[RowBand] = []
    for run in runs:
        if merged and run.top - merged[-1].bottom - 1 < gap:
            merged[-1] = merged[-1].extend_to(run.bottom)
        else:
            merged.append(run)
    return merged


def split_by_bands(box: Rectangle, image: Any) -> list[Rectangle]:
    """A multi-line union divided along its own ink bands: when the
    projection shows several separated writing bands, their row ranges —
    and each band's inked x-extent — ARE the true line boxes. Splitting
    before label matching turns too-few-rows into accurate-rows (the
    birth certificates' 40-vs-25 mismatch) instead
    of refusing the page. Fewer than two bands: the box comes back
    unchanged — single-line and blank boxes are not this function's
    business."""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = image.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return [box]
    gray = image.crop((x0, y0, x1, y1)).convert("L")
    norm_h = 100
    norm = gray.resize((max(1, round(gray.width * norm_h / max(1, gray.height))), norm_h))
    scale = ProjectionScale(gray.width / norm.width, gray.height / norm_h)
    ink = norm.point(lambda p: 255 - p)
    rows = ink.getprojection()[1]
    runs: list[RowBand] = []
    start: int | None = None
    for i, r in enumerate(rows):
        if r and start is None:
            start = i
        elif not r and start is not None:
            runs.append(RowBand(start, i - 1))
            start = None
    if start is not None:
        runs.append(RowBand(start, len(rows) - 1))
    merged = _merge_gap_runs(runs, 3)
    bands = [band for band in merged if band.length >= 3]
    if len(bands) < 2:
        return [box]
    parts = _band_parts(bands, ink, box, scale)
    return parts or [box]


def cluster_rows(boxes: list[Rectangle], gap: float | None = None, x_gap: float | None = None) -> list[PieceRow]:
    """The rec's pieces clustered by y-proximity into ROWS — one text
    line's pieces share the y-band — then each row split at its wide
    x-gaps (side-by-side pieces are separate lines, or a line's words
    at the two ends — the union must not span the blank middle).

    The thresholds default to fractions of the MEASURED piece sizes
    (absolute pixel values tuned on one batch's scan resolution fail at
    any other scale — a half-scale scan merges every row, a double-scale
    split splits every line). y-gap defaults to 0.65× the median piece
    height (between within-line jitter and the next line's top);
    x-gap defaults to 1.5× the median piece width (word gaps stay,
    column gaps split). Rows that chained implausibly tall split
    before the x-split (the form-table case needs y-separation before
    any column gap exists)."""
    if not boxes:
        return []
    heights = [box.height for box in boxes]
    widths = [box.width for box in boxes]
    y_gap = gap if gap is not None else _median(heights, 50.0) * 0.65
    x_split = x_gap if x_gap is not None else _median(widths, 200.0) * 1.5
    ordered = sorted(boxes, key=lambda box: box.cy)
    grouped: list[list[Rectangle]] = []
    for box in ordered:
        if grouped and box.cy - grouped[-1][-1].cy < y_gap:
            grouped[-1].append(box)
        else:
            grouped.append([box])
    rows = [PieceRow(group) for group in grouped]
    treated = [part for row in rows for part in _split_tall_row(row)]
    return [part for row in treated for part in _split_by_x_gap(row, x_split)]


def transcription_line_count_plausible(line_count: int, row_count: int) -> bool:
    """Did the model's transcription plausibly cover the rows the rec
    measured? The collapse detector: a read that folds many measured
    rows into one long line makes every row carry the same blob and Gate
    B refuses the page. A page needs
    rec over-splits; the model merges some). Conservative: pages with
    fewer than 10 measured rows are photo-caption territory where the
    rec's row count is unreliable — any count is accepted."""
    if row_count < 10:
        return True
    return line_count * 5 >= row_count * 2


def match_labels(
    row_unions: list[Rectangle],
    transcription_lines: list[str],
    model_bands: list[ModelBand] | None = None,
) -> list[str]:
    """The rows' labels — the transcription's lines, in order. The
    PROPORTIONAL assignment: each row's y-center, as a fraction of the
    content's y-span, picks the line at the same fraction — no model
    boxes involved (the y-overlap matching collapses when the model's
    full-page boxes are schematic — every row matches the first band).
    When the model's bands are given AND their y-overlap
    assigns distinct bands to at least 60% of the rows (the model's
    boxes trustworthy — the rotated panel), the overlap labels refine
    the assignment; a degenerate overlap falls back to the
    proportional."""
    if not row_unions:
        return []
    centers = [row.cy for row in row_unions]
    top = min(row.y0 for row in row_unions)
    span = max(max(row.y1 for row in row_unions) - top, 1)
    n = len(transcription_lines)
    proportional = [transcription_lines[min(n - 1, max(0, round(((c - top) / span) * (n - 1))))] for c in centers]
    if not model_bands or not transcription_lines:
        return proportional
    overlap_idx = _overlap_assignments(row_unions, model_bands)
    assigned = [i for i in overlap_idx if i >= 0]
    if assigned and len(set(assigned)) / len(overlap_idx) < 0.6:
        return proportional  # the model's boxes are schematic — fall back
    return [transcription_lines[i] if i >= 0 else "" for i in overlap_idx]


def _overlap_assignments(row_unions: list[Rectangle], model_bands: list[ModelBand]) -> list[int]:
    """Each row's best y-overlapping band's index — the model's boxes
    as positions, refined by the measured rows' extents."""
    overlap_idx: list[int] = []
    for row in row_unions:
        best_i, best_ov = -1, 0.0
        for i, band in enumerate(model_bands):
            overlap = band.overlap(row)
            if overlap > best_ov:
                best_i, best_ov = i, overlap
        overlap_idx.append(best_i)
    return overlap_idx
