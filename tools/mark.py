"""One connected piece of ink on the page: a MARK.

The reviewer's word: a word is a mark made of one or more letters. A mark is
the finest grain the detector sees - its bounds, its measured baseline and
waistline (the x-height between them), and its ink. Marks are found at the
working resolution SCALE ; everything else
measures from them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class WordGeometry:
    """A word's two measured lines: the baseline it stands on and the
    waistline above it. Named fields - the order-swap class of bug (is a
    bare tuple waist-first or base-first?) cannot exist."""

    baseline: float
    waistline: float

    @property
    def x_height(self) -> float:
        return self.baseline - self.waistline


SCALE = 2  # work at half resolution (2px geometry precision)
STREAK_TALL = 40  # 1/2 px: a run this tall and ≤3 wide is a scan line
STREAK_WIDE = 60  # 1/2 px: a run this wide and ≤4 tall is a rule
SHAPE_MIN_AREA = 60  # 1/2 px²: smaller components are specks
RULE_ASPECT = 8.0  # width ÷ height: a horizontal line, not writing (tools/word.py)
RULE_TOUCH = 0.15  # of its width: a line is nearly disconnected from the writing
LINE_GAP = 0.75  # × the writing's height: a line further below it is not underscoring it
LINE_ALIGN = 0.2  # of the writing's width: an underline matches it, a rule does not
LINE_HEIGHT = 0.65  # × the x-height: a line is a pen stroke, not a band
WORD_MIN_HEIGHT = 0.38  # × the x-height: shorter ink is a word's fragment
WORD_FULL_LINE = 0.6  # × the x-height: this tall and the piece is a line of writing
WORD_MIN_WIDTH = 0.8  # × the x-height: narrower ink cannot hold a word
WORD_EMPTY_MAX = 0.25  # of its columns, under a full line: disconnected ascender


@dataclass
class Mark:
    """A connected run of ink — a word, or a letter in print."""

    x0: float
    y0: float
    x1: float
    y1: float
    baseline: float
    waistline: float
    area: float
    cx: float
    pix: tuple[np.ndarray, np.ndarray]
    line: int = -1
    id: str = ""

    @property
    def x_height(self) -> float:
        """The word's font size: baseline to waistline, blind to ascenders
        and descenders (box height is not)."""
        return self.baseline - self.waistline

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

    def piece(self, ink: list[tuple[int, int]], line: int, suffix: int) -> Mark:
        """The part of this shape on the given rows, as its own shape on one line."""
        ny = np.array([point[0] for point in ink], dtype=np.float32)
        nx = np.array([point[1] for point in ink], dtype=np.float32)
        histogram: dict[int, int] = {}
        for y in ny.astype(int):
            histogram[int(y)] = histogram.get(int(y), 0) + 1
        return Mark(
            x0=float(nx.min()),
            y0=float(ny.min()),
            x1=float(nx.max()),
            y1=float(ny.max()),
            baseline=float(Ink(ny, nx).baseline_row()),
            waistline=float(Ink(ny, nx).waistline_row()),
            area=float(len(ink)),
            cx=(float(nx.min()) + float(nx.max())) / 2,
            pix=(ny, nx),
            line=line,
            id=f"{self.id}_{suffix}",
        )

    def _bridge_columns(self, other: Mark) -> int:
        """Columns where two pieces' ink meets across their shared edge: how
        much of the boundary is welded. A line is detached (near zero); a
        word's chopped half shares most of its width with what it was cut from."""
        ys, xs = np.asarray(self.pix[0]).astype(int), np.asarray(self.pix[1]).astype(int)
        oys, oxs = np.asarray(other.pix[0]).astype(int), np.asarray(other.pix[1]).astype(int)
        if self.y0 < other.y0:  # this piece sits above: its feet against other's crown
            mine = {x for y, x in zip(ys, xs, strict=False) if y >= ys.max() - 1}
            theirs = {x for y, x in zip(oys, oxs, strict=False) if y <= oys.min() + 1}
        else:
            mine = {x for y, x in zip(ys, xs, strict=False) if y <= ys.min() + 1}
            theirs = {x for y, x in zip(oys, oxs, strict=False) if y >= oys.max() - 1}
        return len(mine & theirs)

    def is_word_shaped(self, unit: float) -> bool:
        """A piece that could be a word: tall enough to hold letter bodies, wide
        enough to hold more than a stroke, and joined up.

        User 2026-09-16, on the case sheets: 2911's upper piece is 'a full word
        that's all joined up'; 1970's is 'very discontinuous pieces of
        ascender'. So a fragment is short, narrow, or full of empty columns —
        and a cut that would leave one is a chop, not a word boundary."""
        ys, xs = np.asarray(self.pix[0]).astype(int), np.asarray(self.pix[1]).astype(int)
        if len(ys) == 0:
            return False
        height = float(ys.max() - ys.min() + 1)
        width = float(xs.max() - xs.min() + 1)
        if height < WORD_MIN_HEIGHT * unit or width < WORD_MIN_WIDTH * unit:
            return False
        if width >= RULE_ASPECT * height:
            return False  # a band this wide for its height is a line, not a word
        if height < WORD_FULL_LINE * unit:
            # too short to be a whole line of writing: it must be joined up, not
            # the detached tips of a word's ascenders
            return 1.0 - len(set(xs.tolist())) / width <= WORD_EMPTY_MAX
        return True

    def classify_line(self, others: list[Mark], page: list[Mark], unit: float) -> str | None:
        """The line this piece is, if it is one: "underline" or "rule", else None.

        A line is a pen stroke: thin (LINE_HEIGHT × the writing's x-height at
        most) and long (RULE_ASPECT wider than tall), and detached from the
        writing it accompanies — a word's chopped half shares its boundary with
        the rest of the word (user 2026-09-16: 'an underline is entirely or
        nearly entirely disconnected from the word'). `others` is the ink it is
        welded to.

        Which kind, by the width of the writing above it on the page (user
        2026-09-16: '14187 is nearly exactly the width of the text above it; the
        other one is not. A rule is a line that is not aligned with the words
        above it, whether wider or narrower or offset.')."""
        width, height = self.x1 - self.x0, self.y1 - self.y0
        if height <= 0 or height > LINE_HEIGHT * unit or width < RULE_ASPECT * height:
            return None
        if sum(self._bridge_columns(other) for other in others) > RULE_TOUCH * width:
            return None  # welded to the rest of the word: a fragment, not a line
        above = [
            other
            for other in page
            if other is not self
            and other.y1 <= self.y0
            and min(other.x1, self.x1) - max(other.x0, self.x0) > 0
            and self.y0 - other.y1 <= LINE_GAP * max(other.height, 1.0)
        ]
        if not above:
            return "rule"  # no writing close above it
        writing = max(other.x1 for other in above) - min(other.x0 for other in above)
        return "underline" if abs(width - writing) <= LINE_ALIGN * max(writing, 1.0) else "rule"


