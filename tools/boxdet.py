"""Box detection — find every line of writing on a scan and box its ink.

The detector reads a page image, finds the ink's shapes, clusters their
baselines into lines of writing, and gives each line a box that hugs its ink at
that line's slope. Where a reviewer has traced a line, the trace defines that
line and replaces the detector's box over the span it covers.

The pipeline, and the invariant each stage holds:

    ink mask    pixels darker than the paper around them
    artifacts   long thin ink deleted: a scan line welds lines into one shape
    shapes      connected components = words (or letters, in print)
    lines       the shapes' baselines clustered and fitted, one fit per line
    assign      every shape belongs to exactly one line; a shape spanning two
                lines is cut at the row where its nearest baseline changes
    boxes       one box per line-run: that line's ink, split at column breaks
    strokes     a stroke IS a line: it names the line it was drawn along
    compose     the trace replaces the detector's box over the span it covers

Coordinates (one system, stated once):

    * geometry — Line.a/b, distances, pitches — is in WORKING pixels: the raster
      is half the page (`WORK_SCALE`), so the page is 2 x every working length;
    * `Shape.x0/y0/x1/y1/baseline/cx` are working pixels, exactly as the raster
      measured them;
    * every box that leaves this module is in PAGE pixels: `Line.box`,
      `Mark.box` and the two JSON writers are the only places the × WORK_SCALE
      conversion happens, and they are the boundary;
    * thresholds are neither: they are fractions of the page's own ruler
      (`PageScale`), evaluated in working pixels like everything else.

That boundary is why the mixed-units bug - ink measured in one system, strokes
in another, both scaled once more - can no longer hide: there is one place to
look, and the box builders are it.

The measured baseline (kept identical by this refactor, which only moved the
geometry onto `Shape` and `Line`): 38 lines and 63 boxes on page-01 with its 44
traced lines, A1 two yellow lines mis-boxed, A3 one box spanning two, A6 pass;
62 boxes with no strokes, 9 of them holding two lines' words and 11 words
missed. Run it, then the jig:

    .venv/bin/python tools/boxdet.py
    .venv/bin/python tools/boxjig.py /tmp/trace
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from tools.boxscale import line_ratio, traced_pitch, writing_scale

Box = list[list[float]]  # a quadrilateral's four corners, page pixels

BATCH = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004")
PAGE = BATCH / "oriented/page-01.jpg"
TRACE = Path("/tmp/trace")

SCALE = 2  # work at half resolution (2px geometry precision)
INK_DELTA = 25  # grey levels below the local paper level = ink
STREAK_TALL = 40  # 1/2 px: a run this tall and ≤3 wide is a scan line
STREAK_WIDE = 60  # 1/2 px: a run this wide and ≤4 tall is a rule
SHAPE_MIN_AREA = 60  # 1/2 px²: smaller components are specks
SLOPE_LIMIT = 0.13  # ≈7.5°: writing on a page never slopes more than this
SEED_FRACTION = 0.38  # × writing height: baselines this close start one line
REFIT_FRACTION = 0.86  # × writing height: how far a shape may sit from a line
SPREAD_FACTOR = 1.2  # × pitch: a line whose members spread further is two lines
MERGE_DIVISOR = 4  # pitch ÷ this: how close two fits are the same line
CLUSTER_DIVISOR = 2  # pitch ÷ this: how far a member may sit from its cluster
CAP = 0.8  # × pitch: a box never exceeds this above/below its baseline
JOIN_FRACTION = 1.78  # × line spacing: the x gap that ends a line-run
STROKE_FRACTION = 2.14  # × writing height: how far a mark's box may exceed its strokes
TOUCH_FRACTION = 0.38  # × writing height: how close a stroke must pass to cover a word
MIN_BOX_PX = 20  # full-res px: a leftover sliver thinner than this is noise
ROW_MERGE = 2  # 1/2 px: rows this close belong to the same piece of a cut shape


@dataclass
class Shape:
    """A connected run of ink — a word, or a letter in print."""

    x0: float
    y0: float
    x1: float
    y1: float
    baseline: float
    area: float
    cx: float
    pix: tuple[np.ndarray, np.ndarray]
    line: int = -1
    id: str = ""

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def is_streak(self) -> bool:
        """A long thin run of ink is a scan line or a rule, never writing."""
        width, height = self.x1 - self.x0, self.y1 - self.y0
        return (width > STREAK_WIDE and height <= 4) or (height > STREAK_TALL and width <= 3)

    def rows(self) -> dict[int, list[int]]:
        """The shape's ink by row — how a straddling shape is cut between lines."""
        ys, xs = self.pix
        per_row: dict[int, list[int]] = {}
        for y, x in zip(ys.astype(int), xs.astype(int), strict=False):
            per_row.setdefault(int(y), []).append(int(x))
        return per_row

    def piece(self, ink: list[tuple[int, int]], line: int, suffix: int) -> Shape:
        """The part of this shape on the given rows, as its own shape on one line."""
        ny = np.array([point[0] for point in ink], dtype=np.float32)
        nx = np.array([point[1] for point in ink], dtype=np.float32)
        histogram: dict[int, int] = {}
        for y in ny.astype(int):
            histogram[int(y)] = histogram.get(int(y), 0) + 1
        return Shape(
            x0=float(nx.min()),
            y0=float(ny.min()),
            x1=float(nx.max()),
            y1=float(ny.max()),
            baseline=float(max(histogram, key=lambda y: histogram[y])),
            area=float(len(ink)),
            cx=(float(nx.min()) + float(nx.max())) / 2,
            pix=(ny, nx),
            line=line,
            id=f"{self.id}_{suffix}",
        )


