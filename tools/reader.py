"""Reading a page: ink to marks to lines to boxes.

Every line of writing on a scan is found and boxed: the ink mask, its marks
(minus specks and scan artifacts), the lines of writing seeded from the marks'
baselines, and each line's ink cut into boxes at column-sized gaps. The
reviewer's traces compose on top.

Run it, then the jig:

    .venv/bin/python tools/reader.py
    .venv/bin/python tools/boxjig.py /tmp/trace
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from tools.line import Line
from tools.mark import SCALE, SHAPE_MIN_AREA, Mark, find_marks, longest_runs
from tools.pagescale import PageScale, line_ratio, traced_pitch, writing_scale
from tools.trace import Box, Trace

BATCH = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004")
PAGE = BATCH / "oriented/page-01.jpg"
TRACE = Path("/tmp/trace")
INK_DELTA = 25  # grey levels below the local paper level = ink
SPREAD_FACTOR = 1.2  # × pitch: a line whose members spread further is two lines
CLUSTER_DIVISOR = 2  # pitch ÷ this: how far a member may sit from its cluster
MIN_BOX_PX = 20  # full-res px: a leftover sliver thinner than this is noise
LINE_ROUNDS = 3  # strip-and-regroup rounds: a line can hide behind another
ROW_MERGE = 2  # 1/2 px: rows this close belong to the same piece of a cut shape
WAIST_RUN = 10  # columns: a cut row running this far is a band of ink, not a stroke tip
WAIST_OVERLAP = 0.5  # of the shorter longest-run: this much overlap is one band


def ink_mask(page: Image.Image) -> np.ndarray:
    """1 where a pixel is darker than the paper around it."""
    g = np.asarray(page.convert("L").resize((page.width // SCALE, page.height // SCALE))).astype(int)
    bg = np.asarray(Image.fromarray(g.astype(np.uint8)).filter(ImageFilter.MedianFilter(17))).astype(int)
    return (bg - g) > INK_DELTA


def artifacts(mask: np.ndarray) -> int:
    """Delete long thin ink from the raster; a scan line welds lines together."""
    removed = 0
    for shape in find_marks(mask):
        if not shape.is_streak:
            continue
        ys, xs = shape.pix
        mask[ys.astype(int), xs.astype(int)] = False
        removed += 1
    return removed


def fit_lines(shapes: list[Mark], scale: PageScale) -> list[Line]:
    """Seed, refit, merge identical fits, reassign, and split lines covering two.

    Seeding compares each baseline to the last shape of the line before it (the
    sorted order makes that the nearest), so a line grows by adjacency and never
    by a growing centre — which is what walks a line down the page.
    """
    pitch = scale.pitch
    lines: list[Line] = []
    for shape in sorted(shapes, key=lambda s: s.baseline):
        if lines and shape.baseline - lines[-1].shapes[-1].baseline <= scale.seed_gap:
            lines[-1].shapes.append(shape)
        else:
            lines.append(Line(shapes=[shape]))
    for _ in range(8):
        for line in lines:
            line.refit()
        merged = True
        while merged:
            merged = False
            for i in range(len(lines)):
                for j in range(i + 1, len(lines)):
                    if lines[i].matches(lines[j], pitch):
                        lines[i].shapes += lines[j].shapes
                        lines[i].refit()
                        lines.pop(j)
                        merged = True
                        break
                if merged:
                    break
        target: list[list[Mark]] = [[] for _ in lines]
        orphans: list[Mark] = []
        for shape in shapes:
            nearest = min(range(len(lines)), key=lambda i: lines[i].distance(shape.cx, shape.baseline))
            home = target[nearest] if lines[nearest].distance(shape.cx, shape.baseline) <= scale.refit_tol else orphans
            home.append(shape)
        lines = [Line(shapes=members) for members in target if members]
        for line in lines:
            line.refit()
        for shape in orphans:
            lines.append(Line(shapes=[shape], a=0.0, b=float(shape.baseline)))
        split: list[Line] = []
        for line in lines:
            # the spread test uses the PERPENDICULAR distance (cosine-corrected);
            # the cluster comparison below uses the raw offset. The two differ,
            # and swapping them changes which lines split.
            spread = sorted(line.signed_distance(shape) for shape in line.shapes)
            if len(spread) < 2 or spread[-1] - spread[0] <= SPREAD_FACTOR * pitch:
                split.append(line)
                continue
            clusters: list[list[Mark]] = []
            for shape in sorted(line.shapes, key=lambda s: s.baseline - line.y_at(s.cx)):
                last = clusters[-1][-1] if clusters else None
                if last is not None and abs(line.offset(shape) - line.offset(last)) <= pitch / CLUSTER_DIVISOR:
                    clusters[-1].append(shape)
                else:
                    clusters.append([shape])
            for cluster in clusters:
                cluster_line = Line(shapes=cluster)
                cluster_line.refit()
                split.append(cluster_line)
        lines = split
    return [line for line in lines if line.shapes]


def line_of_shape(shape: Mark, lines: list[Line]) -> int:
    return min(range(len(lines)), key=lambda i: lines[i].distance(shape.cx, shape.baseline))


def _longest_interval(cols: list[int]) -> tuple[int, int]:
    """The longest continuous column run on one row: the band's own span."""
    ordered = sorted(cols)
    best, start, prev = (ordered[0], ordered[0]), ordered[0], ordered[0]
    for x in ordered[1:]:
        if x == prev + 1:
            prev = x
        else:
            if prev - start > best[1] - best[0]:
                best = (start, prev)
            start, prev = x, x
    if prev - start > best[1] - best[0]:
        best = (start, prev)
    return best