BROAD_FRACTION = 0.25  # x the word's width: a row holding this much ink is the writing
UNDERLINE_RUN = 8.0  # px: an underline's rows are this wide at minimum


@dataclass(frozen=True)
class Ink:
    """One piece of ink, as the two arrays every measurement needs: the rows
    and the columns of its pixels.

    The measurements are its methods — they all read the same pair, which is
    what made them a clump of free functions taking (ys, xs)."""

    ys: np.ndarray
    xs: np.ndarray

    def longest_runs(self) -> dict[int, int]:
        """Per-row longest continuous ink run, in columns."""
        ys, xs = self.ys, self.xs
        rows: dict[int, set[int]] = {}
        for y, x in zip(ys.astype(int), xs.astype(int), strict=False):
            rows.setdefault(int(y), set()).add(int(x))
        runs: dict[int, int] = {}
        for y, cols in rows.items():
            ordered = sorted(cols)
            run = 1
            longest = 1
            for a, b in zip(ordered, ordered[1:], strict=False):
                run = run + 1 if b == a + 1 else 1
                longest = max(longest, run)
            runs[y] = longest
        return runs

    def _thick_zone(self, span: float) -> set[int]:
        """The rows of a thick broad band: consecutive rows whose ink runs a
        fifth or more of the word's width (a crossbar, a big loop's rim, a
        welded underline), plus their 2px fringe. Such rows are never the
        writing's feet."""
        runs = self.longest_runs()
        broad = {y for y, run in runs.items() if run >= BROAD_FRACTION * span}
        thick: set[int] = set()
        for y in broad:
            if any(near in broad for near in (y - 1, y + 1)):
                thick.add(y)
        return set(range(min(thick) - 2, max(thick) + 3)) if thick else set()

    def baseline_row(self) -> int:
        """The row a word's letters stand on: the modal BOTTOM ink row per column.

        The bottom contour is the physical definition: each column's lowest ink
        pixel contributes, and the most common bottom row is the baseline. Two
        per-word hazards upset the plain mode - a crossbar (the f's: rows 25-29
        run a fifth or more of the word's width) and a big loop's rim (the g's:
        its bottom arc) - so rows that are part of a THICK BROAD BAND are not
        bottom candidates: their columns' lowest ink is the band, not the
        writing's feet. Their ±2px fringe goes too, and the survivors' modal is
        measured in ±4px bands, so a body whose letters end at slightly different
        depths still wins over a descender tail. All of it per word, from the
        word's own ink: the lines are not known yet - this is what builds them.
        """
        ys, xs = self.ys, self.xs
        if len(ys) == 0:
            return 0
        span = float(xs.max() - xs.min() + 1)
        intensities = np.bincount(ys.astype(int))
        peak_row = int(np.argmax(intensities))
        top, bottom = int(ys.min()), int(ys.max())
        row_runs = self.longest_runs()
        broad = {y for y, run in row_runs.items() if run >= max(0.15 * span, UNDERLINE_RUN)}
        bands: list[list[int]] = []
        for y in sorted(broad):
            if bands and y - bands[-1][-1] <= 1:
                bands[-1].append(y)
            else:
                bands.append([y])
        band_at_foot = bool(
            bands
            and (bottom - max(bands[-1])) <= 0.25 * (bottom - top)
            and (max(bands[-1]) - min(bands[-1])) <= 0.35 * (bottom - top)
        )
        if band_at_foot:
            seam = self._letters_on_top_of(bands[-1], intensities, peak_row, top)
            if seam is not None:
                return seam
        forbidden = self._thick_zone(span)
        bottoms: dict[int, int] = {}
        for y, x in zip(ys.astype(int), xs.astype(int), strict=False):
            if int(y) > bottoms.get(int(x), -1):
                bottoms[int(x)] = int(y)
        kept = [b for b in bottoms.values() if b not in forbidden]
        if not kept:
            kept = list(bottoms.values())  # an all-band word (a solid glyph): measure as-is
        return _modal_bottom(kept)

    def _letters_on_top_of(self, band: list[int], intensities: np.ndarray, peak_row: int, top: int) -> int | None:
        """Where the letters end when an UNDERLINE owns the word's foot.

        The last broad band touches the foot, so the letters end at the last
        row above the band's deep valley with real body density. The Opera box:
        the letters end at row 43, the valley dips to 2-5, the underline's core
        runs 50-56. The valley must be DEEP - a dense bottom is a bottom-heavy
        word's own body, not an underline."""
        band_top = min(band)
        valley = (
            min(range(max(top, band_top - 6), band_top), key=lambda y: intensities[y])
            if band_top > max(top, band_top - 6)
            else top
        )
        if intensities[valley] > 0.2 * intensities[peak_row]:
            return None  # the valley is shallow: this is the word's own body
        body_floor = max(3 * intensities[valley], 1)
        return next(
            (y for y in range(valley - 1, top - 1, -1) if intensities[y] >= body_floor),
            valley,
        )

    def _broad_waistline(self, width: float) -> int | None:
        """The first row from the top whose ink run spans BROAD_FRACTION of the
        word: the crown of the letters' bodies. Ascender tails and descenders are
        narrow strokes; a big loop's crown ('group' - the reviewer's g-word) is
        broad, so it lands the line where the old profile walk stopped short."""
        ys, xs = self.ys, self.xs
        rows: dict[int, list[int]] = {}
        for y, x in zip(ys.astype(int), xs.astype(int), strict=False):
            rows.setdefault(int(y), []).append(int(x))
        threshold = BROAD_FRACTION * width
        for y in sorted(rows):
            ordered = sorted(set(rows[y]))
            run = 1
            longest = 1
            for a, b in zip(ordered, ordered[1:], strict=False):
                run = run + 1 if b == a + 1 else 1
                longest = max(longest, run)
            if longest >= threshold:
                return int(y)
        return None

    def waistline_row(self) -> int:
        """The top of a word's letter bodies: the x-height line.

        The broad-band walk first: the crown of the writing - the first row from
        the top whose ink run spans a fifth of the word. Where cursive ascenders
        are thin strokes this is the bodies' top exactly ('group's crown, the f's
        bodies); where no row is broad (printed letters, isolated glyphs) the
        profile walk stands: from the peak row, the first row whose count falls
        below half the peak. With `baseline_row` this gives the word's x-height,
        the size measure that ascenders and descenders cannot distort.
        """
        ys, xs = self.ys, self.xs
        if len(ys) == 0:
            return 0
        span = float(xs.max() - xs.min() + 1)
        forbidden = set()
        row_runs = self.longest_runs()
        broad = {y for y, run in row_runs.items() if run >= max(0.15 * span, UNDERLINE_RUN)}
        bands2: list[list[int]] = []
        for y in sorted(broad):
            if bands2 and y - bands2[-1][-1] <= 1:
                bands2[-1].append(y)
            else:
                bands2.append([y])
        top, bottom = int(ys.min()), int(ys.max())
        if bands2 and (bottom - max(bands2[-1])) <= 0.25 * (bottom - top):
            # only the foot band (a welded underline) leaves the crown profile;
            # a mid-word bar (the f's crossbar) is the word's own geometry
            forbidden = {y for y in range(min(bands2[-1]) - 2, bottom + 1)}
        keep = np.array([int(y) not in forbidden for y in ys.astype(int)])
        kept_ys = ys[keep]
        if len(kept_ys) == 0:
            kept_ys = ys  # an all-band word: measure as-is
        crown = Ink(kept_ys, xs[keep])._broad_waistline(span)
        if crown is not None:
            return crown
        counts = np.bincount(np.round(kept_ys).astype(int))
        if counts.size == 0:
            return 0
        peak = int(np.argmax(counts))
        waistline = peak
        while waistline > 0 and counts[waistline - 1] > counts[peak] * 0.5:
            waistline -= 1
        return waistline