@dataclass
class Line:
    """One line of writing: the shapes on it, and the baseline fitted through them."""

    shapes: list[Shape] = field(default_factory=list)
    a: float = 0.0
    b: float = 0.0

    def y_at(self, x: float) -> float:
        return self.a * x + self.b

    def distance(self, x: float, y: float) -> float:
        """Perpendicular distance from a point to this baseline."""
        return abs(y - self.y_at(x)) / math.sqrt(1 + self.a * self.a)

    def offset(self, shape: Shape) -> float:
        """Raw vertical offset of a shape's baseline from this line's, signed."""
        return shape.baseline - self.y_at(shape.cx)

    def signed_distance(self, shape: Shape) -> float:
        """The same offset, measured perpendicular to the baseline (cosine-corrected)."""
        return self.distance(shape.cx, shape.baseline) * (1 if self.offset(shape) >= 0 else -1)

    def refit(self) -> None:
        """Fit the baseline through the shapes' densest rows, sloped like writing.

        A fit beyond SLOPE_LIMIT is not a writing slope — it is a few shapes
        strung across the page by chance — so the line falls back to its median
        level.
        """
        xs = np.array([s.cx for s in self.shapes], dtype=float)
        ys = np.array([s.baseline for s in self.shapes], dtype=float)
        if len(xs) >= 2 and (xs.max() - xs.min()) > 1:
            slope, intercept = np.polyfit(xs, ys, 1)
            if abs(slope) <= SLOPE_LIMIT:
                self.a, self.b = float(slope), float(intercept)
                return
        self.a, self.b = 0.0, float(np.median(ys))

    def matches(self, other: Line, pitch: float) -> bool:
        """Is this the same line of writing as `other`?

        Compared WHERE THEY OVERLAP: a slope and an intercept are not comparable
        across different x ranges, so two fits of one physical line — one from
        its left half, one from its right — have different coefficients and the
        same baseline. Comparing coefficients left two identical lines in the
        model, which split a reviewer's stroke between them so no box could hold
        it. When the two fits do not overlap at all, the comparison is made
        between their centres.
        """
        xs_here = [s.cx for s in self.shapes]
        xs_there = [s.cx for s in other.shapes]
        low = max(min(xs_here), min(xs_there))
        high = min(max(xs_here), max(xs_there))
        samples = (
            [low, (low + high) / 2, high]
            if high > low
            else [(min(xs_here) + max(xs_here) + min(xs_there) + max(xs_there)) / 4]
        )
        return max(abs(self.y_at(x) - other.y_at(x)) for x in samples) < pitch / MERGE_DIVISOR

    def frame(self, shapes: list[Shape]) -> tuple[float, float, float, float, float, float]:
        """The local frame used to measure boxes: origin, and the unit vectors."""
        x_ref = shapes[0].cx if shapes else 0.0
        y_ref = self.y_at(x_ref)
        norm = math.sqrt(1 + self.a * self.a)
        return x_ref, y_ref, 1 / norm, self.a / norm, -self.a / norm, 1 / norm

    def project(self, shapes: list[Shape], shape: Shape) -> tuple[np.ndarray, np.ndarray]:
        """The shape's ink in the line's own frame: along the line, and across it."""
        x_ref, y_ref, ux, uy, nx, ny = self.frame(shapes)
        ys, xs = shape.pix
        return (xs - x_ref) * ux + (ys - y_ref) * uy, (xs - x_ref) * nx + (ys - y_ref) * ny

    def box(self, shapes: list[Shape], u0: float, u1: float, v0: float, v1: float) -> Box:
        """A box [u0, u1] along the line by [v0, v1] across it, in page pixels."""
        x_ref, y_ref, ux, uy, nx, ny = self.frame(shapes)
        return [
            [(x_ref + u * ux + v * nx) * SCALE, (y_ref + u * uy + v * ny) * SCALE]
            for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))
        ]

    def u_span(self, shapes: list[Shape], poly: Box) -> tuple[float, float]:
        """Where a box lies along this line, in the line's own units."""
        x_ref, y_ref, ux, uy, _, _ = self.frame(shapes)
        us = [((px / SCALE - x_ref) * ux + (py / SCALE - y_ref) * uy) for px, py in poly]
        return min(us), max(us)

    def boxes(self, scale: PageScale) -> list[Box]:
        """The line's ink as one or more boxes, split at column-sized x gaps.

        Measured alternative (2026-09-10): splitting relative to the line's own
        word gaps, and clipping each box at the midline to the neighbouring
        baseline. Both are in principle right — a fixed threshold cut 10 of this
        letter's lines, and a box should never contain a neighbour's baseline —
        but the pair regressed the jig (two lines ended in two boxes) and needs
        the composition re-derived, so the plain version stands.
        """
        pitch = scale.pitch
        shapes = sorted(self.shapes, key=lambda s: s.cx)
        if not shapes:
            return []
        runs: list[list[Shape]] = []
        current = [shapes[0]]
        edge = self.project(shapes, shapes[0])[0].max()
        for shape in shapes[1:]:
            along, _ = self.project(shapes, shape)
            if along.min() - edge > scale.join_gap:
                runs.append(current)
                current = [shape]
            else:
                current.append(shape)
            edge = max(edge, along.max())
        runs.append(current)
        out: list[Box] = []
        for run in runs:
            us, vs = zip(*(self.project(run, shape) for shape in run), strict=False)
            along, across = np.concatenate(us), np.concatenate(vs)
            out.append(
                self.box(
                    run,
                    float(along.min()),
                    float(along.max()),
                    max(float(np.percentile(across, 2)), -CAP * pitch / SCALE),
                    min(float(np.percentile(across, 98)), CAP * pitch / SCALE),
                )
            )
        return out