def _is_waist(per_row: dict[int, list[int]], runs: dict[int, int], top: int, bottom: int) -> bool:
    """A cut between rows `top` and `bottom` is real unless it runs through a
    word's body: BOTH cut rows carry long runs AND those longest runs overlap
    each other column-wise — one continuous band of ink the fit sliced
    mid-body. A word boundary breaks at least one side: a short run, or two
    long runs that do not overlap. (User rulings 2026-09-13: the bug through
    widening ink; the eight one-word pins; the Pupil block.)"""
    if min(runs[top], runs[bottom]) < WAIST_RUN:
        return True
    top_iv = _longest_interval(per_row[top])
    bot_iv = _longest_interval(per_row[bottom])
    overlap = max(0, min(top_iv[1], bot_iv[1]) - max(top_iv[0], bot_iv[0]) + 1)
    return overlap < WAIST_OVERLAP * min(top_iv[1] - top_iv[0] + 1, bot_iv[1] - bot_iv[0] + 1)


def _rows_ink(shape: Mark, y0: int, y1: int) -> list[tuple[int, int]]:
    """The shape's ink on rows y0..y1 inclusive."""
    ys, xs = shape.pix
    return [(y, x) for y, x in zip(ys.astype(int), xs.astype(int), strict=False) if y0 <= y <= y1]


def _piece_between(shape: Mark, segment: list[int]) -> Mark:
    """The piece a segment (line, y0, y1) would become."""
    return shape.piece(_rows_ink(shape, segment[1], segment[2]), segment[0], segment[1])


def _boundary_is_a_cut(shape: Mark, above: list[int], below: list[int], unit: float) -> bool:
    """Whether the boundary between two segments is a real cut.

    It is one only when the ink either side is word-shaped — two words meeting
    — or when one side is a rule/underline, which is a line and cedes. A cut
    that would leave a word's fragment (short, narrow, or discontinuous ink)
    is refused: the two sides stay one piece."""
    upper = _piece_between(shape, above)
    lower = _piece_between(shape, below)
    if upper.classify_line([lower], [upper, lower], unit) or lower.classify_line([upper], [upper, lower], unit):
        return True
    return upper.is_word_shaped(unit) and lower.is_word_shaped(unit)


def split_shapes(shapes: list[Mark], lines: list[Line], unit: float) -> list[Mark]:
    """Every shape belongs to one line; a shape spanning two lines is split.

    Candidate boundaries come from the row fit: each ink ROW is assigned to its
    nearest fitted line, and the assignment changes are the candidate cuts. A
    candidate stands only where the ink either side is word-shaped (or is a
    rule/underline); everywhere else the rows stay one piece, so the fit's
    wobble across a single word cuts nothing.
    """
    out: list[Mark] = []
    for shape in shapes:
        segments = _candidate_segments(lines, shape)
        groups: list[list[int]] = []
        for segment in segments:
            if groups and not _boundary_is_a_cut(shape, groups[-1], segment, unit):
                groups[-1][2] = segment[2]
            else:
                groups.append(list(segment))
        if len(groups) == 1:
            shape.line = groups[0][0]
            out.append(shape)
            continue
        for line_index, y0, y1 in groups:
            ink = _rows_ink(shape, y0, y1)
            if len(ink) < SHAPE_MIN_AREA // 2:
                continue
            piece = shape.piece(ink, line_index, y0)
            if piece.is_streak:
                continue
            out.append(piece)
    return out