def _modal_bottom(bottoms: list[int]) -> int:
    """The most common bottom row, counted in ±2 bands (measured: ±4 drifts the
    centre; ±2 puts the f's bodies at 39 against 41 and the g's at 23 against
    21); ties go to the lower row (a bar sits ABOVE the baseline)."""
    best, best_bottom = 0, 0
    for candidate in sorted(set(bottoms)):
        count = sum(1 for bottom in bottoms if abs(bottom - candidate) <= 2)
        if count > best or (count == best and candidate > best_bottom):
            best, best_bottom = count, candidate
    return best_bottom


class Components:
    """Union-find over the ink's row runs: which runs are one connected piece.

    Each mask row contributes its runs; a run joins the previous row's runs
    where their columns overlap, so 8-connected ink ends under one root. The
    pass builds `rows` (the runs per row, each with its run id) and answers
    `labels`, the per-pixel component ids."""

    def __init__(self) -> None:
        self.parent: list[int] = []
        self.rows: list[list[tuple[int, int, int]]] = []
        self._previous: list[tuple[int, int, int]] = []

    def add_row(self, row: np.ndarray) -> None:
        """One mask row: its runs, joined to the runs above where they overlap."""
        current: list[tuple[int, int, int]] = []
        if row.any():
            edges = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
            for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=False):
                self.parent.append(len(self.parent))
                current.append((int(start), int(end) - 1, len(self.parent) - 1))
            self._join_overlapping(current)
        self.rows.append(current)
        self._previous = current

    def _join_overlapping(self, current: list[tuple[int, int, int]]) -> None:
        """Unite every run of this row with the ones it touches above it."""
        i = j = 0
        while i < len(current) and j < len(self._previous):
            start, end, _ = current[i]
            prev_start, prev_end, _ = self._previous[j]
            if end < prev_start:
                i += 1
            elif prev_end < start:
                j += 1
            else:
                self._union(current[i][2], self._previous[j][2])
                i, j = (i + 1, j) if end < prev_end else (i, j + 1)

    def labels(self, shape: tuple[int, int]) -> np.ndarray:
        """Every pixel's component id, 1-based in the order the runs were found."""
        labels = np.zeros(shape, dtype=np.int32)
        for y, current in enumerate(self.rows):
            for start, end, rid in current:
                labels[y, start : end + 1] = self._find(rid) + 1
        return labels

    def _find(self, run: int) -> int:
        """The root of a run's component, with the path halved on the way."""
        while self.parent[run] != run:
            self.parent[run] = self.parent[self.parent[run]]
            run = self.parent[run]
        return run

    def _union(self, one: int, other: int) -> None:
        root_one, root_other = self._find(one), self._find(other)
        if root_one != root_other:
            self.parent[root_other] = root_one


def find_marks(mask: np.ndarray, min_area: int = SHAPE_MIN_AREA) -> list[Mark]:
    """The page's marks: every 8-connected piece of ink, specks aside."""
    components = Components()
    for row in mask:
        components.add_row(row)
    labels = components.labels(mask.shape)
    out: list[Mark] = []
    ids, counts = np.unique(labels[labels > 0], return_counts=True)
    for component, area in zip(ids, counts, strict=False):
        if area < min_area:
            continue
        ys, xs = np.nonzero(labels == component)
        ink = Ink(ys, xs)
        out.append(
            Mark(
                x0=float(xs.min()),
                y0=float(ys.min()),
                x1=float(xs.max()),
                y1=float(ys.max()),
                baseline=float(ink.baseline_row()),
                waistline=float(ink.waistline_row()),
                area=float(area),
                cx=(int(xs.min()) + int(xs.max())) / 2,
                pix=(ys.astype(np.float32), xs.astype(np.float32)),
                id=str(int(component)),
            )
        )
    return out
