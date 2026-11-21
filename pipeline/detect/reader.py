"""Reading a page: ink to marks to lines to boxes.

Every line of writing on a scan is found and boxed: the ink mask, its marks
(minus specks and scan artifacts), the lines of writing seeded from the marks'
baselines, and each line's ink cut into boxes at column-sized gaps. The
reviewer's traces compose on top.

Run it, then check the rows the reading makes: the invariants are
`Rows.validate` (`pipeline/rows/rows.py`), the same check the correction
runs on the reviewer's drawn lines:

    .venv/bin/python tools/reader.py   # the findings are in the terminal + /tmp/trace
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from document.boxes import Boxes
from document.page_size import PageSize
from document.point import Point
from document.span import Span
from document.trace import Box, Trace
from document.word import Word, WordMeasurements
from document.words import Words
from pipeline.detect.covered_words import CoveredWords
from pipeline.detect.line import Line
from pipeline.detect.mark import Components, Mark, find_marks
from pipeline.detect.row_fit import RowFit, nearest_line
from pipeline.detect.ruler import Ruler
from pipeline.detect.stroke import Stroke
from pipeline.detect.stroke_group import StrokeGroup
from pipeline.detect.traced_box import TracedBox
from pipeline.detect.u_span import USpan
from pipeline.detect.word_cut import WordCut


def ink_mask(page: Image.Image) -> np.ndarray:
    """1 where a pixel is darker than the paper around it."""
    g = np.asarray(page.convert("L").resize((page.width // Components.SCALE, page.height // Components.SCALE))).astype(
        int
    )
    bg = np.asarray(Image.fromarray(g.astype(np.uint8)).filter(ImageFilter.MedianFilter(17))).astype(int)
    return (bg - g) > Reading.INK_DELTA


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

    SPREAD_FACTOR = 1.2  # × pitch: a line whose members spread further is two lines
    CLUSTER_DIVISOR = 2  # pitch ÷ this: how far a member may sit from its cluster

    ROUNDS = 8  # refit-merge-reassign-split passes: the fit settles well inside this

    def __init__(self, scale: Ruler) -> None:
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
            self._join_or_start(lines, shape)
        return lines

    def _join_or_start(self, lines: list[Line], shape: Mark) -> None:
        """The shape joins the line whose last member's baseline is within the
        seed gap, else it starts a new line."""
        if lines and shape.baseline - lines[-1].shapes[-1].baseline <= self.scale.seed_gap:
            lines[-1].shapes.append(shape)
        else:
            lines.append(Line(shapes=[shape]))

    @staticmethod
    def _refit_all(lines: list[Line]) -> None:
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
        lines += [Line(shapes=[shape], a=0.0, b=float(shape.baseline)) for shape in orphans]
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
            if len(spread) < 2 or spread[-1] - spread[0] <= LineFitter.SPREAD_FACTOR * self.scale.pitch:
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
            if (
                last is not None
                and abs(line.offset(shape) - line.offset(last)) <= self.scale.pitch / LineFitter.CLUSTER_DIVISOR
            ):
                clusters[-1].append(shape)
            else:
                clusters.append([shape])
        lines: list[Line] = []
        for cluster in clusters:
            cluster_line = Line(shapes=cluster)
            cluster_line.refit()
            lines.append(cluster_line)
        return lines


def split_shapes(shapes: list[Mark], lines: list[Line], unit: float) -> list[Mark]:
    """The words these marks make at this scale, exposed for the tests.

    The pipeline itself cuts through the Writing's `WordCut`; a bare
    shapes/lines/unit tuple is the cut's own three inputs — the marks, the
    fitted lines and the ruler they are measured in."""
    scale = Ruler(unit=unit, pitch=Ruler.LINE_RATIO_DEFAULT * unit)
    return WordCut(shapes, lines, scale).words()


def line_pieces(pieces: list[Mark], unit: float) -> list[Mark]:
    """The pieces that are lines, not writing: rules and underlines.

    A line is thin, long and detached (`Mark.classify_line`). Pieces carry their
    parent's id with a `_suffix`, so a piece's siblings are the writing it was
    welded to. THE ONE PLACE the line rule is applied to ink: every line found
    here has its ink taken out of the raster, whether it stood alone or was
    welded to the words it runs under."""
    by_parent: dict[str, list[Mark]] = {
        parent: [piece for piece in pieces if piece.id.split("_")[0] == parent]
        for parent in {piece.id.split("_")[0] for piece in pieces}
    }
    carved: list[Mark] = []
    for piece in list(pieces):
        band = piece.line_band()
        if band is not None:
            band.id = f"{piece.id}_line"
            family = [o for o in by_parent[piece.id.split("_")[0]] if o is not piece]
            if band.classify_line(family, pieces, unit) is not None:
                carved.append(band)  # the existing line rule says it is a line: strip it
    return carved + [
        piece
        for piece in pieces
        if piece.classify_line([o for o in by_parent[piece.id.split("_")[0]] if o is not piece], pieces, unit)
        is not None
    ]


def covered_by(stroke: list[Point], shapes: list[Mark], touch: float) -> list[Mark]:
    """The shapes a traced line passes over — how a stroke names its line."""
    return [
        shape
        for shape in shapes
        if any(
            shape.x0 - touch <= point.x / Components.SCALE <= shape.x1 + touch
            and shape.y0 - touch <= point.y / Components.SCALE <= shape.y1 + touch
            for point in stroke
        )
    ]


def _page_scale(shapes: list[Mark], traced: list[float]) -> Ruler:
    """The page's ruler: the marks' own heights, the pitch refined by the line
    spacing the reviewer's traces measured."""
    return Ruler.from_marks(shapes, traced)