@dataclass
class Mark:
    """A line the reviewer traced: the strokes drawn along it, and the box they define.

    A mark IS a line — the reviewer's statement about where a line of writing is.
    Its box is the extent of what was drawn, extended to the shapes the strokes
    pass over, but by no more than TOL beyond the strokes at either end, so a
    trace cannot silently claim half the page.
    """

    strokes: list[list[tuple[float, float]]]
    line_index: int
    covered: list[Shape]

    def box(self, stroke_tol: float) -> Box:
        points = [(p[0] / SCALE, p[1] / SCALE) for stroke in self.strokes for p in stroke]
        sx0, sx1 = min(p[0] for p in points), max(p[0] for p in points)
        sy0, sy1 = min(p[1] for p in points), max(p[1] for p in points)
        x0 = min(sx0, max(min((w.x0 for w in self.covered), default=sx0), sx0 - stroke_tol))
        x1 = max(sx1, min(max((w.x1 for w in self.covered), default=sx1), sx1 + stroke_tol))
        y0 = min(sy0, min((w.y0 for w in self.covered), default=sy0))
        y1 = max(sy1, max((w.y1 for w in self.covered), default=sy1))
        return [[x0 * SCALE, y0 * SCALE], [x1 * SCALE, y0 * SCALE], [x1 * SCALE, y1 * SCALE], [x0 * SCALE, y1 * SCALE]]


