"""Batch ink-column runner: every page through the ink-column pipeline.
The VLM panel reads are parallelised across pages (independent HTTP);
the local rec stays sequential (memory-bound).

Runs under .venv-htr (which has PaddleOCR AND the VLM dependencies).

Usage: PYTHONPATH=. .venv-htr/bin/python tools/eval_batch.py <batch_id> ...
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import monotonic
from typing import Any

import numpy as np
from PIL import Image

# The rec engine's imports stay INLINE (in _make_engine/_detect_pieces):
# tools.layout_detect pulls in paddleocr which lives only in .venv-htr;
# a module-top import would make this file unimportable (untestable) in
# the main venv.
from tools.box import (
    fragment_violation,
    has_ink,
    orientation_from_aspect,  # noqa: E402
    projection_runs,
    text_line_count,
)
from tools.gates import glyph_extent_violation, validate_layout
from tools.ink import (
    cluster_rows,
    coverage_violations,
    match_labels,
    offset_box,
    split_by_bands,
    split_row_at_piece_gaps,
    transcription_line_count_plausible,
    union,
)
from tools.layout import load_layout_store, write_layout_store  # noqa: E402
from tools.loft_paths import WORK_DIR  # noqa: E402
from tools.pipeline_store import PipelineStore  # noqa: E402
from tools.text import flag_line_words, selfreport_words_by_line
from tools.vlm import (  # noqa: E402
    parse_transcription_response,
    selfreport_words,
    transcribe_image_vlm,
    transcribe_with_fallbacks,
    transcription_problem,
    transcription_system_with_context,
)
from tools.vlm_cache import (
    load_cached_read,
    load_selfreport,
    store_read,
    store_selfreport,
)  # noqa: E402

# The trial's runner-up (docs/plans/model-trial-report.md §4): same
# family as glm-4.6v, different failure profile — the ladder's last rung.
FALLBACK_MODEL = "z-ai/glm-4.5v"


def layout_is_current(layout: dict[str, Any]) -> bool:
    """Was this layout written by the current ink machinery? The
    clean-skip must only protect layouts today's gates can vouch for:
    page-01/08/11 served stale old-pipeline geometry for days because
    their files validated structurally clean (2026-08-26)."""
    lines = layout.get("lines") or []
    return bool(lines) and all(ln.get("box_source") == "ink" for ln in lines)


def prep_panel(image_path: Path, layout: dict[str, Any] | None, tmp: Path, page: str) -> dict[str, Any] | None:
    """Crop the page's content region; no layout → the full page."""
    if layout is None:
        # one open, one save, the with closes the fp — the unclosed
        # double-open hit a PIL PNG-save race mid-batch ('_idat' has no
        # fileno, 2026-08-28: the full batch crashed at page-09)
        with Image.open(image_path) as im:
            w, h = im.size
            panel_path = tmp / f"{page}.png"
            im.save(panel_path)
        return {"path": str(panel_path), "x0": 0, "y0": 0, "w": w, "h": h}
    boxed = [ln["box"] for ln in layout.get("lines", []) if ln.get("box")]
    unmatched = [u["box"] for u in layout.get("unmatched", []) if u.get("box")]
    all_boxes = boxed + unmatched
    if not all_boxes:
        return None
    xs = [v for b in all_boxes for v in (b[0], b[2])]
    ys = [v for b in all_boxes for v in (b[1], b[3])]
    bx0, by0 = min(xs), min(ys)
    bw, bh = max(xs) - bx0, max(ys) - by0
    if bw <= 0 or bh <= 0:
        return None
    panel_path = tmp / f"{page}.png"
    with Image.open(image_path) as im:
        im.crop((int(bx0), int(by0), int(bx0 + bw), int(by0 + bh))).save(panel_path)
    return {"path": str(panel_path), "x0": bx0, "y0": by0, "w": bw, "h": bh}


_RECALL_ENGINE: Any = None


def _recall_detect(_engine: Any, crop_path: Path) -> list[list[float]]:
    """The recall detector (2026-08-28): a second PaddleOCR instance,
    created lazily — the main engine is freed before Phase 3 (the OOM
    discipline). Runs at the ENGINE's normal threshold: the fix is the
    RESOLUTION (tiles), not the threshold — the 0.86x full-page cap
    under-segments small handwriting, and at tile resolution the
    default threshold already finds it (page-01's margin line-starts:
    28 boxes at 0.3). Boxes come back in crop coordinates; _tile_detect
    offsets them into page space."""
    # lucidlint: ignore global-state the lazy recall engine is the .venv-htr seam — created once, freed before it
    global _RECALL_ENGINE
    if _RECALL_ENGINE is None:
        # lucidlint: ignore inline-import the .venv-htr seam — paddleocr lives only in .venv-htr; the main venv lacks it
        from paddleocr import PaddleOCR  # type: ignore[missing-import]  # paddleocr lives only in .venv-htr

        # lucidlint: ignore inline-import the same seam — ENGINE imports layout_detect, which loads paddleocr
        from tools.layout_detect import ENGINE

        _RECALL_ENGINE = PaddleOCR(**ENGINE)
    # lucidlint: ignore inline-import the .venv-htr seam — paddleocr lives only in .venv-htr; the main venv lacks it
    from tools.layout_detect import detect_page

    raw = detect_page(_RECALL_ENGINE, crop_path)
    return [[float(v) for v in d["box"]] for d in raw["detections"] if d["box"]]