@dataclass(frozen=True)
class Writing:
    """The writing on a page: its marks, the lines they make up, the scale they
    are measured in, and how many lines of ink (rules, underlines, freed streaks)
    were taken out of the raster on the way.

    `Writing.of` is the whole measurement, a fixpoint over MEASURE, CUT, STRIP,
    REGROUP: a line is only separable once a cut has separated it from the words
    it welds, and stripping it separates the words it was welding (user:
    'the words are only joined by the underline. We shouldn't consider an
    underline as joining anything'). `cut` hands the marks to the writing's
    `WordCut` and keeps what it returns, `fit` reads the rows against the
    lines (`RowFit`), and `_settled` re-fits the lines to the words."""

    LINE_ROUNDS = 3  # strip-and-regroup rounds: a line can hide behind another
    VERTICAL_RULE_MIN_HEIGHT = 100  # 1/2 px: a vertical rule runs the height of several lines

    marks: list[Mark]
    lines: list[Line]
    scale: Ruler
    stripped: int

    @classmethod
    def of(cls, mask: np.ndarray, traced: list[float]) -> Writing:
        """The page's writing, measured from its ink.

        The scale comes from the marks, which is why the measuring is inside the
        loop; Writing.LINE_ROUNDS bounds it."""
        cls._strip_vertical_rules(mask)
        marks = find_marks(mask)
        scale = _page_scale(marks, traced)
        stripped = 0
        for _ in range(Writing.LINE_ROUNDS):
            lines = LineFitter(scale).fit(marks)
            found = line_pieces(split_shapes(marks, lines, scale.unit), scale.unit)
            if not found:
                return cls(marks=marks, lines=lines, scale=scale, stripped=stripped)
            cls._strip(mask, found)
            stripped += len(found)
            marks = find_marks(mask)
            scale = _page_scale(marks, traced)
        return cls(marks=marks, lines=LineFitter(scale).fit(marks), scale=scale, stripped=stripped)

    def fit(self) -> RowFit:
        """This writing's rows, read against its lines — where the cut looks."""
        return RowFit(self.lines)

    def cut(self, unit: float) -> Writing:
        """The words: the marks cut where both sides of a boundary are
        word-shaped. A streak the cut freed is not writing either, so it leaves
        the marks and joins `stripped`."""
        cut = WordCut(self.marks, self.lines, self.scale).words()
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
        """Every mark knows its line, and every line its marks.

        The indices are of THIS list — the lines the writing keeps. Numbering
        the marks against `self.lines` while indexing the passed list left
        marks pointing at dropped lines (page-01: 39 rows, 41 word-lines)."""
        for mark in self.marks:
            mark.line = nearest_line(mark, lines)
        for index, line in enumerate(lines):
            line.shapes = [mark for mark in self.marks if mark.line == index]

    @staticmethod
    def _strip_vertical_rules(mask: np.ndarray) -> None:
        """Take the vertical rules' ink out of the raster; a rule is not writing.

        A vertical rule is the one column of ink that runs continuously for the
        height of several lines. On this page exactly one column does — the 2px
        form rule at x2008 whose long run welds the crossed-out rows into the
        fake "square" (user: 'the weird vertical rule that we don't
        [want]'). Letters' strokes never run that far continuously, so the
        floor is safe. The rule's run, not the whole column, is removed: the
        column's other ink is writing that merely crosses the rule."""
        for x in range(mask.shape[1]):
            ys = np.flatnonzero(mask[:, x])
            if len(ys) == 0:
                continue
            run = 1
            run_start = ys[0]
            longest = run_start
            longest_run = 1
            for above, below in zip(ys, ys[1:], strict=False):
                if below == above + 1:
                    run += 1
                    if run > longest_run:
                        longest_run = run
                        longest = below - run + 1
                else:
                    run = 1
            if longest_run >= Writing.VERTICAL_RULE_MIN_HEIGHT:
                mask[longest : longest + longest_run, x] = False

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

    def __init__(self, raw: list[Stroke], page_size: PageSize) -> None:
        width, height = page_size.width, page_size.height
        # A drawn point cannot be off the page: the sketch records normalized
        # coordinates and a drag outside the image can exceed [0, 1] (one stroke
        # carried a point at x=14642 on a 2544px page). Clamped here as well as in
        # the sketch, because stored marks outlive the app that made them.
        self.strokes = [
            Stroke(
                [
                    Point(min(max(point.x, 0.0), 1.0) * width, min(max(point.y, 0.0), 1.0) * height)
                    for point in stroke.points
                ]
            )
            for stroke in raw
        ]

    def traces(self, shapes: list[Mark], scale: Ruler) -> list[Trace]:
        """The page's traced lines, in the order their lines sit on it."""
        covered = self._covers(shapes, scale.touch)
        naming = self._line_of(covered)
        marks: list[Trace] = []
        for group in sorted(self._groups(naming), key=lambda g: self._first_line(naming, g)):
            line_index = next((naming[i] for i in group.members if naming[i] is not None), None)
            if line_index is None:
                continue
            marks.append(
                Trace(
                    strokes=[self.strokes[i].points for i in group.members],
                    line_index=line_index,
                    covered=[word for i in group.members for word in covered[i].words if word.line == line_index],
                )
            )
        return marks

    def _covers(self, shapes: list[Mark], touch: float) -> list[CoveredWords]:
        """The words each stroke passes over — how a stroke names its line."""
        return [CoveredWords(covered_by(stroke.points, shapes, touch)) for stroke in self.strokes]

    @staticmethod
    def _line_of(covered: list[CoveredWords]) -> list[int | None]:
        """The line each stroke names: the one holding most of the words it
        covers. That count measured better here than the fitted-baseline
        distance, which fixed a stroke drawn between two lines but cost three
        more A1 failures."""
        naming: list[int | None] = []
        for cover in covered:
            counts = Counter(shape.line for shape in cover.words)
            naming.append(max(counts, key=lambda key: counts[key]) if counts else None)
        return naming

    def _groups(self, naming: list[int | None]) -> list[StrokeGroup]:
        """The strokes grouped: the ones naming one line and overlapping along it."""
        parent = list(range(len(self.strokes)))
        by_line: dict[int, list[int]] = {
            line_index: [index for index, li in enumerate(naming) if li == line_index]
            for line_index in {li for li in naming if li is not None}
        }
        for members in by_line.values():
            for left in range(len(members)):
                for right in range(left + 1, len(members)):
                    if self._overlap(members[left], members[right]):
                        self._unite(parent, members[left], members[right])
        grouped: dict[int, list[int]] = {}
        for index in range(len(self.strokes)):
            self._group_index(grouped, parent, index)
        return [StrokeGroup(members) for members in grouped.values()]

    @staticmethod
    def _group_index(grouped: dict[int, list[int]], parent: list[int], index: int) -> None:
        """The index into its root's group."""
        grouped.setdefault(Strokes._root(parent, index), []).append(index)

    def _overlap(self, one: int, other: int) -> bool:
        """Whether two strokes share enough of their run along the line."""
        one_span, other_span = self._xspan(one), self._xspan(other)
        return min(one_span.end, other_span.end) - max(one_span.start, other_span.start) > 0.5 * min(
            one_span.end - one_span.start, other_span.end - other_span.start
        )

    def _xspan(self, index: int) -> Span:
        xs = [point.x for point in self.strokes[index].points]
        return Span(min(xs), max(xs))

    @staticmethod
    def _first_line(naming: list[int | None], group: StrokeGroup) -> int:
        """The first line a group names: its place in the page's order."""
        named: list[int] = []
        for index in group.members:
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