def _candidate_segments(lines: list[Line], shape: Mark) -> list[list[int]]:
    """The cuts a shape's row fit proposes: its ink rows grouped by which
    fitted line each row's centre is nearest, split where the assignment
    changes and the ink narrows to a waist."""
    per_row = shape.rows()
    ys, xs = shape.pix
    runs = longest_runs(ys, xs)
    segments: list[list[int]] = []
    for y in sorted(per_row):
        xc = sum(per_row[y]) / len(per_row[y])
        nearest = min(range(len(lines)), key=lambda i: lines[i].distance(xc, y))
        if segments and segments[-1][0] == nearest and y - segments[-1][2] <= ROW_MERGE:
            segments[-1][2] = y
        elif segments and segments[-1][0] != nearest and not _is_waist(per_row, runs, segments[-1][2], y):
            segments[-1] = [segments[-1][0], segments[-1][1], y]
        else:
            segments.append([nearest, y, y])
    return segments


def line_pieces(pieces: list[Mark], unit: float) -> list[Mark]:
    """The pieces that are lines, not writing: rules and underlines.

    A line is thin, long and detached (`Mark.classify_line`). Pieces carry their
    parent's id with a `_suffix`, so a piece's siblings are the writing it was
    welded to. THE ONE PLACE the line rule is applied to ink: every line found
    here has its ink taken out of the raster, whether it stood alone or was
    welded to the words it runs under."""
    by_parent: dict[str, list[Mark]] = {}
    for piece in pieces:
        by_parent.setdefault(piece.id.split("_")[0], []).append(piece)
    return [
        piece
        for piece in pieces
        if piece.classify_line([o for o in by_parent[piece.id.split("_")[0]] if o is not piece], pieces, unit)
        is not None
    ]


def covered_by(stroke: list[tuple[float, float]], shapes: list[Mark], touch: float) -> list[Mark]:
    """The shapes a traced line passes over — how a stroke names its line."""
    return [
        shape
        for shape in shapes
        if any(
            shape.x0 - touch <= px / SCALE <= shape.x1 + touch and shape.y0 - touch <= py / SCALE <= shape.y1 + touch
            for px, py in stroke
        )
    ]


def _page_scale(shapes: list[Mark], traced: list[float]) -> PageScale:
    """The page's writing scale: the marks' own heights, against the line
    spacing the reviewer's traces measured."""
    heights = [s.height for s in shapes]
    return PageScale.of(heights, line_ratio(traced_pitch(traced), writing_scale(heights)))


@dataclass(frozen=True)
class Writing:
    """What a page's writing is: the marks, the lines they make up, the scale
    they are measured in, and how many lines of ink were taken out."""

    marks: list[Mark]
    lines: list[Line]
    scale: PageScale
    stripped: int


def find_writing(mask: np.ndarray, traced: list[float]) -> Writing:
    """The page's writing: its marks and their fitted lines, with every rule and
    underline out of the raster.

    A fixpoint over MEASURE, CUT, STRIP, REGROUP, because a line is only
    separable once something has cut it apart from the words it welds — and
    stripping it separates the words it was welding (user 2026-09-16: 'the
    words are only joined by the underline. We shouldn't consider an underline
    as joining anything'). The scale comes from the marks, which is why the
    measuring is inside the loop; LINE_ROUNDS bounds it."""
    shapes = find_marks(mask)
    scale = _page_scale(shapes, traced)
    stripped = 0
    for _ in range(LINE_ROUNDS):
        lines = fit_lines(shapes, scale)
        lines_found = line_pieces(split_shapes(shapes, lines, scale.unit), scale.unit)
        if not lines_found:
            return Writing(marks=shapes, lines=lines, scale=scale, stripped=stripped)
        for line in lines_found:
            ys, xs = line.pix
            mask[ys.astype(int), xs.astype(int)] = False
        stripped += len(lines_found)
        shapes = find_marks(mask)
        scale = _page_scale(shapes, traced)
    return Writing(marks=shapes, lines=fit_lines(shapes, scale), scale=scale, stripped=stripped)


