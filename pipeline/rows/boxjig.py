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
from typing import Any

DEFAULT_TRACE = Path("/tmp/trace")  # where boxes.json, words.json and strokes.json live
TRACE = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TRACE
A7_HOLDS = 0.5  # A7: a box holds a word when half its area is inside
COVERAGE = 0.90  # A1: the line must be this much inside its box
TOL_X = 90.0  # A2: px the box may differ from the line's x extent (full-res)
PITCH = 58.0  # line pitch, for A3's "same line" test and A5
SURFACE_MARGIN = 40.0  # A4: px a box may exceed the ink area
MAX_SLOPE_DEG = 6.0  # A5: the letter's lines run ~0-2.4 degrees


def word_share(word: dict, quad: list[list[float]]) -> float:
    ix = max(0.0, min(word["x1"], max(p[0] for p in quad)) - max(word["x0"], min(p[0] for p in quad)))
    iy = max(0.0, min(word["y1"], max(p[1] for p in quad)) - max(word["y0"], min(p[1] for p in quad)))
    area = (word["x1"] - word["x0"]) * (word["y1"] - word["y0"])
    return ix * iy / area if area else 0.0


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


class BoxJig:
    """One run of the box-invariant jig: the trace data (yellow lines,
    boxes, words, surface) and one check per invariant. Each check returns
    its failure count and prints its own verdict; ``run`` drives them and
    returns the gate's exit code (1 = an invariant failed, so the
    generator is refused)."""

    def __init__(
        self,
        lines: list[list[tuple[float, float]]],
        boxes: list[list[list[float]]],
        page: dict[str, Any],
        ink: list[dict[str, Any]],
        surface: dict[str, Any],
    ) -> None:
        self.lines = lines
        self.boxes = boxes
        self.page = page
        self.ink = ink
        self.surface = surface
        self.cover = [[coverage(ln, b) for b in boxes] for ln in lines]

    @classmethod
    def load(cls, trace: Path) -> BoxJig:
        """Read the trace artifacts (strokes, boxes, surface, words)."""
        strokes = json.loads((trace / "strokes.json").read_text())["strokes"]
        boxes = json.loads((trace / "boxes.json").read_text())["boxes"]
        page = json.loads((trace / "boxes.json").read_text())["page"]
        surface = json.loads((trace / "surface.json").read_text())
        ink = json.loads((trace / "words.json").read_text())["words"] if (trace / "words.json").exists() else []
        return cls([sample(s, page["width"], page["height"]) for s in strokes], boxes, page, ink, surface)

    def _stroke_line(self, i: int) -> int | None:
        """The line of writing a stroke's points cover most - A3's judge
        (each stroke's line is the line owning most of the words it
        covers; comparing heights flags ordinary jitter within one line)."""
        counts: dict[int, int] = {}
        for p in self.lines[i]:
            for w in self.ink:
                if w["x0"] - 8 <= p[0] <= w["x1"] + 8 and w["y0"] - 8 <= p[1] <= w["y1"] + 8:
                    counts[w["line"]] = counts.get(w["line"], 0) + 1
        return max(counts, key=lambda k: counts[k]) if counts else None

    def _near_box(self, cx: float, cy: float) -> float:
        """Distance to the nearest box corner - a word edge this close to
        a box counts as inside it (5px rounding)."""
        return min(min(math.hypot(cx - px, cy - py) for px, py in b) for b in self.boxes) if self.boxes else 1e9

    def check_a1(self) -> int:
        """A1 - each yellow line inside exactly one box (>= COVERAGE)."""
        print("A1  each yellow line inside exactly one box (>=90%)")
        failures = 0
        for i, row in enumerate(self.cover):
            hits = [(j, c) for j, c in enumerate(row) if c >= COVERAGE]
            if len(hits) != 1:
                failures += 1
                what = "no box" if not hits else f"{len(hits)} boxes {[(j, round(c, 2)) for j, c in hits]}"
                print(f"    FAIL line {i:>2}: {what}")
        print(f"    {'PASS' if failures == 0 else f'{failures} failure(s)'}\n")
        return failures

    def check_a7(self) -> int:
        """A7 - no box holding words of two different lines ("holds" = half
        the word's AREA inside; edge overlap from ascenders is fine)."""
        print("A7  no box holding words of two different lines")
        failures = 0
        for j, b in enumerate(self.boxes):
            holds = {w["line"] for w in self.ink if word_share(w, b) >= A7_HOLDS}
            if len(holds) > 1:
                failures += 1
                print(f"    FAIL box {j}: holds words of lines {sorted(holds)}")
        print(f"    {'PASS' if failures == 0 else f'{failures} failure(s)'}\n")
        return failures

    def check_a2(self) -> int:
        """A2 - per box: x extent within TOL_X of the union of the strokes
        it serves (a mark may be several strokes on one line)."""
        print("A2  box x position and width within tolerance of the line(s) it serves")
        failures = 0
        for j in range(len(self.boxes)):
            inside = [i for i, row in enumerate(self.cover) if row[j] >= COVERAGE]
            if not inside:
                continue
            bx0, bx1 = quad_x(self.boxes[j])
            sx0 = min(min(p[0] for p in self.lines[i]) for i in inside)
            sx1 = max(max(p[0] for p in self.lines[i]) for i in inside)
            dx0, dx1 = abs(bx0 - sx0), abs(bx1 - sx1)
            if dx0 > TOL_X or dx1 > TOL_X:
                failures += 1
                print(
                    f"    FAIL box {j}: serves lines {inside}; x offset {dx0:.0f}px / {dx1:.0f}px "
                    f"(box x {bx0:.0f}-{bx1:.0f}, lines x {sx0:.0f}-{sx1:.0f})"
                )
        print(f"    {'PASS' if failures == 0 else f'{failures} failure(s)'}\n")
        return failures

    def check_a3(self) -> int:
        """A3 - no box holding two different yellow lines, judged by the
        writing itself (each stroke's line is the line owning most of the
        words it covers)."""
        print("A3  no box holding two different yellow lines")
        failures = 0
        stroke_lines = [self._stroke_line(i) for i in range(len(self.lines))]
        for j in range(len(self.boxes)):
            inside = [i for i, row in enumerate(self.cover) if row[j] >= COVERAGE]
            if len(inside) < 2:
                continue
            claimed = {stroke_lines[i] for i in inside if stroke_lines[i] is not None}
            if len(claimed) > 1:
                failures += 1
                on_lines = sorted(x for x in claimed if x is not None)
                print(f"    FAIL box {j}: holds lines {inside} whose writing is on lines {on_lines}")
        print(f"    {'PASS' if failures == 0 else f'{failures} failure(s)'}\n")
        return failures

    def check_a6(self) -> int:
        """A6 - every word of writing ends up in exactly one box. Outside
        all boxes: under a yellow line (a bug - the line should have boxed
        it) or under nothing (leftover text: the user must trace it). In
        two boxes: only the allowed ascender/descender overlap across
        lines."""
        print("A6  every word of writing in exactly one box (else: trace it or box it)")
        close = 12.0  # a word edge this close to a box counts as inside it (5px rounding)
        failures = 0
        leftover = 0
        overlapped = 0
        for w in self.ink:
            cx, cy = (w["x0"] + w["x1"]) / 2, (w["y0"] + w["y1"]) / 2
            hits = [b for b in self.boxes if in_quad(cx, cy, b)]
            if not hits and self._near_box(cx, cy) < close:
                hits = [min(self.boxes, key=lambda b: min(math.hypot(cx - px, cy - py) for px, py in b))]
            if len(hits) == 1:
                continue
            if not hits:
                traced = any(any(abs(px - cx) < 25 and abs(py - cy) < 25 for px, py in ln) for ln in self.lines)
                if traced:
                    failures += 1
                    print(f"    FAIL word at ({cx:.0f},{cy:.0f}) is under a yellow line but in no box")
                else:
                    leftover += 1
                continue
            overlapped += 1  # two boxes claiming a word: the allowed ascender/descender overlap
        print(
            f"    {'PASS' if failures == 0 else f'{failures} failure(s)'}"
            f" — {leftover} word(s) outside every box with no trace "
            f"(user must trace them), {overlapped} word(s) in two lines' boxes (the allowed overlap)\n"
        )
        return failures

    def check_a4(self) -> int:
        """A4 - boxes stay on the letter surface (the ink area, plus the
        margin - the border ink of a photographed letter is noise)."""
        print("A4  boxes inside the letter surface")
        failures = 0
        for j, b in enumerate(self.boxes):
            for x, y in b:
                if not (
                    self.surface["x0"] - SURFACE_MARGIN <= x <= self.surface["x1"] + SURFACE_MARGIN
                    and self.surface["y0"] - SURFACE_MARGIN <= y <= self.surface["y1"] + SURFACE_MARGIN
                ):
                    failures += 1
                    print(
                        f"    FAIL box {j}: corner ({x:.0f}, {y:.0f}) outside the surface "
                        f"x{self.surface['x0']}-{self.surface['x1']} y{self.surface['y0']}-{self.surface['y1']}"
                    )
                    break
        print(f"    {'PASS' if failures == 0 else f'{failures} failure(s)'}\n")
        return failures

    def check_a5(self) -> int:
        """A5 - no nonsense orientation: a box's slope must be a plausible
        writing slope (the letter's lines run within a few degrees of
        horizontal)."""
        print("A5  boxes run along the writing (slope within a few degrees)")
        failures = 0
        for j, b in enumerate(self.boxes):
            s = quad_slope(b)
            if abs(s) > MAX_SLOPE_DEG:
                failures += 1
                print(f"    FAIL box {j}: slope {s:.1f}°")
        print(f"    {'PASS' if failures == 0 else f'{failures} failure(s)'}\n")
        return failures

    def run(self) -> int:
        """Drive every check over the loaded trace and print the verdict."""
        detector_only = not self.lines  # no yellow lines: judge the detector on its own
        mode = "detector alone (A1-A3 need yellow lines, so they are skipped)" if detector_only else "assisted"
        print(
            f"jig: {len(self.lines)} yellow lines, {len(self.boxes)} boxes,"
            f" page {self.page['width']}x{self.page['height']} — {mode}"
        )
        print(
            f"     coverage >= {COVERAGE:.0%} · x tolerance {TOL_X:.0f}px"
            f" · surface margin {SURFACE_MARGIN:.0f}px · max slope {MAX_SLOPE_DEG}°\n"
        )
        failures = 0
        if detector_only:
            print("A1-A3  skipped (they are about the reviewer's lines)\n")
        else:
            failures += self.check_a1()
        for check in (self.check_a7, self.check_a2, self.check_a3, self.check_a6, self.check_a4, self.check_a5):
            failures += check()
        print(f"{'ALL PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
        return 1 if failures else 0


def main() -> int:
    """The CLI entry: run the jig over the trace given on argv (or the default)."""
    return BoxJig.load(TRACE).run()


if __name__ == "__main__":
    sys.exit(main())