def compose_boxes(lines: list[Line], traced: list[TracedBox], scale: Ruler) -> list[Box]:
    """The page's boxes: the detector boxes every line, and a trace replaces the
    span it defines (the boxes it covers are cut out of its line's)."""
    final: list[Box] = []
    for line_index, line in enumerate(lines):
        spans = sorted(
            line.u_span(line.shapes, traced_box.box) for traced_box in traced if traced_box.line == line_index
        )
        for poly in line.boxes(scale):
            final += _boxes_between(line, poly, spans, scale)
    return final + [traced_box.box for traced_box in traced]


def _boxes_between(line: Line, poly: Box, traced: list[USpan], scale: Ruler) -> list[Box]:
    """The boxes one line's polygon gives, with the traced spans taken out."""
    x_ref, y_ref, ux, uy, nx, ny = line.frame(line.shapes)
    along = [(px / Components.SCALE - x_ref) * ux + (py / Components.SCALE - y_ref) * uy for px, py in poly]
    across = [(px / Components.SCALE - x_ref) * nx + (py / Components.SCALE - y_ref) * ny for px, py in poly]
    boxes = [
        line.box(line.shapes, span.start, span.end, min(across), max(across))
        for span in _spans_after([USpan(min(along), max(along))], traced)
        if (span.end - span.start) * Components.SCALE > Reading.MIN_BOX_PX
    ]
    return boxes