def _tile_detect(image: Any, detect: Any, crop_dir: Path, target: int = 1300, overlap: int = 300) -> list[list[float]]:
    """The tile pass (2026-08-28): the full-page detection's internal
    resize is capped by max_side_limit=4000 to ~0.86x of a 2544px-wide
    page — small handwriting words merge into their neighbours and the
    line extensions vanish (page-01: the 'margin notes' are the lines'
    own starts at x~543, merged into the body words at 0.86x). A 2D
    grid of ~``target``-px tiles gets the short side upscaled to the
    2000px limit while the long side stays under the 4000px cap:
    ~1.4-1.5x effective resolution per tile (the 1300px sweet spot:
    below it the long-side cap binds, above it the upscale shrinks).
    The overlap keeps lines straddling a tile boundary fully inside
    one tile. Crop-local boxes offset to page space; near-identical
    duplicates from the overlap zones dedupe. ``detect(engine,
    crop_path)`` is the injectable seam."""
    w, h = image.size
    n_vert = max(1, math.ceil(w / target))
    n_horiz = max(1, math.ceil(h / target))
    xs = _tile_steps(w, n_vert, overlap)
    ys = _tile_steps(h, n_horiz, overlap)
    pieces: list[list[float]] = []
    i = 0
    for x0, x1 in xs:
        for y0, y1 in ys:
            crop = crop_dir / f"tile-{i}.png"
            i += 1
            image.crop((x0, y0, x1, y1)).save(crop)
            for box in detect(None, crop):
                pieces.append([box[0] + x0, box[1] + y0, box[2] + x0, box[3] + y0])
    # drop noise slivers (the upscaled tiles over-detect page specks —
    # 2026-08-28: 17x3px pieces clustered into absurd rows on page-01;
    # real text at this scan scale is 40-70px tall), then dedupe
    # near-identical overlap duplicates (all 4 corners within 2px)
    unique: list[list[float]] = []
    for p in sorted(pieces, key=lambda b: (b[1], b[0])):
        if p[2] - p[0] < 20 or p[3] - p[1] < 20:
            continue
        if not any(
            abs(p[0] - q[0]) <= 2 and abs(p[1] - q[1]) <= 2 and abs(p[2] - q[2]) <= 2 and abs(p[3] - q[3]) <= 2
            for q in unique
        ):
            unique.append(p)
    return unique


def _tile_steps(size: int, n: int, overlap: int) -> list[tuple[int, int]]:
    """The covered, overlapped start/end pairs for one axis of the
    tile grid: ``n`` tiles, each ``step + overlap`` long, the total
    covering ``size`` (the last tile ends exactly at ``size``)."""
    step = max(1, (size + overlap) // n - overlap)
    spans = []
    x0 = 0
    while x0 < size:
        x1 = min(size, x0 + step + overlap)
        spans.append((x0, x1))
        if x1 >= size:
            break
        x0 += step
    return spans


def _gap_merged_runs(runs: list[tuple[int, int]], gap: int, last_row: int | None = None) -> list[tuple[int, int]]:
    """The proj>0 runs, gap-merged within ``gap`` rows — the
    handwriting's strokes leave 1-row gaps; a sparse row must not
    split a band (extracted from ink_layout_boxes 2026-08-29 for the
    complexity bar)."""
    merged: list[tuple[int, int]] = []
    for b in runs:
        if merged and b[0] - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], b[1])
        else:
            merged.append(b)
    return merged


def _adaptive_ink(arr: Any) -> tuple[Any, int, int]:
    """The ink-layout's ink: pixel < local_median - 35 (a 4x4 block
    median — the pipeline's has_ink threshold; the scan's shading is
    not ink). Returns (ink-mask, block_rows, width) (extracted from
    ink_layout_boxes 2026-08-29 for the complexity bar)."""
    h, w = arr.shape
    block = 4
    bh, bw = h // block, w // block
    a = arr[: bh * block, : bw * block]
    level = np.repeat(np.repeat(np.median(a.reshape(bh, block, bw, block), axis=(1, 3)), block, axis=0), block, axis=1)
    return a < (level - 35), bh, w


def _text_lines(p: Any, y0: int, y1: int) -> list[tuple[int, int]]:
    """The band's text lines: the profile's ≥0.12x-max rows, gap-merged
    within 6 rows (extracted from ink_layout_boxes 2026-08-29 for the
    complexity bar)."""
    text_rows = p >= 0.12 * p.max()
    lines: list[tuple[int, int]] = []
    s2 = None
    for i, t in enumerate(text_rows):
        if t and s2 is None:
            s2 = i
        elif not t and s2 is not None:
            if i - s2 >= 15:
                lines.append((s2 + y0, i - 1 + y0))
            s2 = None
    if s2 is not None and y1 - s2 >= 15:
        lines.append((s2 + y0, y1))
    lmerged: list[tuple[int, int]] = []
    for ln in lines:
        if lmerged and ln[0] - lmerged[-1][1] <= 6:
            lmerged[-1] = (lmerged[-1][0], ln[1])
        else:
            lmerged.append(ln)
    return lmerged


def _line_ink_boxes(a: Any, ly0: int, ly1: int, word_gap: int, min_w: int) -> list[list[float]]:
    """One text line's x-runs, split at word gaps into boxes of at
    least ``min_w`` — the raw ink (< 200) so the boxes cover the
    gate's measure: the faint marks the adaptive threshold excluded
    (extracted from ink_layout_boxes 2026-08-29 for the complexity
    bar)."""
    lxs = np.where((a[ly0 : ly1 + 1] < 200).sum(axis=0) > 0)[0]
    if len(lxs) == 0:
        return []
    runs: list[tuple[int, int]] = []
    rs = [int(lxs[0]), int(lxs[0])]
    for x in lxs[1:]:
        xi = int(x)
        if xi - rs[1] <= word_gap:
            rs[1] = xi
        else:
            runs.append((rs[0], rs[1]))
            rs = [xi, xi]
    runs.append((rs[0], rs[1]))
    return [[float(x0b), float(ly0), float(x1b), float(ly1)] for x0b, x1b in runs if x1b - x0b >= min_w]