def read_page(page_path: Path, trace_dir: Path, split: bool = True) -> list[Box]:
    """Box every line on the page; write boxes.json and words.json into trace_dir.

    The page and the trace directory are arguments, so the detector can run on
    any page (and be tested on a synthetic one) rather than only on the batch it
    was developed against. `split=False` runs the detector without the line
    cutter — the suite's marks-only path.
    """
    page = Image.open(page_path)
    strokes_raw = json.loads((trace_dir / "strokes.json").read_text())["strokes"]

    mask = ink_mask(page)
    n_art = artifacts(mask)
    # the reviewer's traces measure the page's line spacing, which with the
    # writing's own height gives the scale everything else is measured against
    traced = sorted(float(np.median([p[1] for p in s])) * page.height / SCALE for s in strokes_raw)
    writing = find_writing(mask, traced)
    shapes, lines, scale, stripped = writing.marks, writing.lines, writing.scale, writing.stripped
    if split:
        shapes = split_shapes(shapes, lines, scale.unit)
    # a streak the split freed is still not writing
    before = len(shapes)
    shapes = [s for s in shapes if not s.is_streak]
    n_art += before - len(shapes)
    print(
        f"pitch {scale.pitch:.1f} (unit {scale.unit:.1f})  ink: {int(mask.sum())} px"
        f" · ink removed: {n_art + stripped} · shapes {len(shapes)} · lines {len(lines)}"
    )
    for shape in shapes:
        shape.line = line_of_shape(shape, lines)
    for index, line in enumerate(lines):  # re-attach after the split
        line.shapes = [s for s in shapes if s.line == index]
    # the split and the artifact filter both change the shapes, so the model is
    # refitted on what survives before anything is assigned to it
    lines = fit_lines(shapes, scale)
    for shape in shapes:
        shape.line = line_of_shape(shape, lines)
    for index, line in enumerate(lines):
        line.shapes = [s for s in shapes if s.line == index]
    lines = [line for line in lines if line.shapes]
    for shape in shapes:
        shape.line = line_of_shape(shape, lines)

    # A drawn point cannot be off the page: the sketch records normalized
    # coordinates and a drag outside the image can exceed [0, 1] (one stroke
    # carried a point at x=14642 on a 2544px page). Clamped here as well as in the
    # sketch, because stored marks outlive the app that made them.
    strokes = [
        [(min(max(x, 0.0), 1.0) * page.width, min(max(y, 0.0), 1.0) * page.height) for x, y in s] for s in strokes_raw
    ]
    covered = [covered_by(stroke, shapes, scale.touch) for stroke in strokes]
    # A stroke is a line. Assignment is by the words it covers (the count), which
    # measured better here than the fitted-baseline distance: the latter fixed a
    # stroke drawn between two lines but cost three more A1 failures.
    assign: list[int | None] = []
    for words in covered:
        counts: dict[int, int] = {}
        for shape in words:
            counts[shape.line] = counts.get(shape.line, 0) + 1
        assign.append(max(counts, key=lambda k: counts[k]) if counts else None)

    # a stroke IS a line: group strokes that share a line and overlap along it
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

    marks: list[Trace] = []
    for _, members in sorted(
        groups.items(), key=lambda kv: min((assign[i] for i in kv[1] if assign[i] is not None), default=0)
    ):
        line_index = next((assign[i] for i in members if assign[i] is not None), None)
        if line_index is None:
            continue
        marks.append(
            Trace(
                strokes=[strokes[i] for i in members],
                line_index=line_index,
                covered=[w for i in members for w in covered[i] if w.line == line_index],
            )
        )
    trace_boxes: list[tuple[int, Box]] = [(mark.line_index, mark.box(scale.stroke_tol)) for mark in marks]

    # compose: the detector boxes the page; a trace replaces the span it defines
    final: list[Box] = []
    for line_index, line in enumerate(lines):
        traced = sorted(line.u_span(line.shapes, box) for owner, box in trace_boxes if owner == line_index)
        for poly in line.boxes(scale):
            x_ref, y_ref, ux, uy, nx, ny = line.frame(line.shapes)
            along = [(px / SCALE - x_ref) * ux + (py / SCALE - y_ref) * uy for px, py in poly]
            across = [(px / SCALE - x_ref) * nx + (py / SCALE - y_ref) * ny for px, py in poly]
            spans = [(min(along), max(along))]
            for t0, t1 in traced:
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
                if (s1 - s0) * SCALE > MIN_BOX_PX:
                    final.append(line.box(line.shapes, s0, s1, min(across), max(across)))
    final += [box for _, box in trace_boxes]

    trace_dir.mkdir(parents=True, exist_ok=True)
    with open(trace_dir / "boxes.json", "w") as handle:
        json.dump({"page": {"width": page.width, "height": page.height}, "boxes": final}, handle, indent=1)
    with open(trace_dir / "words.json", "w") as handle:
        json.dump(
            {
                "words": [
                    {
                        "x0": s.x0 * SCALE,
                        "y0": s.y0 * SCALE,
                        "x1": s.x1 * SCALE,
                        "y1": s.y1 * SCALE,
                        "line": s.line,
                        "baseline": s.baseline * SCALE,
                        "waistline": s.waistline * SCALE,
                    }
                    for s in shapes
                ]
            },
            handle,
        )
    print(f"boxes: {len(final)} ({len(trace_boxes)} from strokes, {len(final) - len(trace_boxes)} from the detector)")
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Box every line of writing on a scanned page.")
    parser.add_argument("--page", type=Path, default=PAGE, help="the page image")
    parser.add_argument(
        "--trace-dir", type=Path, default=TRACE, help="where strokes.json lives and boxes.json is written"
    )
    args = parser.parse_args(argv)
    read_page(args.page, args.trace_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