def _spans_after(spans: list[USpan], traced: list[USpan]) -> list[USpan]:
    """The spans that remain when every traced span is taken out of them."""
    for traced_span in traced:
        remaining: list[USpan] = []
        for span in spans:
            if traced_span.end <= span.start or traced_span.start >= span.end:
                remaining.append(span)
                continue
            if span.start < traced_span.start:
                remaining.append(USpan(span.start, traced_span.start))
            if traced_span.end < span.end:
                remaining.append(USpan(traced_span.end, span.end))
        spans = remaining
    return spans


def _word(shape: Mark) -> Word:
    """The word a measured shape makes: its box and its own ink lines, in page
    pixels — the record words.json holds and the reading carries."""
    return Word(
        x0=shape.x0 * Components.SCALE,
        y0=shape.y0 * Components.SCALE,
        x1=shape.x1 * Components.SCALE,
        y1=shape.y1 * Components.SCALE,
        measurements=WordMeasurements(
            baseline=shape.baseline * Components.SCALE,
            waistline=shape.waistline * Components.SCALE,
            line=shape.line,
        ),
    )


def write_outputs(trace_dir: Path, page: Image.Image, boxes: list[Box], shapes: list[Mark]) -> None:
    """The reading, written out: boxes.json (the page's boxes) and words.json
    (the words they were measured from), in page pixels."""
    trace_dir.mkdir(parents=True, exist_ok=True)
    with open(trace_dir / "boxes.json", "w") as handle:
        json.dump(Boxes(PageSize(page.width, page.height), boxes).to_dict(), handle, indent=1)
    with open(trace_dir / "words.json", "w") as handle:
        json.dump(Words([_word(shape) for shape in shapes]).to_dict(), handle)


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
    traced = sorted(
        float(np.median([point[1] for point in stroke])) * page.height / Components.SCALE for stroke in strokes_raw
    )
    writing = Writing.of(mask, traced)
    if split:
        writing = writing.cut(writing.scale.unit)
    shapes, lines = writing.marks, writing.lines
    print(
        f"pitch {writing.scale.pitch:.1f} (unit {writing.scale.unit:.1f})  ink: {int(mask.sum())} px"
        f" · ink removed: {removed + writing.stripped} · shapes {len(shapes)} · lines {len(lines)}"
    )

    strokes = Strokes([Stroke.from_wire(stroke) for stroke in strokes_raw], PageSize(page.width, page.height))
    traced_boxes = [
        TracedBox(trace.line_index, trace.box(writing.scale.stroke_tol))
        for trace in strokes.traces(shapes, writing.scale)
    ]
    final = compose_boxes(lines, traced_boxes, writing.scale)
    write_outputs(trace_dir, page, final, shapes)
    print(f"boxes: {len(final)} ({len(traced_boxes)} from strokes, {len(final) - len(traced_boxes)} from the detector)")
    return final


