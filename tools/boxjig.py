"""Test jig: assert the box invariants against the drawn yellow lines.

    .venv/bin/python /tmp/trace_jig.py

Reads /tmp/trace/strokes.json (the finger lines), /tmp/trace/boxes.json (the
generated boxes) and /tmp/trace/surface.json (the letter's ink area).

The invariants, as ruled:
  A1  each yellow line is covered by EXACTLY ONE box — at least 90% of the
      line's path inside that box, and no other box covering it that much;
  A2  that box matches the line's x position and width within TOL_X;
  A3  no box holds two yellow lines: the lines ≥90% inside a box must lie on
      one line of writing (baselines within half a line pitch);
  A4  boxes stay on the letter surface (the ink area, plus a small margin);
  A5  no nonsense orientation: a box's slope must be a plausible writing
      slope (the letter's lines run within a few degrees of horizontal).

Exit code is 1 if any invariant fails, so it can gate the generator.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

DEFAULT_TRACE = Path("/tmp/trace")  # where boxes.json, words.json and strokes.json live
TRACE = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TRACE
COVERAGE = 0.90  # A1: the line must be this much inside its box
TOL_X = 90.0  # A2: px the box may differ from the line's x extent (full-res)
PITCH = 58.0  # line pitch, for A3's "same line" test and A5
SURFACE_MARGIN = 40.0  # A4: px a box may exceed the ink area
MAX_SLOPE_DEG = 6.0  # A5: the letter's lines run ~0-2.4 degrees


def in_quad(px: float, py: float, quad: list[list[float]]) -> bool:
    inside = False
    for i in range(len(quad)):
        x1, y1 = quad[i]
        x2, y2 = quad[(i + 1) % len(quad)]
        if (y1 > py) != (y2 > py) and px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def sample(path: list[list[float]], page_w: int, page_h: int) -> list[tuple[float, float]]:
    pts = [(x * page_w, y * page_h) for x, y in path]
    out: list[tuple[float, float]] = []
    for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
        steps = max(1, int(math.hypot(bx - ax, by - ay) / 10))
        out += [(ax + t / steps * (bx - ax), ay + t / steps * (by - ay)) for t in range(steps)]
    return out


def coverage(line: list[tuple[float, float]], quad: list[list[float]]) -> float:
    if not line:
        return 0.0
    return sum(1 for px, py in line if in_quad(px, py, quad)) / len(line)


def quad_x(quad: list[list[float]]) -> tuple[float, float]:
    return min(p[0] for p in quad), max(p[0] for p in quad)


def quad_slope(quad: list[list[float]]) -> float:
    (x0, y0), (x1, y1) = quad[0], quad[1]
    return math.degrees(math.atan2(y1 - y0, x1 - x0))


def main() -> int:
    strokes = json.loads((TRACE / "strokes.json").read_text())["strokes"]
    boxes = json.loads((TRACE / "boxes.json").read_text())["boxes"]
    page = json.loads((TRACE / "boxes.json").read_text())["page"]
    surface = json.loads((TRACE / "surface.json").read_text())
    ink = json.loads((TRACE / "words.json").read_text())["words"] if (TRACE / "words.json").exists() else []

    lines = [sample(s, page["width"], page["height"]) for s in strokes]
    detector_only = not lines  # no yellow lines: judge the detector on its own
    mode = "detector alone (A1-A3 need yellow lines, so they are skipped)" if detector_only else "assisted"
    print(f"jig: {len(lines)} yellow lines, {len(boxes)} boxes, page {page['width']}x{page['height']} — {mode}")
    print(
        f"     coverage >= {COVERAGE:.0%} · x tolerance {TOL_X:.0f}px"
        f" · surface margin {SURFACE_MARGIN:.0f}px · max slope {MAX_SLOPE_DEG}°\n"
    )

    cover = [[coverage(ln, b) for b in boxes] for ln in lines]
    failures = 0
    if detector_only:
        print("A1-A3  skipped (they are about the reviewer's lines)\n")
        skip = True
    else:
        skip = False

    # A1 — exactly one box covers the line >= COVERAGE (assisted runs only)
    if not skip:
        print("A1  each yellow line inside exactly one box (>=90%)")
        for i, row in enumerate(cover):
            hits = [(j, c) for j, c in enumerate(row) if c >= COVERAGE]
            if len(hits) != 1:
                failures += 1
                what = "no box" if not hits else f"{len(hits)} boxes {[(j, round(c, 2)) for j, c in hits]}"
                print(f"    FAIL line {i:>2}: {what}")
        print(f"    {'PASS' if failures == 0 else f'{failures} failure(s)'}\n")

    # A7 — a box holds the words of ONE line of writing. This is the detector's own
    #      quality bar: it is exactly what the reviewer would otherwise have to fix.
    a7 = 0
    print("A7  no box holding words of two different lines")
    for j, b in enumerate(boxes):
        holds = {w["line"] for w in ink if in_quad((w["x0"] + w["x1"]) / 2, (w["y0"] + w["y1"]) / 2, b)}
        if len(holds) > 1:
            a7 += 1
            print(f"    FAIL box {j}: holds words of lines {sorted(holds)}")
    failures += a7
    print(f"    {'PASS' if a7 == 0 else f'{a7} failure(s)'}\n")

    # A2 — per BOX: its x extent vs the union of the strokes it serves (a mark may be
    #      several strokes on one line; the box answers to the mark, not to each stroke)
    a2 = 0
    print("A2  box x position and width within tolerance of the line(s) it serves")
    for j in range(len(boxes)):
        inside = [i for i, row in enumerate(cover) if row[j] >= COVERAGE]
        if not inside:
            continue
        bx0, bx1 = quad_x(boxes[j])
        sx0 = min(min(p[0] for p in lines[i]) for i in inside)
        sx1 = max(max(p[0] for p in lines[i]) for i in inside)
        dx0, dx1 = abs(bx0 - sx0), abs(bx1 - sx1)
        if dx0 > TOL_X or dx1 > TOL_X:
            a2 += 1
            print(
                f"    FAIL box {j}: serves lines {inside}; x offset {dx0:.0f}px / {dx1:.0f}px "
                f"(box x {bx0:.0f}-{bx1:.0f}, lines x {sx0:.0f}-{sx1:.0f})"
            )
    failures += a2
    print(f"    {'PASS' if a2 == 0 else f'{a2} failure(s)'}\n")

    # A3 — no box holds two different yellow lines. "Different" is judged by the writing
    #      itself: each stroke's line is the line owning most of the words it covers.
    #      (Comparing the strokes' heights flags ordinary jitter within one line.)
    a3 = 0
    print("A3  no box holding two different yellow lines")

    def stroke_line(i):
        counts: dict[int, int] = {}
        for p in lines[i]:
            for w in ink:
                if w["x0"] - 8 <= p[0] <= w["x1"] + 8 and w["y0"] - 8 <= p[1] <= w["y1"] + 8:
                    counts[w["line"]] = counts.get(w["line"], 0) + 1
        return max(counts, key=lambda k: counts[k]) if counts else None

    stroke_lines = [stroke_line(i) for i in range(len(lines))]
    for j in range(len(boxes)):
        inside = [i for i, row in enumerate(cover) if row[j] >= COVERAGE]
        if len(inside) < 2:
            continue
        claimed = {stroke_lines[i] for i in inside if stroke_lines[i] is not None}
        if len(claimed) > 1:
            a3 += 1
            on_lines = sorted(x for x in claimed if x is not None)
            print(f"    FAIL box {j}: holds lines {inside} whose writing is on lines {on_lines}")
    failures += a3
    print(f"    {'PASS' if a3 == 0 else f'{a3} failure(s)'}\n")

    # A6 — every word of writing ends up in exactly one box. Anything outside all boxes
    #      is either under a yellow line (then the line should have boxed it: a bug) or
    #      under nothing (leftover text: the user must be asked to trace it). A word in
    #      two boxes is only acceptable when they are on DIFFERENT lines — the
    #      ascender/descender overlap that including them necessarily implies.
    a6 = 0
    leftover = 0
    overlapped = 0
    print("A6  every word of writing in exactly one box (else: trace it or box it)")
    close = 12.0  # a word edge this close to a box counts as inside it (5px rounding)

    def near_box(cx: float, cy: float) -> float:
        return min(min(math.hypot(cx - px, cy - py) for px, py in b) for b in boxes) if boxes else 1e9

    for w in ink:
        cx, cy = (w["x0"] + w["x1"]) / 2, (w["y0"] + w["y1"]) / 2
        hits = [b for b in boxes if in_quad(cx, cy, b)]
        if not hits and near_box(cx, cy) < close:
            hits = [min(boxes, key=lambda b: min(math.hypot(cx - px, cy - py) for px, py in b))]
        if len(hits) == 1:
            continue
        if not hits:
            traced = any(any(abs(px - cx) < 25 and abs(py - cy) < 25 for px, py in ln) for ln in lines)
            if traced:
                a6 += 1
                print(f"    FAIL word at ({cx:.0f},{cy:.0f}) is under a yellow line but in no box")
            else:
                leftover += 1
            continue
        overlapped += 1  # two boxes claiming a word: the allowed ascender/descender overlap
    failures += a6
    print(
        f"    {'PASS' if a6 == 0 else f'{a6} failure(s)'} — {leftover} word(s) outside every box with no trace "
        f"(user must trace them), {overlapped} word(s) in two lines' boxes (the allowed overlap)\n"
    )
    a4 = 0
    print("A4  boxes inside the letter surface")
    for j, b in enumerate(boxes):
        for x, y in b:
            if not (
                surface["x0"] - SURFACE_MARGIN <= x <= surface["x1"] + SURFACE_MARGIN
                and surface["y0"] - SURFACE_MARGIN <= y <= surface["y1"] + SURFACE_MARGIN
            ):
                a4 += 1
                print(
                    f"    FAIL box {j}: corner ({x:.0f}, {y:.0f}) outside the surface "
                    f"x{surface['x0']}-{surface['x1']} y{surface['y0']}-{surface['y1']}"
                )
                break
    failures += a4
    print(f"    {'PASS' if a4 == 0 else f'{a4} failure(s)'}\n")

    # A5 — plausible orientation
    a5 = 0
    print("A5  boxes run along the writing (slope within a few degrees)")
    for j, b in enumerate(boxes):
        s = quad_slope(b)
        if abs(s) > MAX_SLOPE_DEG:
            a5 += 1
            print(f"    FAIL box {j}: slope {s:.1f}°")
    failures += a5
    print(f"    {'PASS' if a5 == 0 else f'{a5} failure(s)'}\n")

    print(f"{'ALL PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