def ink_layout_boxes(image: Any, word_gap: int = 80, min_w: int = 40) -> list[list[float]]:
    """The ink-layout (2026-08-28): the dense-cursive rescue. A letter's
    margin notes (annotations) interleave with the main text at the same
    y-bands; the piece-based line model cannot separate them (the pieces
    span the interleaving, the boxes double-claim). The ink-layout reads
    the page DIRECTLY, no detector pieces:
    - the ADAPTIVE ink: pixel < local_median - 35 (a 4x4 block median —
      the pipeline's has_ink threshold; the scan's shading is not ink);
      a line with a real gap (the item's end vs the annotation's start)
      becomes TWO boxes; a continuous line stays ONE box. The boxes are
      x-disjoint by construction — no double-claims regardless of the
      y-interleaving — and they ARE the ink, so coverage and fragments
      pass by construction. The item and its annotation are separate
      transcript lines: the letter's own sense is preserved."""
    arr = np.array(image.convert("L")).astype(np.int16)
    ink, bh, w = _adaptive_ink(arr)
    # the MID column: the words' x-height zone (page-01's only clean
    # band source — the left edge has the scan's shading, the right
    # edge the interleaving with the annotations)
    mid = (int(w * 0.30), int(w * 0.57))
    proj = ink[:, mid[0] : mid[1]].sum(axis=1)
    # the 7-wide smoothing: the real page's profile is dense (every
    # row inked), and a wider kernel also bridges the sparse rows of a
    # synthetic/scan with 3-row stroke gaps without merging the
    # descender bridges (their counts stay far below the threshold)
    kernel = np.ones(7) / 7
    # all proj>0 runs, gap-merged (the handwriting's strokes leave
    # 1-row gaps — a sparse row must not split a band), then the
    # min-height applies to the MERGED runs
    merged = _gap_merged_runs(projection_runs(proj), 8)
    bands = [b for b in merged if b[1] - b[0] + 1 >= 20]
    boxes: list[list[float]] = []
    for y0, y1 in bands:
        p = np.convolve(proj[y0 : y1 + 1].astype(float), kernel, mode="same")
        if p.max() <= 0:
            continue
        for ly0, ly1 in _text_lines(p, y0, y1):
            boxes.extend(_line_ink_boxes(arr, ly0, ly1, word_gap, min_w))
    # the raw-ink x-runs catch the scan's SHADING (light-gray pixels,
    # no dark text — 2026-08-28: 9 no_ink boxes of 60 on page-01).
    # has_ink (median - 35) is the honest test: a region whose pixels
    # are all near its own median is shading, not text.
    boxes = [b for b in boxes if has_ink(b, image)]
    # the decoration strips (underlines/swirls, h=14-22 vs the letter's
    # 27-70px lines) are ink but not text — the min-height drops them
    return [b for b in boxes if b[3] - b[1] >= 25]


def _detect_pieces(engine: Any, panel_path: Path) -> list[list[float]]:
    """The rec's detection pieces (the REAL ink)."""
    # lucidlint: ignore inline-import the .venv-htr seam — paddleocr lives only in .venv-htr
    from tools.layout_detect import detect_page

    raw = detect_page(engine, panel_path)
    return [[float(v) for v in d["box"]] for d in raw["detections"] if d["box"]]


def needs_row_reads(row_count: int, line_count: int) -> bool:
    """Did the model under-read so badly that proportional matching
    cannot be trusted? (2026-08-26: the birth cert's 40 measured rows
    vs 16 VLM lines — the model's 40%-plausibility floor let exactly
    16 lines through and matching smeared them across the rows.) When
    the line count falls below two-thirds of the rows on a page with
    at least 10 rows, every row gets its own clip read instead. Tiny
    pages are exempt (the rec over-splits their fragments into rows)."""
    return row_count >= 10 and line_count * 3 < row_count * 2


def _safe_row_read(read: Any, box: list[float]) -> str | None:
    """One row clip read that cannot crash the batch — a failure
    returns None and the row stays empty (the page refuses honestly;
    2026-08-26: the budget-exhaustion VlmError aborted a whole run)."""
    try:
        return read(box)
    except Exception:
        return None


def _drop_unreadable(boxes: list[list[float]], labels: Sequence[str | None]) -> tuple[list[list[float]], list[str]]:
    """The ink-layout's edge artifacts (2026-08-28): the scan's
    right-edge marks (x 2005+) and stray left-edge specks pass has_ink
    but the VLM reads NOTHING — they are not text. The empty-labeled
    boxes drop after the fills; their ink stays unboxed and visible,
    the page's honest boxes serve."""
    kept: list[list[float]] = []
    kept_labels: list[str] = []
    for b, lab in zip(boxes, labels, strict=True):
        if (lab or "").strip():
            kept.append(b)
            kept_labels.append(lab or "")
    return kept, kept_labels


