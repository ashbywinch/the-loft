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
from tools.mark import SCALE, SHAPE_MIN_AREA, Ink, Mark, find_marks
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


class LineFitter:
    """The page's lines of writing, fitted to its marks.

    Seeding compares each baseline to the last shape of the line before it (the
    sorted order makes that the nearest), so a line grows by adjacency and never
    by a growing centre — which is what walks a line down the page. Then, for a
    fixed number of rounds: refit every line, merge the lines that are one line,
    reassign every shape to its nearest line, and split a line that covers two.
    """

    ROUNDS = 8  # refit-merge-reassign-split passes: the fit settles well inside this

    def __init__(self, scale: PageScale) -> None:
        self.scale = scale

    def fit(self, shapes: list[Mark]) -> list[Line]:
        """The lines: seeded, then settled by the rounds, empty ones dropped."""
        lines = self._seed(shapes)
        for _ in range(self.ROUNDS):
            self._refit_all(lines)
            lines = self._merged(lines)
            lines = self._reassigned(lines, shapes)
            lines = self._split_broad(lines)
        return [line for line in lines if line.shapes]

    def _seed(self, shapes: list[Mark]) -> list[Line]:
        """Lines grown by adjacency: a shape joins the line whose last member's
        baseline is within the seed gap, else it starts a new line."""
        lines: list[Line] = []
        for shape in sorted(shapes, key=lambda s: s.baseline):
            if lines and shape.baseline - lines[-1].shapes[-1].baseline <= self.scale.seed_gap:
                lines[-1].shapes.append(shape)
            else:
                lines.append(Line(shapes=[shape]))
        return lines

    def _refit_all(self, lines: list[Line]) -> None:
        for line in lines:
            line.refit()

    def _merged(self, lines: list[Line]) -> list[Line]:
        """The lines with the pairs that are the same line merged into one."""
        merged = True
        while merged:
            merged = False
            for i in range(len(lines)):
                for j in range(i + 1, len(lines)):
                    if lines[i].matches(lines[j], self.scale.pitch):
                        lines[i].shapes += lines[j].shapes
                        lines[i].refit()
                        lines.pop(j)
                        merged = True
                        break
                if merged:
                    break
        return lines

    def _reassigned(self, lines: list[Line], shapes: list[Mark]) -> list[Line]:
        """Every shape on its nearest line; one too far from any becomes a line
        of its own (an orphan is still writing)."""
        target: list[list[Mark]] = [[] for _ in lines]
        orphans: list[Mark] = []
        for shape in shapes:
            nearest = min(range(len(lines)), key=lambda i: lines[i].distance(shape.cx, shape.baseline))
            near = lines[nearest].distance(shape.cx, shape.baseline) <= self.scale.refit_tol
            (target[nearest] if near else orphans).append(shape)
        lines = [Line(shapes=members) for members in target if members]
        self._refit_all(lines)
        for shape in orphans:
            lines.append(Line(shapes=[shape], a=0.0, b=float(shape.baseline)))
        return lines

    def _split_broad(self, lines: list[Line]) -> list[Line]:
        """A line whose members spread wider than a line can is two lines: its
        members cluster by offset, and each cluster becomes its own line."""
        split: list[Line] = []
        for line in lines:
            # the spread test uses the PERPENDICULAR distance (cosine-corrected);
            # the cluster comparison below uses the raw offset. The two differ,
            # and swapping them changes which lines split.
            spread = sorted(line.signed_distance(shape) for shape in line.shapes)
            if len(spread) < 2 or spread[-1] - spread[0] <= SPREAD_FACTOR * self.scale.pitch:
                split.append(line)
                continue
            split += self._clustered_lines(line)
        return split

    def _clustered_lines(self, line: Line) -> list[Line]:
        """The line's members grouped by offset from it (baseline order), each
        group refitted as a line of its own."""
        clusters: list[list[Mark]] = []
        for shape in sorted(line.shapes, key=lambda s: s.baseline - line.y_at(s.cx)):
            last = clusters[-1][-1] if clusters else None
            if last is not None and abs(line.offset(shape) - line.offset(last)) <= self.scale.pitch / CLUSTER_DIVISOR:
                clusters[-1].append(shape)
            else:
                clusters.append([shape])
        lines: list[Line] = []
        for cluster in clusters:
            cluster_line = Line(shapes=cluster)
            cluster_line.refit()
            lines.append(cluster_line)
        return lines


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
    runs = Ink(ys, xs).longest_runs()
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
    """The writing on a page: its marks, the lines they make up, the scale they
    are measured in, and how many lines of ink (rules, underlines, freed streaks)
    were taken out of the raster on the way.

    `Writing.of` is the whole measurement, a fixpoint over MEASURE, CUT, STRIP,
    REGROUP: a line is only separable once a cut has separated it from the words
    it welds, and stripping it separates the words it was welding (user
    2026-09-16: 'the words are only joined by the underline. We shouldn't
    consider an underline as joining anything'). `cut` is the cutting of the
    marks into words, `_settled` the lines re-fitted to them."""

    marks: list[Mark]
    lines: list[Line]
    scale: PageScale
    stripped: int

    @classmethod
    def of(cls, mask: np.ndarray, traced: list[float]) -> Writing:
        """The page's writing, measured from its ink.

        The scale comes from the marks, which is why the measuring is inside the
        loop; LINE_ROUNDS bounds it."""
        marks = find_marks(mask)
        scale = _page_scale(marks, traced)
        stripped = 0
        for _ in range(LINE_ROUNDS):
            lines = LineFitter(scale).fit(marks)
            found = line_pieces(split_shapes(marks, lines, scale.unit), scale.unit)
            if not found:
                return cls(marks=marks, lines=lines, scale=scale, stripped=stripped)
            cls._strip(mask, found)
            stripped += len(found)
            marks = find_marks(mask)
            scale = _page_scale(marks, traced)
        return cls(marks=marks, lines=LineFitter(scale).fit(marks), scale=scale, stripped=stripped)

    def cut(self, unit: float) -> Writing:
        """The words: the marks cut where both sides of a boundary are
        word-shaped. A streak the cut freed is not writing either, so it leaves
        the marks and joins `stripped`."""
        cut = split_shapes(self.marks, self.lines, unit)
        words = [mark for mark in cut if not mark.is_streak]
        freed = Writing(
            marks=words,
            lines=self.lines,
            scale=self.scale,
            stripped=self.stripped + len(cut) - len(words),
        )
        return freed._settled()

    def _settled(self) -> Writing:
        """The lines fitted to these words and attached to them: the cut and the
        artifact filter both change the marks, so the model is fitted on what
        survives before anything is assigned to it."""
        self._attach(self.lines)
        lines = LineFitter(self.scale).fit(self.marks)
        self._attach(lines)
        lines = [line for line in lines if line.shapes]
        self._attach(lines)
        return Writing(marks=self.marks, lines=lines, scale=self.scale, stripped=self.stripped)

    def _attach(self, lines: list[Line]) -> None:
        """Every mark knows its line, and every line its marks."""
        for mark in self.marks:
            mark.line = line_of_shape(mark, lines)
        for index, line in enumerate(lines):
            line.shapes = [mark for mark in self.marks if mark.line == index]

    @staticmethod
    def _strip(mask: np.ndarray, lines: list[Mark]) -> None:
        """Take the lines' ink out of the raster: a line is not writing."""
        for line in lines:
            ys, xs = line.pix
            mask[ys.astype(int), xs.astype(int)] = False


