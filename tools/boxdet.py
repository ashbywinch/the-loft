"""Box detection spike — the reworked pipeline (detector + stroke correction).

    .venv/bin/python /tmp/boxspike.py        # runs end to end, exports for the jig

The page is processed once; every stage is deterministic and stated in the
data's own scale (word size, line pitch, ink gaps), never in absolute page
units that only fit this scan.

Stages
  1  ink mask      the raster: pixels darker than their local paper level
  2  artifacts     long thin streaks (scan lines, rules) removed before shapes
  3  shapes        connected components of ink = words (or letters, in print)
  4  lines         fitted baselines: seed by row, refit + reassign, split a line
                   whose words spread across more than one line, merge fits that
                   describe the same baseline
  5  shapes→line   every shape belongs to exactly ONE line (its densest row's
                   nearest fitted baseline), and a shape that spans two lines is
                   split between them — ink welding two lines is the trap here
  6  detector      one box per line-run: the line's words, split at column-sized
                   x gaps, extent = the ink's own (ascenders/descenders included,
                   capped at ±0.8 pitch)
  7  strokes       a stroke IS a line: it is assigned to the line owning most of
                   the words it covers, and it may not sit more than half a pitch
                   from that line (else it founds its own)
  8  compose       the detector boxes the page; a trace replaces the detector's
                   box over the span it defines (which splits a detector box when
                   the trace covers only part of its text). Text under no box and
                   no trace is reported as leftover for the user to fix.

Outputs: /tmp/trace/boxes.json, words.json, summary.json — consumed by
/tmp/trace_jig.py, which asserts the invariants and exits non-zero on failure.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter  # noqa: E402

from tools.boxscale import line_ratio, traced_pitch, writing_scale

BATCH = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004")
PAGE = BATCH / "oriented/page-01.jpg"
TRACE = Path("/tmp/trace")
TOL = 40  # 1/2 px = 80px: how far a box may exceed the stroke's x span
Box = list[list[float]]  # a quadrilateral's four corners, page pixels

SCALE = 2  # work at half resolution (2px geometry precision)
INK_DELTA = 25  # grey levels below the local paper level = ink
STREAK_TALL = 40  # 1/2 px: "long and thin" thresholds for artifacts
STREAK_WIDE = 60
SHAPE_MIN_AREA = 60  # 1/2 px²: smaller components are specks
PITCH_FALLBACK = 58.0  # full-res px between lines, when the page gives no better
SEED_GAP, REFIT_TOL = 8, 18
CAP = 0.8  # × pitch: a box never exceeds this above/below its baseline
JOIN_GAP = 60  # 1/2 px = 120px: the x gap that ends a line-run
TOL = 45  # 1/2 px = 90px: how far a box may exceed the stroke's x span
WORD_TOUCH = 8  # 1/2 px = 16px: how close a stroke must pass to cover a word


def ink_mask(page: Image.Image) -> np.ndarray:
    """1 where a pixel is darker than its local paper level (median-filtered)."""
    g = np.asarray(page.convert("L").resize((page.width // SCALE, page.height // SCALE))).astype(int)
    bg = np.asarray(Image.fromarray(g.astype(np.uint8)).filter(ImageFilter.MedianFilter(17))).astype(int)
    return (bg - g) > INK_DELTA


def thin_artifact(shape: dict) -> bool:
    """A long thin ink structure is a scan streak or a rule/underline, not writing.

    Applied twice: once to the raw components (a streak welds every line it
    touches into one shape — the worst failure this pipeline has had) and again
    after the line-split, which can free a sliver that was welded to a word.
    """
    w = shape["x1"] - shape["x0"]
    h = shape["y1"] - shape["y0"]
    return (w > STREAK_WIDE and h <= 4) or (h > STREAK_TALL and w <= 3)


def artifacts(mask: np.ndarray) -> int:
    """Remove thin ink structures from the mask in place; returns how many."""
    labels, comps = components(mask)
    removed = 0
    for c in comps:
        if not thin_artifact(c):
            continue
        ys, xs = c["pix"]
        mask[ys.astype(int), xs.astype(int)] = False
        removed += 1
    return removed


def components(mask: np.ndarray, min_area: int = SHAPE_MIN_AREA) -> tuple[np.ndarray, list[dict]]:
    """Connected components (8-connected) with a union-find over row runs."""
    h, w = mask.shape
    parent: list[int] = []

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    rows: list[list[tuple[int, int, int]]] = []
    prev: list[tuple[int, int, int]] = []
    for y in range(h):
        row = mask[y]
        cur: list[tuple[int, int, int]] = []
        if row.any():
            d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
            for s, e in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1), strict=False):
                rid = len(parent)
                parent.append(rid)
                cur.append((int(s), int(e) - 1, rid))
            i = j = 0
            while i < len(cur) and j < len(prev):
                s, e, _ = cur[i]
                ps, pe, _ = prev[j]
                if e < ps:
                    i += 1
                elif pe < s:
                    j += 1
                else:
                    union(cur[i][2], prev[j][2])
                    if e < pe:
                        i += 1
                    else:
                        j += 1
        rows.append(cur)
        prev = cur
    labels = np.zeros((h, w), dtype=np.int32)
    for y, cur in enumerate(rows):
        for s, e, rid in cur:
            labels[y, s : e + 1] = find(rid) + 1
    out: list[dict] = []
    ids, counts = np.unique(labels[labels > 0], return_counts=True)
    for cid, area in zip(ids, counts, strict=False):
        if area < min_area:
            continue
        yy, xx = np.nonzero(labels == cid)
        hist = np.bincount(yy - yy.min())
        out.append(
            {
                "id": int(cid),
                "x0": int(xx.min()),
                "y0": int(yy.min()),
                "x1": int(xx.max()),
                "y1": int(yy.max()),
                "baseline": int(np.argmax(hist)) + int(yy.min()),
                "area": int(area),
                "cx": (int(xx.min()) + int(xx.max())) / 2,
                "pix": (yy.astype(np.float32), xx.astype(np.float32)),
            }
        )
    return labels, out


SLOPE_LIMIT = 0.13  # ≈7.5°: writing on a page never slopes more than this


def fit(members: list[dict]) -> tuple[float, float]:
    """Least-squares baseline through the shapes' densest rows.

    A fit beyond SLOPE_LIMIT is not a writing slope — it is a few shapes strung
    across the page by chance — so the line falls back to its median level.
    """
    xs = np.array([m["cx"] for m in members], dtype=float)
    ys = np.array([m["baseline"] for m in members], dtype=float)
    if len(xs) >= 2 and (xs.max() - xs.min()) > 1:
        a, b = np.polyfit(xs, ys, 1)
        if abs(a) <= SLOPE_LIMIT:
            return float(a), float(b)
    return 0.0, float(np.median(ys))


def dist_to_line(px: float, py: float, line: dict) -> float:
    a, b = line["a"], line["b"]
    return abs(py - (a * px + b)) / math.sqrt(1 + a * a)


def same_line(li: dict, lj: dict, pitch: float) -> bool:
    """Are these two fits the same line of writing?

    Compared WHERE THEY OVERLAP, because a fit's slope and intercept are not
    comparable across different x ranges — two fits of one physical line, one
    from its left half and one from its right, have different coefficients and
    the same baseline. Comparing coefficients left two identical lines in the
    model (lines 33 and 34, baselines 4px apart), which split a stroke's words
    between them so no box could hold it.
    """
    xs_i = [m["cx"] for m in li["m"]]
    xs_j = [m["cx"] for m in lj["m"]]
    lo = max(min(xs_i), min(xs_j))
    hi = min(max(xs_i), max(xs_j))
    xs = [lo, (lo + hi) / 2, hi] if hi > lo else [(min(xs_i) + max(xs_i) + min(xs_j) + max(xs_j)) / 4]
    return max(abs((li["a"] * x + li["b"]) - (lj["a"] * x + lj["b"])) for x in xs) < pitch / 4


def fit_lines(shapes: list[dict], pitch: float) -> list[dict]:
    """Seed, refit, merge identical fits, and split any line covering >1 line."""
    lines = []
    for s in sorted(shapes, key=lambda s: s["baseline"]):
        if lines and s["baseline"] - lines[-1]["m"][-1]["baseline"] <= SEED_GAP:
            lines[-1]["m"].append(s)
        else:
            lines.append({"m": [s]})
    for _ in range(8):
        for ln in lines:
            ln["a"], ln["b"] = fit(ln["m"])
        merged = True
        while merged:
            merged = False
            for i in range(len(lines)):
                for j in range(i + 1, len(lines)):
                    if same_line(lines[i], lines[j], pitch):
                        lines[i]["m"] += lines[j]["m"]
                        lines[i]["a"], lines[i]["b"] = fit(lines[i]["m"])
                        lines.pop(j)
                        merged = True
                        break
                if merged:
                    break
        alloc: list[list[dict]] = [[] for _ in lines]
        orphans: list[dict] = []
        for s in shapes:
            best, bd = None, 1e9
            for i, ln in enumerate(lines):
                d = dist_to_line(s["cx"], s["baseline"], ln)
                if d < bd:
                    best, bd = i, d
            (alloc[best] if best is not None and bd <= REFIT_TOL else orphans).append(s)
        lines = [{"m": m, "a": fit(m)[0], "b": fit(m)[1]} for m in alloc if m]
        lines += [{"m": [s], "a": 0.0, "b": float(s["baseline"])} for s in orphans]
        # split a line whose members' perpendicular spread exceeds one line
        out = []
        for ln in lines:
            vs = sorted(
                dist_to_line(s["cx"], s["baseline"], ln) * (1 if s["baseline"] >= ln["a"] * s["cx"] + ln["b"] else -1)
                for s in ln["m"]
            )
            if len(vs) < 2 or vs[-1] - vs[0] <= 1.2 * pitch:
                out.append(ln)
                continue
            clusters: list[list[dict]] = []
            for s in sorted(ln["m"], key=lambda s: s["baseline"] - ln["a"] * s["cx"]):
                v = s["baseline"] - (ln["a"] * s["cx"] + ln["b"])
                if (
                    clusters
                    and abs(v - (clusters[-1][-1]["baseline"] - (ln["a"] * clusters[-1][-1]["cx"] + ln["b"])))
                    <= pitch / 2
                ):
                    clusters[-1].append(s)
                else:
                    clusters.append([s])
            for c in clusters:
                out.append({"m": c, "a": fit(c)[0], "b": fit(c)[1]})
        lines = out
    return [ln for ln in lines if ln["m"]]


def line_of_shape(shape: dict, lines: list[dict]) -> int:
    return min(range(len(lines)), key=lambda i: dist_to_line(shape["cx"], shape["baseline"], lines[i]))


def split_shapes(shapes: list[dict], lines: list[dict], pitch: float) -> list[dict]:
    """Every shape belongs to one line; a shape spanning two lines is split.

    This is the fix for ink welding two lines together (a descender touching the
    next line's ascender): each ink ROW is assigned to its nearest fitted line,
    and the shape breaks where that assignment changes.
    """
    out: list[dict] = []
    for s in shapes:
        ys, xs = s["pix"]
        ys = ys.astype(int)
        xs = xs.astype(int)
        per_row: dict[int, list[int]] = {}
        for y, x in zip(ys, xs, strict=False):
            per_row.setdefault(y, []).append(x)
        segments: list[list[int]] = []
        for y in sorted(per_row):
            xc = sum(per_row[y]) / len(per_row[y])
            li = min(range(len(lines)), key=lambda i: dist_to_line(xc, y, lines[i]))
            if segments and segments[-1][0] == li and y - segments[-1][2] <= 2:
                segments[-1][2] = y
            else:
                segments.append([li, y, y])
        if len(segments) == 1:
            out.append({**s, "line": segments[0][0]})
            continue
        for li, y0, y1 in segments:
            sel = [(y, x) for y, x in zip(ys, xs, strict=False) if y0 <= y <= y1]
            if len(sel) < SHAPE_MIN_AREA // 2:
                continue
            ny = np.array([p[0] for p in sel])
            nx = np.array([p[1] for p in sel])
            hist: dict[int, int] = {}
            for y in ny:
                hist[y] = hist.get(y, 0) + 1
            out.append(
                {
                    "id": f"{s['id']}_{y0}",
                    "x0": int(nx.min()),
                    "y0": int(ny.min()),
                    "x1": int(nx.max()),
                    "y1": int(ny.max()),
                    "baseline": max(hist, key=lambda y: hist[y]),
                    "area": len(sel),
                    "cx": (int(nx.min()) + int(nx.max())) / 2,
                    "pix": (ny.astype(np.float32), nx.astype(np.float32)),
                    "line": li,
                }
            )
    return out


def frame(line: dict, shapes: list[dict]) -> tuple[float, float, float, float, float, float]:
    a = line["a"]
    x_ref = shapes[0]["cx"] if shapes else 0.0
    y_ref = a * x_ref + line["b"]
    n = math.sqrt(1 + a * a)
    return x_ref, y_ref, 1 / n, a / n, -a / n, 1 / n


def project(line: dict, shapes: list[dict], w: dict) -> tuple[np.ndarray, np.ndarray]:
    x_ref, y_ref, ux, uy, nx, ny = frame(line, shapes)
    yy, xx = w["pix"]
    return (xx - x_ref) * ux + (yy - y_ref) * uy, (xx - x_ref) * nx + (yy - y_ref) * ny


def box_from(line: dict, shapes: list[dict], u0: float, u1: float, v0: float, v1: float) -> Box:
    x_ref, y_ref, ux, uy, nx, ny = frame(line, shapes)
    return [
        [(x_ref + u * ux + v * nx) * SCALE, (y_ref + u * uy + v * ny) * SCALE]
        for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))
    ]


def detector_boxes(line: dict, lines: list[dict], pitch: float) -> list[Box]:
    """One box per line-run: the line's words, split at column-sized x gaps.

    Measured alternative (2026-09-10): splitting relative to the line's own word
    gaps, and clipping the box at the midline to the neighbouring baseline. Both
    are in principle right — a fixed threshold cut 10 of this letter's lines, and
    a box should never contain a neighbour's baseline — but the pair regressed the
    jig (two lines ended in two boxes) and needs re-deriving the composition, so
    the plain version stands until that is done properly.
    """
    ws = sorted(line["m"], key=lambda w: w["cx"])
    if not ws:
        return []
    runs, cur, prev_u = [], [ws[0]], project(line, ws, ws[0])[0].max()
    for w in ws[1:]:
        u, _ = project(line, ws, w)
        if u.min() - prev_u > JOIN_GAP:
            runs.append(cur)
            cur = [w]
        else:
            cur.append(w)
        prev_u = max(prev_u, u.max())
    runs.append(cur)
    out: list[Box] = []
    for r in runs:
        us, vs = zip(*(project(line, r, w) for w in r), strict=False)
        u_all, v_all = np.concatenate(us), np.concatenate(vs)
        u0, u1 = float(u_all.min()), float(u_all.max())
        v0 = max(float(np.percentile(v_all, 2)), -CAP * pitch / SCALE)
        v1 = min(float(np.percentile(v_all, 98)), CAP * pitch / SCALE)
        out.append(box_from(line, r, u0, u1, v0, v1))
    return out


def covered_by(stroke: list[tuple[float, float]], shapes: list[dict]) -> list[dict]:
    return [
        w
        for w in shapes
        if any(
            w["x0"] - WORD_TOUCH <= px / SCALE <= w["x1"] + WORD_TOUCH
            and w["y0"] - WORD_TOUCH <= py / SCALE <= w["y1"] + WORD_TOUCH
            for px, py in stroke
        )
    ]


def main() -> None:
    page = Image.open(PAGE)
    strokes_raw = json.loads((TRACE / "strokes.json").read_text())["strokes"]

    mask = ink_mask(page)
    n_art = artifacts(mask)
    _, shapes = components(mask)
    # The page's line spacing, measured rather than assumed: the writing's own
    # height times the ratio between line spacing and writing height, the ratio
    # taken from the reviewer's traces when they have drawn enough of them.
    # (boxscale owns those conventions; a fixed 58px here was tuned to this scan.)
    heights = [s["y1"] - s["y0"] for s in shapes]
    unit = writing_scale(heights)
    traced_lines = (
        sorted(float(np.median([p[1] for p in s])) * page.height / SCALE for s in strokes_raw) if strokes_raw else []
    )
    ratio = line_ratio(traced_pitch(traced_lines), unit)
    pitch = unit * ratio
    lines = fit_lines(shapes, pitch)
    shapes = split_shapes(shapes, lines, pitch)
    # the split can free a rule/underline or a streak that was welded to a word, so the
    # artifact test is applied again to the shapes themselves
    before = len(shapes)
    shapes = [s for s in shapes if not thin_artifact(s)]
    n_art += before - len(shapes)
    print(
        f"pitch {pitch:.1f} (unit {unit:.1f} × ratio {ratio:.2f})  ink: {int(mask.sum())} px"
        f" · artifacts removed: {n_art} · shapes {len(shapes)} · lines {len(lines)}"
    )
    for s in shapes:
        s["line"] = line_of_shape(s, lines)
    for li, ln in enumerate(lines):  # re-attach after the split
        ln["m"] = [s for s in shapes if s["line"] == li]
    # the split and the artifact filter both change the shapes, so the line model is
    # refitted on what survives before anything is assigned to it
    lines = fit_lines(shapes, pitch)
    for s in shapes:
        s["line"] = line_of_shape(s, lines)
    for li, ln in enumerate(lines):
        ln["m"] = [s for s in shapes if s["line"] == li]
    lines = [ln for ln in lines if ln["m"]]
    for s in shapes:
        s["line"] = line_of_shape(s, lines)
    # A drawn point cannot be off the page: the app records normalized coordinates
    # and a drag outside the image can exceed [0, 1] (one stroke carried a point at
    # x=14642 on a 2544px page, which no box could cover). Clamped here as well as
    # in the app, because stored marks outlive the app that made them.
    strokes = [
        [(min(max(x, 0.0), 1.0) * page.width, min(max(y, 0.0), 1.0) * page.height) for x, y in s] for s in strokes_raw
    ]
    cov = [covered_by(s, shapes) for s in strokes]
    # A stroke is a line. Assignment is by the words it covers (the count), which
    # measured better than the fitted-baseline distance on this page: the latter
    # fixed stroke 6 (drawn between two lines) but cost three more A1 failures and
    # three A3, so it was reverted. The duplicate-line bug it exposed (lines 33 and
    # 34 share a baseline) is a separate, real defect — fixed in the line model.
    assign: list[int | None] = []
    for c in cov:
        counts: dict[int, int] = {}
        for w in c:
            counts[w["line"]] = counts.get(w["line"], 0) + 1
        assign.append(max(counts, key=lambda k: counts[k]) if counts else None)

    # a stroke IS a line: group strokes that share a line and overlap along it
    parent = list(range(len(strokes)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def xspan(i: int) -> tuple[float, float]:
        xs = [p[0] for p in strokes[i]]
        return min(xs), max(xs)

    by_line: dict[int, list[int]] = {}
    for i, li in enumerate(assign):
        if li is not None:
            by_line.setdefault(li, []).append(i)
    for members in by_line.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                (p0, p1), (q0, q1) = xspan(members[i]), xspan(members[j])
                if min(p1, q1) - max(p0, q0) > 0.5 * min(p1 - p0, q1 - q0):
                    ra, rb = find(members[i]), find(members[j])
                    if ra != rb:
                        parent[rb] = ra
    groups: dict[int, list[int]] = {}
    for i in range(len(strokes)):
        groups.setdefault(find(i), []).append(i)

    trace_boxes: list[tuple[int, list[list[float]]]] = []
    for _, members in sorted(
        groups.items(),
        key=lambda kv: (
            min(assign[i] for i in kv[1] if assign[i] is not None) if any(assign[i] is not None for i in kv[1]) else 0
        ),
    ):
        li = next((assign[i] for i in members if assign[i] is not None), None)
        if li is None:
            continue
        lines[li]
        ws = [w for i in members for w in cov[i] if w["line"] == li]
        sm = [(p[0] / SCALE, p[1] / SCALE) for i in members for p in strokes[i]]
        sx0, sx1 = min(p[0] for p in sm), max(p[0] for p in sm)
        sy0, sy1 = min(p[1] for p in sm), max(p[1] for p in sm)
        wx0 = min((w["x0"] for w in ws), default=sx0)
        wx1 = max((w["x1"] for w in ws), default=sx1)
        wy0 = min((w["y0"] for w in ws), default=sy0)
        wy1 = max((w["y1"] for w in ws), default=sy1)
        x0 = min(sx0, max(wx0, sx0 - TOL))
        x1 = max(sx1, min(wx1, sx1 + TOL))
        y0, y1 = min(sy0, wy0), max(sy1, wy1)
        trace_boxes.append(
            (
                li,
                [
                    [x0 * SCALE, y0 * SCALE],
                    [x1 * SCALE, y0 * SCALE],
                    [x1 * SCALE, y1 * SCALE],
                    [x0 * SCALE, y1 * SCALE],
                ],
            )
        )

    # compose: the detector boxes the page; a trace replaces the span it defines
    def u_range(poly: Box, line: dict) -> tuple[float, float]:
        x_ref, y_ref, ux, uy, _, _ = frame(line, line["m"])
        us = [((px / SCALE - x_ref) * ux + (py / SCALE - y_ref) * uy) for px, py in poly]
        return min(us), max(us)

    final = []
    for li, ln in enumerate(lines):
        traced = sorted(u_range(b, ln) for box_line, b in trace_boxes if box_line == li)
        for poly in detector_boxes(ln, lines, pitch):
            x_ref, y_ref, ux, uy, nx, ny = frame(ln, ln["m"])
            us = [((px / SCALE - x_ref) * ux + (py / SCALE - y_ref) * uy) for px, py in poly]
            vs = [((px / SCALE - x_ref) * nx + (py / SCALE - y_ref) * ny) for px, py in poly]
            spans = [(min(us), max(us))]
            for t0, t1 in traced:
                nxt = []
                for s0, s1 in spans:
                    if t1 <= s0 or t0 >= s1:
                        nxt.append((s0, s1))
                    else:
                        if s0 < t0:
                            nxt.append((s0, t0))
                        if t1 < s1:
                            nxt.append((t1, s1))
                spans = nxt
            for s0, s1 in spans:
                if (s1 - s0) * SCALE > 20:
                    final.append(box_from(ln, ln["m"], s0, s1, min(vs), max(vs)))
    final += [b for _, b in trace_boxes]

    TRACE.mkdir(exist_ok=True)
    with open(TRACE / "boxes.json", "w") as handle:
        json.dump({"page": {"width": page.width, "height": page.height}, "boxes": final}, handle, indent=1)
    with open(TRACE / "words.json", "w") as handle:
        json.dump(
            {
                "words": [
                    {
                        "x0": s["x0"] * SCALE,
                        "y0": s["y0"] * SCALE,
                        "x1": s["x1"] * SCALE,
                        "y1": s["y1"] * SCALE,
                        "line": s["line"],
                    }
                    for s in shapes
                ]
            },
            handle,
        )
    print(f"boxes: {len(final)} ({len(trace_boxes)} from strokes, {len(final) - len(trace_boxes)} from the detector)")


if __name__ == "__main__":
    main()