def _violation_indices(
    page_unions: list[list[float]],
    labels: list[str],
    pieces_for_cov: list[list[float]],
    im: Any,
    glyph_check: bool,
) -> tuple[list[int], list[int], list[int], list[int], list[int]]:
    """(bad, no_ink, multi, fragments, glyph) — the union of every
    gate's bad indices for one page plus the per-gate breakdown for
    the report counts (extracted from _gate_layout 2026-08-29)."""
    no_ink = [i for i, u in enumerate(page_unions) if not has_ink(u, im)]
    multi = [i for i, u in enumerate(page_unions) if text_line_count(u, im) > 1]
    fragments = [
        i
        for i, u in enumerate(page_unions)
        if fragment_violation(u, im, siblings=[v for j, v in enumerate(page_unions) if j != i])
    ]
    glyph = (
        [i for i, u in enumerate(page_unions) if glyph_extent_violation(labels[i], u, orientation_from_aspect(u))]
        if glyph_check
        else []
    )
    all_bad = set(no_ink) | set(multi) | set(fragments) | set(glyph)
    if coverage_violations(page_unions, pieces_for_cov)[0]:
        all_bad |= set(range(len(page_unions)))
    return sorted(all_bad), no_ink, multi, fragments, glyph


def _line_records(page_unions: list[list[float]], labels: list[str]) -> list[dict]:
    """The assembled transcript records for one page (extracted from
    _gate_layout 2026-08-29 for the complexity bar)."""
    return [
        {
            "index": i,
            "text": labels[i],
            "box": [round(v) for v in u],
            "conf": 1.0,
            "words": [],
            "box_source": "ink",
            "orientation": orientation_from_aspect(u),
        }
        for i, u in enumerate(page_unions)
    ]


def _split_row_reads(
    page_unions: list[list[float]], piece_list: list[list[float]], ox: float, oy: float
) -> list[list[float]]:
    """The under-read path's per-row split: a row whose box is wider
    than 25x its height holds MULTIPLE transcript lines (the model's
    line count fell below the measured rows, so proportional matching
    smeared them) — split it at its piece gaps (extracted from
    assemble 2026-08-29 for the complexity bar)."""
    read_unions: list[list[float]] = []
    for u in page_unions:
        w = u[2] - u[0]
        h = u[3] - u[1]
        if h > 0 and w / h > 25:
            in_row = [
                p
                for p in (offset_box(q, ox, oy) for q in piece_list)
                if u[1] <= (p[1] + p[3]) / 2 <= u[3] and u[0] <= p[0] and p[2] <= u[2]
            ]
            parts = split_row_at_piece_gaps(in_row) if in_row else [[u]]
            read_unions.extend([union(p) for p in parts if p])
        else:
            read_unions.append(u)
    return read_unions


def _assemble_page(
    piece_list: list[list[float]],
    im: Any,
    ctx: tuple[float, float, list[str], Any, str],
    conn: tuple[str, str, str | None],
    batch_ctx: tuple[int, Path],
) -> tuple[list[dict], dict[str, int], list[int], list[list[float]], list[str], int, int]:
    """One page's full assembly from its PIECES: cluster, band-split,
    label (the under-read path + fills), gates. Unified so the recall
    pass can re-assemble with merged pieces (hoisted out of the page
    loop 2026-08-29 — the closure carried every page's captured state
    into a fresh nested function per page)."""
    workers, tmp_base = batch_ctx
    ox, oy, texts, bands, page_name = ctx
    pw, ph = im.size
    rows = cluster_rows([offset_box(p, ox, oy) for p in piece_list])
    page_unions = [
        part
        for u in (union(r) for r in rows)
        for part in (split_by_bands(u, im) if text_line_count(u, im) > 1 else [u])
    ]
    labels = match_labels(page_unions, texts, bands)
    clip_dir = Path(tempfile.mkdtemp(prefix="eval-clip-", dir=str(tmp_base)))
    read_clip = _make_row_reader(im, clip_dir, page_name, conn)

    # The under-read path: when the model's line count falls far
    # below the measured rows, proportional matching smears lines
    # across rows — every inky row gets its own clip read.
    if needs_row_reads(len(page_unions), len(texts)):
        read_unions = _split_row_reads(page_unions, piece_list, ox, oy)
        with ThreadPoolExecutor(max_workers=min(4, workers)) as pool:
            read_results = list(pool.map(lambda u: _safe_row_read(read_clip, u), read_unions))
        labels = [r or "" for r in read_results]
        page_unions = read_unions
        print(f"  {page_name}: row-read path ({len(labels)} rows)", file=sys.stderr)
    labels = fill_unlabeled_labels(labels, page_unions, im, read_clip)
    shutil.rmtree(clip_dir, ignore_errors=True)
    all_pieces_for_cov = [offset_box(p, ox, oy) for p in piece_list]
    out_lines, counts, bad = _gate_layout(page_unions, labels, all_pieces_for_cov, im)
    return out_lines, counts, bad, page_unions, labels, pw, ph


def _gate_layout(
    page_unions: list[list[float]],
    labels: list[str],
    pieces_for_cov: list[list[float]],
    im: Any,
    glyph_check: bool = True,
) -> tuple[list[dict], dict[str, int], list[int]]:
    """The gates for an assembled page (2026-08-28: extracted from
    assemble so the ink-layout's rescue path runs the SAME checks —
    one contract for every box source). ``glyph_check`` stays on for
    the PIECES-based paths (a label-vs-extent mismatch means a wrong
    box); the ink-layout's boxes ARE the ink, so a mismatch can only
    be the VLM read's fault — the reviewer's to fix, not a refusal."""
    bad, no_ink, multi, fragments, glyph = _violation_indices(page_unions, labels, pieces_for_cov, im, glyph_check)
    uncovered = len(coverage_violations(page_unions, pieces_for_cov)[0])
    double_claims = coverage_violations(page_unions, pieces_for_cov)[1]
    out_lines = _line_records(page_unions, labels)
    counts = {
        "no_ink": len(no_ink),
        "multi": len(multi),
        "fragments": len(fragments),
        "uncovered": uncovered,
        "double": double_claims,
        "glyph": len(glyph),
    }
    return out_lines, counts, bad


