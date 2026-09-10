"""The simple box detector: words, then lines, then boxes.

Thesis (user, 2026-09-10): grouping the words and drawing a box per row is the
whole task. The seed/refit/merge/split line machinery and the shape cutting in
boxdet are unnecessary. This module is that thesis, directly:

  1. words: ink components, minus specks and scan artifacts;
  2. membership: a word belongs to a horizontal line only if it CAN be
     horizontal writing — not much taller than the writing's own height, and
     not a streak. Vertical ink (margin notes, flourishes, welded pairs) never
     joins a line: it is not the detector's to box;
  3. lines: the members' baselines, grouped by the page's measured spacing —
     sorted, cut where the gap to the previous word exceeds half the spacing;
  4. boxes: one box per line-run, that line's ink in its own frame.

The traced lines compose exactly as in boxdet: a mark replaces the detector's
box over the span it defines. Measured against the jig it either holds — and
boxdet's machinery dies — or it loses, and this file dies instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from tools.boxdet import (
    MIN_BOX_PX,
    SCALE,
    SEED_FRACTION,
    Line,  # the line's own frame work is reused unchanged
    Mark,
    PageScale,
    artifacts,
    components,
    covered_by,
    ink_mask,
)
from tools.boxscale import line_ratio, traced_pitch, writing_scale

BATCH = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004")
PAGE = BATCH / "oriented/page-01.jpg"
TRACE = Path("/tmp/trace")

ROW_MERGE_FRACTION = 0.6  # x line spacing: medians closer than this are one row
GROUP_FRACTION = SEED_FRACTION  # a baseline gap beyond 0.38 x the writing height starts a new row


def same_row(a: Line, b: Line, scale: PageScale) -> bool:
    """Are these two rows really one row of writing?

    Compared by the MEDIAN baseline of each row's members, not by the fitted
    lines: a 3-word fragment's fit can be tilted enough that the sampled
    difference between two same-row clusters reaches 17.6px against a 16.8px
    bound and they never merge (measured on this page's middle rows). The
    medians of those same clusters are 16.5px apart, while the nearest genuinely
    different rows are 27.5px apart - so the bound sits at 0.6 x the spacing,
    clear of both.
    """
    here = float(np.median([s.baseline for s in a.shapes]))
    there = float(np.median([s.baseline for s in b.shapes]))
    return abs(here - there) < ROW_MERGE_FRACTION * scale.pitch


def member_of(shape, lines: list[Line], scale: PageScale) -> int:
    """Which row does this component belong to? The one with which its ink
    overlaps most: a component's rows counted inside each fitted row's band
    (baseline ± half the spacing). Overlap, not height, not centre-distance —
    a tall interjection inside one band joins it; a vertical flourish that
    spends its ink across many bands joins none; a marginal-note letter
    straddling two bands equally joins neither."""
    rows = shape.rows()
    best, best_share = -1, 0.0
    for index, line in enumerate(lines):
        band = (line.y_at(shape.cx) - scale.pitch / 2, line.y_at(shape.cx) + scale.pitch / 2)
        inside = sum(1 for y in rows if band[0] <= y <= band[1])
        share = inside / len(rows)
        if share > best_share:
            best, best_share = index, share
    return best if best_share > 0.5 else -1


def lines_of(words: list, scale: PageScale) -> list[Line]:
    """Seed rows by adjacency, then let the fits do the work.

    A pure walk over baselines has no threshold that survives handwriting: the
    wobble within a row (measured ~12px) bedevils any cut between that and the
    row spacing (measured ~34px). So: seed by adjacency, fit each row, assign
    every word to the NEAREST fitted row, and merge rows whose fits are the
    same line. No spread test - that was what cut real rows into phantom lines.
    """
    out: list[Line] = []
    for word in sorted(words, key=lambda s: s.baseline):
        if not out or word.baseline - out[-1].shapes[-1].baseline > GROUP_FRACTION * scale.unit:
            out.append(Line(shapes=[word]))
        else:
            out[-1].shapes.append(word)
    for _ in range(4):
        for line in out:
            line.refit()
        merged = True
        while merged:
            merged = False
            for i in range(len(out)):
                for j in range(i + 1, len(out)):
                    if same_row(out[i], out[j], scale):
                        out[i].shapes += out[j].shapes
                        out[i].refit()
                        out.pop(j)
                        merged = True
                        break
                if merged:
                    break
        target: list[list] = [[] for _ in out]
        for word in words:
            nearest = min(range(len(out)), key=lambda i: out[i].distance(word.cx, word.baseline))
            target[nearest].append(word)
        out = [Line(shapes=members) for members in target if members]
    for line in out:
        line.refit()  # the last reassign rebuilt them; fit before anyone measures
    return [line for line in out if line.shapes]


def detect(page_path: Path, trace_dir: Path) -> list[list[list[float]]]:
    """Words → lines → boxes; the strokes compose as in boxdet."""
    page = Image.open(page_path)
    strokes_raw = json.loads((trace_dir / "strokes.json").read_text())["strokes"]

    mask = ink_mask(page)
    n_art = artifacts(mask)
    shapes = components(mask)
    n_art += sum(1 for s in shapes if s.is_streak)
    shapes = [s for s in shapes if not s.is_streak]

    ratio = line_ratio(
        traced_pitch(sorted(float(np.median([p[1] for p in s])) * page.height / SCALE for s in strokes_raw)),
        writing_scale([s.height for s in shapes]),
    )
    scale = PageScale.of([s.height for s in shapes], ratio)

    lines = lines_of(shapes, scale)
    for shape in shapes:
        shape.line = member_of(shape, lines, scale)
    for index, line in enumerate(lines):
        line.shapes = [s for s in shapes if s.line == index]
    lines = [line for line in lines if line.shapes]  # a row every word abandoned is not a row
    for line in lines:
        line.refit()

    print(
        f"pitch {scale.pitch:.1f} (unit {scale.unit:.1f} × ratio {ratio:.2f})  ink: {int(mask.sum())} px"
        f" · artifacts removed: {n_art} · shapes {len(shapes)} · lines {len(lines)}"
    )

    strokes = [
        [(min(max(x, 0.0), 1.0) * page.width, min(max(y, 0.0), 1.0) * page.height) for x, y in s] for s in strokes_raw
    ]
    covered = [covered_by(stroke, [s for s in shapes if s.line >= 0], scale.touch) for stroke in strokes]
    assign: list[int | None] = []
    for words in covered:
        counts: dict[int, int] = {}
        for shape in words:
            counts[shape.line] = counts.get(shape.line, 0) + 1
        assign.append(max(counts, key=lambda k: counts[k]) if counts else None)

    parent = list(range(len(strokes)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def xspan(index: int) -> tuple[float, float]:
        xs = [p[0] for p in strokes[index]]
        return min(xs), max(xs)

    by_line: dict[int, list[int]] = {}
    for index, line_index in enumerate(assign):
        if line_index is not None:
            by_line.setdefault(line_index, []).append(index)
    for members in by_line.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                (p0, p1), (q0, q1) = xspan(members[i]), xspan(members[j])
                if min(p1, q1) - max(p0, q0) > 0.5 * min(p1 - p0, q1 - q0):
                    root_a, root_b = find(members[i]), find(members[j])
                    if root_a != root_b:
                        parent[root_b] = root_a
    groups: dict[int, list[int]] = {}
    for index in range(len(strokes)):
        groups.setdefault(find(index), []).append(index)

    marks: list[Mark] = []
    for _, members in sorted(
        groups.items(), key=lambda kv: min((assign[i] for i in kv[1] if assign[i] is not None), default=0)
    ):
        line_index = next((assign[i] for i in members if assign[i] is not None), None)
        if line_index is None:
            continue
        marks.append(
            Mark(
                strokes=[strokes[i] for i in members],
                line_index=line_index,
                covered=[w for i in members for w in covered[i] if w.line == line_index],
            )
        )
    trace_boxes: list[tuple[int, list[list[float]]]] = [(mark.line_index, mark.box(scale.stroke_tol)) for mark in marks]

    # the thesis, in the box: one box per row = the union of that row's word
    # bounds, page pixels. Nothing else: no frame, no percentile, no cap. A trace
    # replaces the box over the span it covers, so the reviewer's line and the
    # detector's box never both claim the same ink.
    final: list[list[list[float]]] = []
    for line_index, line in enumerate(lines):
        if not line.shapes:
            continue
        x0 = min(s.x0 for s in line.shapes) * SCALE
        y0 = min(s.y0 for s in line.shapes) * SCALE
        x1 = max(s.x1 for s in line.shapes) * SCALE
        y1 = max(s.y1 for s in line.shapes) * SCALE
        spans = [(x0, x1)]
        for owner, box in trace_boxes:
            if owner != line_index:
                continue
            t0 = min(p[0] for p in box)
            t1 = max(p[0] for p in box)
            remaining: list[tuple[float, float]] = []
            for s0, s1 in spans:
                if t1 <= s0 or t0 >= s1:
                    remaining.append((s0, s1))
                    continue
                if s0 < t0:
                    remaining.append((s0, t0))
                if t1 < s1:
                    remaining.append((t1, s1))
            spans = remaining
        for s0, s1 in spans:
            if s1 - s0 > MIN_BOX_PX:
                final.append([[s0, y0], [s1, y0], [s1, y1], [s0, y1]])
    # ink the rows did not claim still gets a box of its own: a component the rows
    # cannot own (a vertical flourish, a margin mark) is something the reviewer
    # must be able to see and trace, never something to drop silently.
    for shape in shapes:
        if shape.line == -1:
            final.append(
                [
                    [shape.x0 * SCALE, shape.y0 * SCALE],
                    [shape.x1 * SCALE, shape.y0 * SCALE],
                    [shape.x1 * SCALE, shape.y1 * SCALE],
                    [shape.x0 * SCALE, shape.y1 * SCALE],
                ]
            )
    final += [box for _, box in trace_boxes]

    trace_dir.mkdir(parents=True, exist_ok=True)
    with open(trace_dir / "boxes.json", "w") as handle:
        json.dump({"page": {"width": page.width, "height": page.height}, "boxes": final}, handle, indent=1)
    with open(trace_dir / "words.json", "w") as handle:
        json.dump(
            {
                "words": [
                    {"x0": s.x0 * SCALE, "y0": s.y0 * SCALE, "x1": s.x1 * SCALE, "y1": s.y1 * SCALE, "line": s.line}
                    for s in shapes
                ]
            },
            handle,
        )
    print(f"boxes: {len(final)} ({len(trace_boxes)} from strokes, {len(final) - len(trace_boxes)} from the detector)")
    return final


if __name__ == "__main__":
    detect(PAGE, TRACE)