@dataclass
class PageScale:
    """The page's own ruler: what one length means here.

    Every distance the detector compares is a multiple of the writing's height
    (the median height of its ink shapes) or of the line spacing that height
    implies. A page at another resolution, in another hand, or in print needs no
    edits - the multiples are typography, the height is measured.
    """

    unit: float  # the writing's height, in working pixels
    pitch: float  # the line spacing, in working pixels

    @classmethod
    def of(cls, heights: list[float], ratio: float) -> PageScale:
        unit = writing_scale(heights)
        return cls(unit=unit, pitch=unit * ratio)

    @property
    def seed_gap(self) -> float:
        return SEED_FRACTION * self.unit

    @property
    def refit_tol(self) -> float:
        return REFIT_FRACTION * self.unit

    @property
    def join_gap(self) -> float:
        return JOIN_FRACTION * self.pitch

    @property
    def stroke_tol(self) -> float:
        return STROKE_FRACTION * self.unit

    @property
    def touch(self) -> float:
        return TOUCH_FRACTION * self.unit


def ink_mask(page: Image.Image) -> np.ndarray:
    """1 where a pixel is darker than the paper around it."""
    g = np.asarray(page.convert("L").resize((page.width // SCALE, page.height // SCALE))).astype(int)
    bg = np.asarray(Image.fromarray(g.astype(np.uint8)).filter(ImageFilter.MedianFilter(17))).astype(int)
    return (bg - g) > INK_DELTA


def components(mask: np.ndarray, min_area: int = SHAPE_MIN_AREA) -> list[Shape]:
    """Connected components (8-connected) via a union-find over row runs."""
    height, width = mask.shape
    parent: list[int] = []

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    rows: list[list[tuple[int, int, int]]] = []
    previous: list[tuple[int, int, int]] = []
    for y in range(height):
        row = mask[y]
        current: list[tuple[int, int, int]] = []
        if row.any():
            edges = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
            for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=False):
                parent.append(len(parent))
                current.append((int(start), int(end) - 1, len(parent) - 1))
            i = j = 0
            while i < len(current) and j < len(previous):
                s, e, _ = current[i]
                ps, pe, _ = previous[j]
                if e < ps:
                    i += 1
                elif pe < s:
                    j += 1
                else:
                    union(current[i][2], previous[j][2])
                    i, j = (i + 1, j) if e < pe else (i, j + 1)
        rows.append(current)
        previous = current
    labels = np.zeros((height, width), dtype=np.int32)
    for y, current in enumerate(rows):
        for start, end, rid in current:
            labels[y, start : end + 1] = find(rid) + 1
    out: list[Shape] = []
    ids, counts = np.unique(labels[labels > 0], return_counts=True)
    for component, area in zip(ids, counts, strict=False):
        if area < min_area:
            continue
        ys, xs = np.nonzero(labels == component)
        histogram = np.bincount(ys - ys.min())
        out.append(
            Shape(
                x0=float(xs.min()),
                y0=float(ys.min()),
                x1=float(xs.max()),
                y1=float(ys.max()),
                baseline=float(int(np.argmax(histogram)) + int(ys.min())),
                area=float(area),
                cx=(int(xs.min()) + int(xs.max())) / 2,
                pix=(ys.astype(np.float32), xs.astype(np.float32)),
                id=str(int(component)),
            )
        )
    return out


def artifacts(mask: np.ndarray) -> int:
    """Delete long thin ink from the raster; a scan line welds lines together."""
    removed = 0
    for shape in components(mask):
        if not shape.is_streak:
            continue
        ys, xs = shape.pix
        mask[ys.astype(int), xs.astype(int)] = False
        removed += 1
    return removed


def fit_lines(shapes: list[Shape], scale: PageScale) -> list[Line]:
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
        target: list[list[Shape]] = [[] for _ in lines]
        orphans: list[Shape] = []
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
            clusters: list[list[Shape]] = []
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


def line_of_shape(shape: Shape, lines: list[Line]) -> int:
    return min(range(len(lines)), key=lambda i: lines[i].distance(shape.cx, shape.baseline))


def split_shapes(shapes: list[Shape], lines: list[Line]) -> list[Shape]:
    """Every shape belongs to one line; a shape spanning two lines is split.

    The fix for ink welding two lines together (a descender touching the next
    line's ascender): each ink ROW is assigned to its nearest fitted line, and
    the shape breaks where that assignment changes.
    """
    out: list[Shape] = []
    for shape in shapes:
        per_row = shape.rows()
        segments: list[list[int]] = []
        for y in sorted(per_row):
            xc = sum(per_row[y]) / len(per_row[y])
            nearest = min(range(len(lines)), key=lambda i: lines[i].distance(xc, y))
            if segments and segments[-1][0] == nearest and y - segments[-1][2] <= ROW_MERGE:
                segments[-1][2] = y
            else:
                segments.append([nearest, y, y])
        if len(segments) == 1:
            shape.line = segments[0][0]
            out.append(shape)
            continue
        ys, xs = shape.pix
        for line_index, y0, y1 in segments:
            ink = [(y, x) for y, x in zip(ys.astype(int), xs.astype(int), strict=False) if y0 <= y <= y1]
            if len(ink) < SHAPE_MIN_AREA // 2:
                continue
            out.append(shape.piece(ink, line_index, y0))
    return out


def covered_by(stroke: list[tuple[float, float]], shapes: list[Shape], touch: float) -> list[Shape]:
    """The shapes a traced line passes over — how a stroke names its line."""
    return [
        shape
        for shape in shapes
        if any(
            shape.x0 - touch <= px / SCALE <= shape.x1 + touch and shape.y0 - touch <= py / SCALE <= shape.y1 + touch
            for px, py in stroke
        )
    ]


def detect(page_path: Path, trace_dir: Path) -> list[Box]:
    """Box every line on the page; write boxes.json and words.json into trace_dir.

    The page and the trace directory are arguments, so the detector can run on
    any page (and be tested on a synthetic one) rather than only on the batch it
    was developed against.
    """
    page = Image.open(page_path)
    strokes_raw = json.loads((trace_dir / "strokes.json").read_text())["strokes"]

    mask = ink_mask(page)
    n_art = artifacts(mask)
    shapes = components(mask)
    # The page's line spacing, measured rather than assumed: the writing's own
    # height times the ratio between line spacing and writing height, the ratio
    # taken from the reviewer's traces when they have drawn enough of them.
    traced_lines = sorted(float(np.median([p[1] for p in s])) * page.height / SCALE for s in strokes_raw)
    ratio = line_ratio(traced_pitch(traced_lines), writing_scale([s.height for s in shapes]))
    scale = PageScale.of([s.height for s in shapes], ratio)
    lines = fit_lines(shapes, scale)
    shapes = split_shapes(shapes, lines)
    # the split can free a rule/underline or a streak welded to a word, so the test
    # is applied again to the shapes themselves
    before = len(shapes)
    shapes = [s for s in shapes if not s.is_streak]
    n_art += before - len(shapes)
    print(
        f"pitch {scale.pitch:.1f} (unit {scale.unit:.1f} × ratio {ratio:.2f})  ink: {int(mask.sum())} px"
        f" · artifacts removed: {n_art} · shapes {len(shapes)} · lines {len(lines)}"
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
                    {"x0": s.x0 * SCALE, "y0": s.y0 * SCALE, "x1": s.x1 * SCALE, "y1": s.y1 * SCALE, "line": s.line}
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
    detect(args.page, args.trace_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