def _make_row_reader(image: Any, clip_dir: Path, page_name: str, conn: tuple[str, str, str | None]) -> Any:
    model, base_url, api_key = conn
    """The per-box clip reader (2026-08-28: extracted from assemble so
    the ink-layout's rescue labels its boxes with the SAME cached-VLM
    seam — sha256-keyed, zero tokens on a hit)."""

    def read(box: list[float]) -> str:
        clip = clip_dir / f"{page_name}-{int(box[0])}-{int(box[1])}.png"
        image.crop((int(box[0]), int(box[1]), int(box[2]), int(box[3]))).save(clip)
        spec = {"model": model, "max_tokens": 4000}
        cached = load_cached_read(clip, spec)
        if cached is not None:
            return cached[0]
        text, usage = transcribe_image_vlm(
            clip,
            model=model,
            system=transcription_system_with_context(request_boxes=False),
            base_url=base_url,
            api_key=api_key,
            max_tokens=4000,
        )
        store_read(clip, spec, text, int(usage.get("total_tokens", 0) or 0))
        return text

    return read


def fill_unlabeled_labels(labels: Sequence[str | None], unions: list[list[float]], image: Any, read: Any) -> list[str]:
    """Rows the VLM left unlabeled get ONE targeted read of their own
    clip (2026-08-26, the label-completeness lever: page-12 and the
    birth certs refuse on empty-text rows although the ink is there —
    the model under-read). Only inky, unlabeled rows are read; a failed
    read leaves the row empty and the page refuses honestly — never an
    invented label."""
    out = list(labels)
    for i, label in enumerate(labels):
        # a None label (a failed _safe_row_read) is an empty label —
        # the ink-layout path crashed the batch on label.strip() here
        # (2026-08-28)
        if (label or "").strip() or not has_ink(unions[i], image):
            continue
        try:
            text = read(unions[i])
        # lucidlint: ignore swallow a failing clip read must never abort the batch; the row stays empty
        except Exception:
            # VlmError crashed the whole run mid-photos)
            text = None
        if text and text.strip():
            out[i] = text.strip().split("\n")[0]
    # a failed read leaves the row EMPTY — never None (2026-08-28:
    # the ink-layout's labels escaped as None and the gates crashed
    # on text.strip())
    return [lab or "" for lab in out]


def normalized_bands(
    lines: list[str], boxes: dict[int, list[float]] | None, frame_h: float
) -> list[tuple[float, float, str]]:
    """The model's normalized 0-1000 line bands in the frame's PIXELS —
    the scale match_labels's y-overlap compares against (the measured
    unions are panel pixels; the first batch run hardcoded 1600 here and
    every other panel height silently shifted its overlaps)."""
    bands: list[tuple[float, float, str]] = []
    for i, b in sorted((boxes or {}).items()):
        if i < len(lines):
            bands.append(((b[1] / 1000) * frame_h, (b[3] / 1000) * frame_h, lines[i]))
    return bands


def _self_report_for(panel: Path, full_text: str) -> list[dict]:
    """The model's doubt flags for one panel's transcription — cached
    like the reads (the flags are a pure function of the read). Runs in
    Phase 2, where the panel still exists."""
    cached = load_selfreport(panel, full_text)
    if cached is not None:
        return cached

    def _sr_call(image, *, system, user_text=None, **kw):
        # the 64000 default hangs this model on a page image (the trial
        # report's budget finding); the doubt list is small
        return transcribe_image_vlm(image, system=system, user_text=user_text, max_tokens=8000, **kw)

    report = selfreport_words(panel, full_text, transcribe=_sr_call)
    store_selfreport(panel, full_text, report)
    if report:
        print(f"  self-report: {len(report)} entries: {report}", file=sys.stderr)
    return report


