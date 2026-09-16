"""Splitter case sheets: one raw ink component vs what split_shapes does to it.

Pipeline: run the detector (tools/reader + tools/mark on page-01), compute
each case's pieces/cuts/drops from split_shapes' own output, draw every
sheet through tools/page_visuals.split_sheet. Only the case table — which
component, which crop window, which title — lives here; all drawing lives
in the library.
Usage: .venv/bin/python research/spike-word-segmentation/render_split_cases.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from PIL import Image

from tools.mark import SCALE, SHAPE_MIN_AREA, find_marks
from tools.page_visuals import contiguous_runs, review_image, split_sheet, stack_sheets
from tools.pagescale import PageScale, line_ratio, traced_pitch, writing_scale
from tools.reader import LineFitter, artifacts, ink_mask, split_shapes

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
TRACE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "page01-wordseg"
OUTDIR = Path(__file__).resolve().parent / "split-cases"


# name -> raw component id, crop window (x0, y0, x1, y1, scale) in page px, title
# (user rulings 2026-09-13: cases 2, 4, 5, 6, 7, 8, 9 are each ONE word the
# splitter must NOT split — my "weld"/"kiss"/"three-line" labels were
# misreads of the ink, checked only after the user corrected them.
# id=1970's "waist" is intra-word cursive; id=683's "three lines" are the
# word's own ascenders; id=9690/6475's "touches" never reach the next line.)
CASES = {
    "case1_single": ("19583", (1090, 4120, 1500, 4300, 3.0), "Case 1 — clean single-line: one in, one out"),
    "case2_oneword": ("4503", (660, 2620, 990, 2780, 2.5), "Case 2 — one word, cut mid-body: must NOT split"),
    "case3_bug": ("4847", (1440, 2650, 2050, 2770, 2.0), "Case 3 — y2710 cut refused, y2680 cut stands"),
    "case4_oneword": ("9690", (900, 3140, 1170, 3360, 2.5), "Case 4 — one word, split in two: must NOT split"),
    "case5_oneword": ("6475", (720, 2830, 1060, 3050, 2.5), "Case 5 — one word, split in two: must NOT split"),
    "case6_oneword": ("5555", (1020, 2710, 1180, 2900, 2.5), "Case 6 — one word, split in three: must NOT split"),
    "case7_oneword": ("3780", (1160, 2540, 1360, 2730, 2.5), "Case 7 — one word, edge touch: must NOT split"),
    "case8_oneword": ("1970", (720, 2380, 1020, 2560, 3.0), "Case 8 — one word, intra-word waist: must NOT split"),
    "case9_oneword": ("683", (1330, 2220, 1590, 2420, 3.0), "Case 9 — one word, split in three: must NOT split"),
    "case10_twowords": ("2911", (1810, 2480, 2000, 2660, 2.5), "Case 10 — render 47: two words, one shape: MUST split"),
    "case11_pair": ("5514", (1430, 2710, 1750, 2880, 2.5), "Case 11 — renders 75 + 81: halves stay apart"),
    "case12_pair": ("22082", (1480, 4400, 1640, 4580, 2.5), "Case 12 — renders 324 + 332: two words, stay apart"),
    "case13_pupil": ("2723", (1690, 2470, 1860, 2620, 3.0), "Case 13 — 2723: one digit, one piece (user 2026-09-16)"),
    "case14_23150": ("23150", (1460, 4390, 1680, 4600, 3.0), "Case 14 — 23150: two pieces (user 2026-09-16)"),
    "case15_bug_slivers": ("4847", (1440, 2530, 2060, 2730, 2.0), "Case 15 — 4847's upper slivers: must merge"),
    "case16_rule": ("2875", (1900, 2500, 2060, 2640, 3.0), "Case 16 — 2875: two pieces (no rule claimed)"),
}


def _case_geometry(shape, per_row, pieces):
    """The sheet's data, computed from the splitter's own output: piece boxes
    + labels, cut rows + per-row profiles, dropped bands + label, summary."""
    covered: set[int] = set()
    for p in pieces:
        ys, _ = p.pix
        covered.update(int(v) for v in ys.astype(int))
    dropped_rows = sorted(y for y in per_row if y not in covered)
    # cuts: boundaries between SURVIVING pieces only — speck-segment edges
    # are dropped ink, not cuts, and drawing them buries the real one.
    bounds = [int(round((a.y1 + b.y0) / 2)) for a, b in zip(pieces, pieces[1:], strict=False)]

    def profile(cy):
        return " ".join(f"{y * SCALE:.0f}:{len(per_row[y])}" for y in range(cy - 3, cy + 4) if y in per_row)

    pieces_arg = [
        (
            (p.x0 * SCALE, p.y0 * SCALE, p.x1 * SCALE, p.y1 * SCALE),
            f"P{i + 1} n={int(p.area)} L{p.line}",
        )
        for i, p in enumerate(pieces)
    ]
    cuts_arg = [(cy * SCALE, [profile(cy)]) for cy in bounds]
    runs = contiguous_runs(dropped_rows)
    drops_arg = [(run[0] * SCALE, (run[-1] + 1) * SCALE) for run in runs]
    drop_label = f"DROPPED {sum(len(per_row[y]) for y in dropped_rows)}px (floor {SHAPE_MIN_AREA // 2})"
    summary = (
        f"raw id={shape.id} y{shape.y0 * SCALE:.0f}-{shape.y1 * SCALE:.0f} -> "
        f"{len(pieces)} piece(s), {len(dropped_rows)} rows dropped ({sum(len(per_row[y]) for y in dropped_rows)}px)"
    )
    return pieces_arg, cuts_arg, drops_arg, drop_label, summary


def _main() -> int:
    page = Image.open(SCAN).convert("RGB")
    strokes_raw = json.loads((TRACE / "strokes.json").read_text())["strokes"]
    mask = ink_mask(page)
    artifacts(mask)
    shapes = find_marks(mask)
    traced_lines = sorted(float(np.median([p[1] for p in s])) * page.height / 2 for s in strokes_raw)
    ratio = line_ratio(traced_pitch(traced_lines), writing_scale([s.height for s in shapes]))
    scale = PageScale.of([s.height for s in shapes], ratio)
    lines = LineFitter(scale).fit(shapes)
    by_id = {s.id: s for s in shapes}
    OUTDIR.mkdir(parents=True, exist_ok=True)
    sheets = []
    for name, (sid, crop, title) in CASES.items():
        shape = by_id[sid]
        per_row = shape.rows()
        pieces = split_shapes([shape], lines, scale.unit)
        pieces_arg, cuts_arg, drops_arg, drop_label, summary = _case_geometry(shape, per_row, pieces)
        # split_sheet takes one profile string per cut; join the rows here.
        cuts_flat = [(cy, " ".join(prof)) for cy, prof in cuts_arg]
        sheet = split_sheet(
            page,
            (shape.x0 * SCALE, shape.y0 * SCALE, shape.x1 * SCALE, shape.y1 * SCALE),
            pieces_arg,
            cuts_flat,
            drops_arg,
            drop_label,
            title,
            summary,
            crop,
        )
        out = OUTDIR / f"{name}.png"
        sheet.save(out)
        print(f"{name} -> {out}")
        sheets.append(sheet)
    review_names = []
    for name, sheet in zip(CASES, sheets, strict=False):
        data = review_image(sheet)
        (OUTDIR / f"{name}.jpg").write_bytes(data)
        review_names.append((name, CASES[name][2], len(data)))
        print(f"{name}_review -> {OUTDIR / f'{name}.jpg'} ({len(data) // 1024}KB)")
    total = sum(n for _, _, n in review_names)
    assert total < 1_200_000, f"review page weighs {total // 1024}KB, budget is 1200KB"
    contact = stack_sheets([Image.open(OUTDIR / f"{name}.jpg") for name, _, _ in review_names])
    contact.save(OUTDIR / "all_cases.jpg", quality=70)
    print(f"all_cases -> {OUTDIR / 'all_cases.jpg'} ({(OUTDIR / 'all_cases.jpg').stat().st_size // 1024}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