class Strokes:
    """The reviewer's drawn strokes: the page's coordinates, the words each
    covers, and the line each names.

    A stroke IS a line — the reviewer drew it along one — and strokes that name
    the same line and overlap along it are one group, one traced box."""

    def __init__(self, raw: list[list[tuple[float, float]]], page_size: tuple[int, int]) -> None:
        width, height = page_size
        # A drawn point cannot be off the page: the sketch records normalized
        # coordinates and a drag outside the image can exceed [0, 1] (one stroke
        # carried a point at x=14642 on a 2544px page). Clamped here as well as in
        # the sketch, because stored marks outlive the app that made them.
        self.points = [
            [(min(max(x, 0.0), 1.0) * width, min(max(y, 0.0), 1.0) * height) for x, y in stroke] for stroke in raw
        ]

    def traces(self, shapes: list[Mark], scale: PageScale) -> list[Trace]:
        """The page's traced lines, in the order their lines sit on it."""
        covered = self._covers(shapes, scale.touch)
        naming = self._line_of(covered)
        marks: list[Trace] = []
        for members in sorted(self._groups(naming), key=lambda group: self._first_line(naming, group)):
            line_index = next((naming[i] for i in members if naming[i] is not None), None)
            if line_index is None:
                continue
            marks.append(
                Trace(
                    strokes=[self.points[i] for i in members],
                    line_index=line_index,
                    covered=[word for i in members for word in covered[i] if word.line == line_index],
                )
            )
        return marks

    def _covers(self, shapes: list[Mark], touch: float) -> list[list[Mark]]:
        """The words each stroke passes over — how a stroke names its line."""
        return [covered_by(stroke, shapes, touch) for stroke in self.points]

    def _line_of(self, covered: list[list[Mark]]) -> list[int | None]:
        """The line each stroke names: the one holding most of the words it
        covers. That count measured better here than the fitted-baseline
        distance, which fixed a stroke drawn between two lines but cost three
        more A1 failures."""
        naming: list[int | None] = []
        for words in covered:
            counts: dict[int, int] = {}
            for shape in words:
                counts[shape.line] = counts.get(shape.line, 0) + 1
            naming.append(max(counts, key=lambda key: counts[key]) if counts else None)
        return naming

    def _groups(self, naming: list[int | None]) -> list[list[int]]:
        """The strokes grouped: the ones naming one line and overlapping along it."""
        parent = list(range(len(self.points)))
        by_line: dict[int, list[int]] = {}
        for index, line_index in enumerate(naming):
            if line_index is not None:
                by_line.setdefault(line_index, []).append(index)
        for members in by_line.values():
            for left in range(len(members)):
                for right in range(left + 1, len(members)):
                    if self._overlap(members[left], members[right]):
                        self._unite(parent, members[left], members[right])
        grouped: dict[int, list[int]] = {}
        for index in range(len(self.points)):
            grouped.setdefault(self._root(parent, index), []).append(index)
        return list(grouped.values())

    def _overlap(self, one: int, other: int) -> bool:
        """Whether two strokes share enough of their run along the line."""
        (p0, p1), (q0, q1) = self._xspan(one), self._xspan(other)
        return min(p1, q1) - max(p0, q0) > 0.5 * min(p1 - p0, q1 - q0)

    def _xspan(self, index: int) -> tuple[float, float]:
        xs = [point[0] for point in self.points[index]]
        return min(xs), max(xs)

    def _first_line(self, naming: list[int | None], group: list[int]) -> int:
        """The first line a group names: its place in the page's order."""
        named: list[int] = []
        for index in group:
            line_index = naming[index]
            if line_index is not None:
                named.append(line_index)
        return min(named, default=0)

    @staticmethod
    def _root(parent: list[int], index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    @staticmethod
    def _unite(parent: list[int], one: int, other: int) -> None:
        root_one, root_other = Strokes._root(parent, one), Strokes._root(parent, other)
        if root_one != root_other:
            parent[root_other] = root_one


def compose_boxes(lines: list[Line], traced: list[tuple[int, Box]], scale: PageScale) -> list[Box]:
    """The page's boxes: the detector boxes every line, and a trace replaces the
    span it defines (the boxes it covers are cut out of its line's)."""
    final: list[Box] = []
    for line_index, line in enumerate(lines):
        spans = sorted(line.u_span(line.shapes, box) for owner, box in traced if owner == line_index)
        for poly in line.boxes(scale):
            final += _boxes_between(line, poly, spans, scale)
    return final + [box for _, box in traced]


def _boxes_between(line: Line, poly: Box, traced: list[tuple[float, float]], scale: PageScale) -> list[Box]:
    """The boxes one line's polygon gives, with the traced spans taken out."""
    x_ref, y_ref, ux, uy, nx, ny = line.frame(line.shapes)
    along = [(px / SCALE - x_ref) * ux + (py / SCALE - y_ref) * uy for px, py in poly]
    across = [(px / SCALE - x_ref) * nx + (py / SCALE - y_ref) * ny for px, py in poly]
    boxes: list[Box] = []
    for start, end in _spans_after([(min(along), max(along))], traced):
        if (end - start) * SCALE > MIN_BOX_PX:
            boxes.append(line.box(line.shapes, start, end, min(across), max(across)))
    return boxes


def _spans_after(spans: list[tuple[float, float]], traced: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The spans that remain when every traced span is taken out of them."""
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
    return spans


def write_outputs(trace_dir: Path, page: Image.Image, boxes: list[Box], shapes: list[Mark]) -> None:
    """The reading, written out: boxes.json (the page's boxes) and words.json
    (the words they were measured from), in page pixels."""
    trace_dir.mkdir(parents=True, exist_ok=True)
    with open(trace_dir / "boxes.json", "w") as handle:
        json.dump({"page": {"width": page.width, "height": page.height}, "boxes": boxes}, handle, indent=1)
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


def read_page(page_path: Path, trace_dir: Path, split: bool = True) -> list[Box]:
    """Box every line of writing on the page; write boxes.json and words.json.

    The page and the trace directory are arguments, so the detector can run on
    any page (and be tested on a synthetic one) rather than only on the batch it
    was developed against. `split=False` runs the detector without the line
    cutter — the suite's marks-only path.

    The stages, in order: the ink and its artifacts; the writing (`Writing.of`
    measures the marks, strips the rules and underlines, and fits the lines);
    the split (a cut stands only where both sides are words); the lines
    re-fitted to the words; the reviewer's strokes as traced boxes; the boxes
    composed; the reading written out.
    """
    page = Image.open(page_path)
    strokes_raw = json.loads((trace_dir / "strokes.json").read_text())["strokes"]

    mask = ink_mask(page)
    removed = artifacts(mask)
    # the reviewer's traces measure the page's line spacing, which with the
    # writing's own height gives the scale everything else is measured against
    traced = sorted(float(np.median([point[1] for point in stroke])) * page.height / SCALE for stroke in strokes_raw)
    writing = Writing.of(mask, traced)
    if split:
        writing = writing.cut(writing.scale.unit)
    shapes, lines = writing.marks, writing.lines
    print(
        f"pitch {writing.scale.pitch:.1f} (unit {writing.scale.unit:.1f})  ink: {int(mask.sum())} px"
        f" · ink removed: {removed + writing.stripped} · shapes {len(shapes)} · lines {len(lines)}"
    )

    strokes = Strokes(strokes_raw, (page.width, page.height))
    traced_boxes = [
        (trace.line_index, trace.box(writing.scale.stroke_tol)) for trace in strokes.traces(shapes, writing.scale)
    ]
    final = compose_boxes(lines, traced_boxes, writing.scale)
    write_outputs(trace_dir, page, final, shapes)
    print(f"boxes: {len(final)} ({len(traced_boxes)} from strokes, {len(final) - len(traced_boxes)} from the detector)")
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