def _vlm_read(
    panel_path: str, panel_h: int, row_count: int, conn: tuple[str, str, str | None]
) -> tuple[list[str], list[tuple[float, float, str]], int]:
    model, base_url, api_key = conn
    """One panel's VLM read — the text + the normalized bands. The
    escalation ladder (2026-08-25): first the boxed JSON read, then a
    plain-text re-read (no format to fail mid-echoing; a fraction of the
    tokens), then the plain-text read on the fallback model (glm-4.5v,
    the trial's runner-up with a different failure profile). A response
    must also plausibly cover the measured rows — the birth certificate's
    collapse folded 26 rows into one line."""

    def usable(text: str) -> bool:
        if transcription_problem(text) is not None:
            return False
        plain, _boxes = parse_transcription_response(text)
        return transcription_line_count_plausible(len([ln for ln in plain.split("\n") if ln.strip()]), row_count)

    # The read cache (2026-08-26): keyed on the PANEL BYTES + primary
    # model + budget — any ladder variant's successful read is a valid
    # transcription of that panel, so gate/assembly iterations over
    # unchanged pages cost zero tokens. LOFT_VLM_CACHE=0 bypasses.
    cache_spec = {"model": model, "max_tokens": 8000}
    cached = load_cached_read(Path(panel_path), cache_spec)
    tokens = 0
    if cached is not None:
        # zero NEW tokens: the spend happened in an earlier run
        text, _stored_tokens = cached
        print(f"  vlm {Path(panel_path).name}: CACHED", file=sys.stderr)
    else:
        variants = [
            {
                "model": model,
                "system": transcription_system_with_context(),
                "base_url": base_url,
                "api_key": api_key,
                "max_tokens": 8000,
            },
            {
                "model": model,
                "system": transcription_system_with_context(request_boxes=False),
                "base_url": base_url,
                "api_key": api_key,
                "max_tokens": 8000,
            },
            {
                "model": FALLBACK_MODEL,
                "system": transcription_system_with_context(request_boxes=False),
                "base_url": base_url,
                "api_key": api_key,
                "max_tokens": 8000,
            },
        ]
        text, usage = transcribe_with_fallbacks(Path(panel_path), variants, usable=usable)
        tokens = int(usage.get("total_tokens", 0) or 0)
        store_read(Path(panel_path), cache_spec, text, tokens)
    plain, boxes = parse_transcription_response(text)
    return plain.split("\n"), normalized_bands(plain.split("\n"), boxes, panel_h), tokens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval_batch")
    parser.add_argument("batch_ids", nargs="+")
    parser.add_argument("--model", default="z-ai/glm-4.6v")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--pages", default="", help="comma-separated page stems; empty = all")
    args = parser.parse_args(argv)
    api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY")

    t0 = monotonic()
    total_written = 0
    total_refused = 0
    total_tokens = 0
    reports: list[dict[str, Any]] = []

    for batch_id in args.batch_ids:
        result = _process_batch(
            batch_id,
            args.work_dir,
            (args.model, args.base_url, api_key),
            args.workers,
            wanted={s for s in args.pages.split(",") if s},
        )
        reports.append(result)
        total_written += result["written"]
        total_refused += result["refused"]
        total_tokens += result["tokens"]

    elapsed = round(monotonic() - t0, 1)
    print(
        json.dumps(
            {
                "written": total_written,
                "refused": total_refused,
                "tokens": total_tokens,
                "elapsed_s": elapsed,
                "reports": reports,
            },
            indent=1,
        )
    )
    return 0


def _detect_phase(
    pages_with_text: list[Path],
    engine: Any,
    panel_dir: Path,
    batch: tuple[str, PipelineStore, Path],
    panels: dict[str, dict[str, Any]],
) -> None:
    """Phase 1: rec-detect each page's content panel (local, sequential).
    A stored clean layout skips its page (extracted from _process_batch
    2026-08-29 for the complexity bar). ``batch`` = (batch_id, store,
    tmp_base)."""
    batch_id, store, _tmp_base = batch
    for ip in pages_with_text:
        pg = ip.stem
        lp = f"{batch_id}/ocr-guess/{pg}.layout.json"
        try:
            layout = load_layout_store(store, lp)
        # lucidlint: ignore swallow a stored layout unreadable falls back to a fresh run; the error is surfaced
        except Exception:
            layout = None
        if layout is not None and layout_is_current(layout) and not validate_layout(layout):
            print(f"  {pg}: stored layout clean, skipping", file=sys.stderr)
            continue
        prep = prep_panel(ip, layout, panel_dir, pg)
        if not prep:
            continue
        try:
            pieces = _detect_pieces(engine, Path(prep["path"]))
            rows = cluster_rows(pieces)
            unions = [union(r) for r in rows]
            panels[pg] = {
                "path": prep["path"],
                "h": prep["h"],
                "x0": prep["x0"],
                "y0": prep["y0"],
                "unions": unions,
                "pieces": pieces,
            }
        # lucidlint: ignore swallow the batch isolates one page's failure; the rec error is surfaced above
        except Exception as exc:
            print(f"  rec {pg} FAILED: {str(exc)[:80]}", file=sys.stderr)


def _vlm_read_phase(
    panels: dict[str, dict[str, Any]],
    workers: int,
    conn: tuple[str, str, str | None],
    oriented_dir: Path,
    vlm_results: dict[str, tuple[list[str], list[tuple[float, float, str]], int, list[dict]]],
) -> None:
    """Phase 2: VLM-read all panels (parallel, network-bound). One
    page's failure is surfaced and isolated; the batch continues
    (extracted from _process_batch 2026-08-29 for the complexity bar)."""
    model, base_url, api_key = conn
    futures = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for pg, panel in panels.items():
            row_count = len(panel["unions"])
            futures[pool.submit(_vlm_read, panel["path"], panel["h"], row_count, (model, base_url, api_key))] = pg
        for future in as_completed(futures):
            pg = futures[future]
            try:
                texts, bands, tok = future.result()
                report = _self_report_for(Path(panels[pg]["path"]), "\n".join(texts))
                vlm_results[pg] = (texts, bands, tok, report)
                print(f"  vlm {pg}: {len(bands)} bands, {tok} tok", file=sys.stderr)
            # lucidlint: ignore swallow one page's VLM failure; surfaced above, the batch continues
            except Exception as exc:
                print(f"  vlm {pg} FAILED: {exc}", file=sys.stderr)


def _box_dims(page_unions: list[list[float]], i: int) -> str:
    """One bad box's WxH for the refusal detail line (hoisted from the
    refusal branch 2026-08-29 — the nested closure broke the closures
    rule)."""
    b = page_unions[i]
    return f"{int(b[2] - b[0])}x{int(b[3] - b[1])}"