@dataclass(frozen=True)
class Reading:
    """One page's automatic reading, in page pixels: the fitted writing LINES
    (the row proposal the review shows) and the SPLIT WORDS those lines group,
    each word a `Word` record carrying its own measured baseline and waistline.
    The drawn-lines correction (`rows.adjust`) groups the words, so the reading
    carries them — the pipeline persists both side by side."""

    TRACE = Path(os.environ.get("LOFT_TRACE_DIR", "/tmp/trace"))
    INK_DELTA = 25  # grey levels below the local paper level = ink
    MIN_BOX_PX = 20  # full-res px: a leftover sliver thinner than this is noise
    WAIST_RUN = 10  # columns: a cut row running this far is a band of ink, not a stroke tip
    WAIST_OVERLAP = 0.5  # of the shorter longest-run: this much overlap is one band

    lines: list[dict[str, Any]]
    words: list[Word]
    width: int
    height: int


def reading_for_page(page: Image.Image) -> Reading:
    """The page's automatic reading: the fitted writing lines (the row
    proposal for the pipeline's reading stage — object-model Phase 1: rows
    replace the strip stage's layout) and the split words.

    The ink mask is measured at the reader's SCALE resolution, so every box
    is scaled back to page pixels. The lines arrive in reading order (top to
    bottom), text-less; the caller maps the page transcription onto them.
    The words are the splitter's own (`Writing.cut`) — the same words
    ``read_page`` writes to words.json — so the reviewer's drawn row lines
    can correct the rows in the app."""
    mask = ink_mask(page)
    writing = Writing.of(mask, [])
    writing = writing.cut(writing.scale.unit)
    lines: list[dict[str, Any]] = []
    for index, line in enumerate(writing.lines):
        if not line.shapes:
            continue
        xs = [s.x0 for s in line.shapes] + [s.x1 for s in line.shapes]
        ys = [s.y0 for s in line.shapes] + [s.y1 for s in line.shapes]
        lines.append(
            {
                "index": index,
                "text": "",
                "box": [
                    min(xs) * Components.SCALE,
                    min(ys) * Components.SCALE,
                    max(xs) * Components.SCALE,
                    max(ys) * Components.SCALE,
                ],
                "orientation": 0,
                "box_source": "reader",
                "words": [],
            }
        )
    words = [_word(shape) for shape in writing.marks]
    return Reading(lines=lines, words=words, width=page.width, height=page.height)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Box every line of writing on a scanned page.")
    parser.add_argument("--page", type=Path, required=True, help="the page image")
    parser.add_argument(
        "--trace-dir", type=Path, default=Reading.TRACE, help="where strokes.json lives and boxes.json is written"
    )
    args = parser.parse_args(argv)
    read_page(args.page, args.trace_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