def _rescue_page(
    page: tuple[str, Any, list[list[float]], float, float, list[str], Any],
    batch_ctx: tuple[tuple[str, str, str | None], int, Path],
    current: tuple[list[dict], dict[str, int], list[int], int, int],
) -> tuple[list[dict], dict[str, int], list[int], int, int]:
    """The rescue passes for a page that refused on fragments/glyph
    (extracted from _assemble_phase 2026-08-29 for the complexity bar):
    (1) the tile recall — the full-page detection under-segmented at
    ~0.86x internal resize; detect in overlapped tiles at ~1.5x and
    MERGE the new pieces into the base (the tile set ALONE
    over-segments: 29 fragments on page-01 vs 8 for the merge —
    2026-08-28); (2) the ink-layout — the dense-cursive rescue, reading
    the page directly (2026-08-28). ``page`` = (pg, im, base_pieces,
    x0, y0, texts, bands); ``batch_ctx`` = (conn, workers, tmp_base);
    ``current`` = the best (out_lines, counts, bad, pw, ph) found.
    Returns the best (out_lines, counts, bad, pw, ph) found."""
    pg, im, base_pieces, x0, y0, texts, bands = page
    conn, workers, tmp_base = batch_ctx
    out_lines, counts, bad, pw, ph = current
    model, base_url, api_key = conn
    recall_dir = Path(tempfile.mkdtemp(prefix="eval-recall-", dir=str(tmp_base)))
    try:
        new_pieces = _tile_detect(im, _recall_detect, recall_dir)
    finally:
        shutil.rmtree(recall_dir, ignore_errors=True)
    print(f"  {pg}: recall tile pieces={len(new_pieces)}", file=sys.stderr)
    if new_pieces:
        # The tile set MERGES into the base: the base's coarse pieces
        # are the reliable word anchors, the tile pieces fill the
        # under-segmented gaps.
        merged = base_pieces + new_pieces
        out_lines2, counts2, bad2, _u2, _l2, _pw2, _ph2 = _assemble_page(
            merged, im, (x0, y0, texts, bands, pg), conn, (workers, tmp_base)
        )
        if not bad2:
            out_lines, counts, bad = out_lines2, counts2, bad2
            print(f"  {pg}: recall rescued ({len(merged)} merged pieces)", file=sys.stderr)
        else:
            print(f"  {pg}: recall reassemble still bad {counts2}", file=sys.stderr)
    if bad:
        # The ink-layout (2026-08-28): the dense-cursive rescue. Margin
        # notes interleave with the main text at the same y-bands; the
        # piece model cannot separate them (the pieces span the
        # interleaving, the boxes double-claim). The ink-layout reads
        # the page DIRECTLY: lines from the adaptive ink, each line's
        # x-runs — a line with a real gap becomes TWO boxes (the item +
        # its annotation, transcribed separately: the letter's sense is
        # preserved), a continuous line stays ONE box. X-disjoint by
        # construction: no double-claims, fragments pass.
        ink_boxes = ink_layout_boxes(im)
        print(f"  {pg}: ink-layout boxes={len(ink_boxes)}", file=sys.stderr)
        if ink_boxes:
            clip_dir = Path(tempfile.mkdtemp(prefix="eval-ink-", dir=str(tmp_base)))
            try:
                ink_read = _make_row_reader(im, clip_dir, pg, conn)
                with ThreadPoolExecutor(max_workers=min(4, workers)) as pool:
                    ink_labels = list(pool.map(lambda u, _r=ink_read: _safe_row_read(_r, u), ink_boxes))
                ink_labels = fill_unlabeled_labels(ink_labels, ink_boxes, im, ink_read)
            finally:
                shutil.rmtree(clip_dir, ignore_errors=True)
            ink_boxes, ink_labels = _drop_unreadable(ink_boxes, ink_labels)
            ink_pieces = [offset_box(p, x0, y0) for p in base_pieces] + new_pieces
            # the ink-layout's boxes ARE the ink — the glyph gate's
            # label-vs-extent mismatch is the READ's fault (the
            # reviewer's fix), never a wrong box
            out_lines3, counts3, bad3 = _gate_layout(ink_boxes, ink_labels, ink_pieces, im, glyph_check=False)
            for ln in out_lines3:
                ln["box_source"] = "ink-layout"  # Gate B skips the read-fault labels
            if not bad3:
                out_lines, counts, bad = out_lines3, counts3, bad3
                pw, ph = im.size
                print(f"  {pg}: ink-layout rescued ({len(ink_boxes)} boxes)", file=sys.stderr)
            else:
                print(f"  {pg}: ink-layout still bad {counts3}", file=sys.stderr)
    return out_lines, counts, bad, pw, ph


def _assemble_phase(
    panels: dict[str, dict[str, Any]],
    vlm_results: dict[str, tuple[list[str], list[tuple[float, float, str]], int, list[dict]]],
    batch_ctx: tuple[Path, tuple[str, str, str | None], int, Path, PipelineStore, str],
) -> tuple[int, int]:
    """Phase 3: assemble each page, run the rescue passes (tile recall,
    ink-layout) on refusals, validate and write. Returns (written,
    refused) (extracted from _process_batch 2026-08-29 for the
    complexity bar). ``batch_ctx`` = (oriented_dir, conn, workers,
    tmp_base, store, batch_id)."""
    oriented_dir, conn, workers, tmp_base, store, batch_id = batch_ctx
    model, base_url, api_key = conn
    written = 0
    refused = 0
    for pg in sorted(panels):
        result = vlm_results.get(pg)
        if not result:
            continue
        texts, bands, _tok, report = result
        x0, y0 = panels[pg]["x0"], panels[pg]["y0"]

        with Image.open(oriented_dir / f"{pg}.jpg") as im:
            out_lines, counts, bad, page_unions, labels, pw, ph = _assemble_page(
                panels[pg]["pieces"], im, (x0, y0, texts, bands, pg), (model, base_url, api_key), (workers, tmp_base)
            )
            if bad and (counts["fragments"] or counts["glyph"]):
                out_lines, counts, bad, pw, ph = _rescue_page(
                    (pg, im, panels[pg]["pieces"], x0, y0, texts, bands),
                    ((model, base_url, api_key), workers, tmp_base),
                    (out_lines, counts, bad, pw, ph),
                )

        if bad:
            refused += 1
            detail = ", ".join(f"{i}:{labels[i][:16]!r}({_box_dims(page_unions, i)})" for i in bad[:8])
            print(
                f"  {pg} REFUSED (no-ink={counts['no_ink']} multi-band={counts['multi']} "
                f"glyph={counts['glyph']} fragment={counts['fragments']} "
                f"uncovered={counts['uncovered']} double={counts['double']}): {detail}",
                file=sys.stderr,
            )
            continue
        # The self-report stage: the model's doubt flags (collected in
        # Phase 2, where the panel exists) mark the UI's "red words" —
        # flags-only, never a gate.
        by_line = selfreport_words_by_line([ln["text"] for ln in out_lines], report)
        flagged = sum(len(v) for v in by_line.values())
        if flagged:
            print(f"  {pg}: {flagged} self-flagged words", file=sys.stderr)
        for ln in out_lines:
            ln["words"] = flag_line_words(ln["text"], by_line.get(ln["index"], set()))
        assembled = {"page": pg, "width": pw, "height": ph, "lines": out_lines, "unmatched": []}

        violations = validate_layout(assembled)
        if violations:
            refused += 1
            print(f"  {pg} REFUSED ({len(violations)}): {violations[0][:80]}", file=sys.stderr)
            continue
        write_layout_store(assembled, store, f"{batch_id}/ocr-guess/{pg}.layout.json")
        written += 1
        print(f"  {pg} written ({len(out_lines)} lines)", file=sys.stderr)
    return written, refused


def _process_batch(
    batch_id: str,
    work_dir: Path,
    conn: tuple[str, str, str | None],
    workers: int,
    wanted: set[str] | None = None,
) -> dict[str, Any]:
    model, base_url, api_key = conn
    oriented_dir = work_dir / batch_id / "oriented"
    guess_dir = work_dir / batch_id / "ocr-guess"
    store = PipelineStore(work_dir)
    # the batch's temp panels/tiles/clips live on the WORK DISK, not
    # /tmp: the shared tmpfs fills with other sessions' work and the
    # PNG saves hit 'Disk quota exceeded' mid-batch (2026-08-28)
    tmp_base = work_dir / "tmp"
    tmp_base.mkdir(exist_ok=True)
    image_paths = sorted(oriented_dir.glob("*.jpg"))

    pages_with_text = [p for p in image_paths if (guess_dir / p.with_suffix(".txt").name).exists()]
    if wanted:
        pages_with_text = [p for p in pages_with_text if p.stem in wanted]
    print(f"batch {batch_id}: {len(pages_with_text)} pages", file=sys.stderr)

    panels: dict[str, dict[str, Any]] = {}
    engine = _make_engine()
    # The engine is freed after Phase 1 — the recall pass's low-sensitivity
    # engine must never coexist with it (the OOM history; two PaddleOCR
    # instances is a full page of RAM each).
    # The panels persist through BOTH phases — a TemporaryDirectory here
    # would delete them before Phase 2 reads them (2026-08-22).
    panel_dir = Path(tempfile.mkdtemp(prefix="eval-batch-", dir=str(tmp_base)))
    try:
        _detect_phase(pages_with_text, engine, panel_dir, (batch_id, store, tmp_base), panels)
        # Phase 2: VLM-read all panels (parallel, network-bound) — INSIDE
        # this try: the panels must live through it; cleanup waits for
        # the finally below.
        vlm_results: dict[str, tuple[list[str], list[tuple[float, float, str]], int, list[dict]]] = {}
        _vlm_read_phase(panels, workers, conn, oriented_dir, vlm_results)
    finally:
        del engine  # free the main engine BEFORE the recall pass can spawn its own
        # the panels must live through Phase 2 (2026-08-22) — and die
        # after it: the uncleaned mkdtemp dirs leaked ~2.8G of full-page
        # PNGs into /tmp across five batch runs and filled the tmpfs
        # that pytest's own tempdir shares (2026-08-26).
        shutil.rmtree(panel_dir, ignore_errors=True)

    # Phase 3: assemble + validate + write
    written, refused = _assemble_phase(
        panels, vlm_results, (oriented_dir, (model, base_url, api_key), workers, tmp_base, store, batch_id)
    )
    batch_tokens = sum(r[2] for r in vlm_results.values())

    return {
        "batch": batch_id,
        "pages": len(pages_with_text),
        "written": written,
        "refused": refused,
        "tokens": batch_tokens,
        "vlm_elapsed_s": round(sum(r[2] for r in vlm_results.values()) / 100, 1),
    }


def _make_engine() -> Any:
    # lucidlint: ignore inline-import the .venv-htr seam — paddleocr lives only in .venv-htr; the main venv lacks it
    from paddleocr import PaddleOCR  # type: ignore[missing-import]  # paddleocr lives only in .venv-htr

    # lucidlint: ignore inline-import the same seam — ENGINE imports layout_detect, which loads paddleocr
    from tools.layout_detect import ENGINE

    return PaddleOCR(**ENGINE)


if __name__ == "__main__":
    sys.exit(main())
