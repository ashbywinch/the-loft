"""How tall may a band be? The measurement behind the band sizing.

A page arrives at the vision model as bands because one tall image is
downsampled by its long edge — page-01's numbers reach the model unreadably
small and it stops where it can still see them. The band count follows from that
limit, so the limit has to be measured rather than guessed at.

The measurement needs no gold: the row numbers are DRAWN by us, so a band's
numbers are known exactly, and a band whose numbers the model cannot read is a
band too tall. Each band is the production render (the rows tinted, the chips at
their line ends) with the production prompt, one call per band — the production
path exactly once, no sampling and no second tries.

Usage:
    PYTHONPATH=. .venv/bin/python -m tools.eval_band_size [--fixture DIR]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image

from document.numbered_rows import NumberedRows
from tools.render import render_rows
from tools.rows import Rows
from tools.schemas import load_user_row_adjustments
from tools.transcripts import SYSTEM, band_prompt
from tools.vlm import VlmOptions, transcribe_images_vlm
from tools.word import Word

SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
FIXTURE = Path("tests/fixtures/page01-rows-gold")
OUT = Path("work/eval-band-size")

# the band heights tried, tallest first: 2450 is the whole writing on one image
# (the case bands exist to avoid) and the rest step down to well inside the
# model's comfort. The tallest height whose bands come back fully read is the
# limit the renderer sizes bands by.
HEIGHTS = (2450, 2000, 1700, 1500, 1300, 1100, 900)


def read_band(band: NumberedRows, index: int, of: int, height: int, out_dir: Path) -> dict[str, Any]:
    """One band's call, and what it could see of that band: the numbers drawn on
    it are known, so which of them the answer names is checkable with no gold."""
    numbers = sorted(band.numbers.values())
    path = out_dir / f"page-01.max-{height}.band-{index + 1}.jpg"
    band.image.save(path, quality=88)
    started = time.monotonic()
    answer, _usage = transcribe_images_vlm(
        [path], options=VlmOptions(system=SYSTEM, user_text=band_prompt(index, of, numbers, []))
    )
    (out_dir / f"page-01.max-{height}.band-{index + 1}.answer.json").write_text(
        json.dumps({"answer": answer}, indent=1), encoding="utf-8"
    )
    named = _numbers_named(answer, numbers)
    return {
        "height": band.image.height,
        "width": band.image.width,
        "rows": numbers,
        "read": named,
        "seconds": round(time.monotonic() - started, 1),
    }


def run(image_path: Path, fixture: Path, heights: tuple[int, ...] = HEIGHTS) -> list[dict[str, Any]]:
    """One pass per band height: the bands that height makes, and how much of
    each band's numbering the model could see."""
    page = Image.open(image_path)
    rows = Rows.from_words(_words(fixture), (page.width, page.height)).adjust(
        load_user_row_adjustments(fixture / "user-row-adjustments.json")["lines"]
    )
    OUT.mkdir(parents=True, exist_ok=True)
    report: list[dict[str, Any]] = []
    for height in heights:
        bands = NumberedRows.render_strips(render_rows(page, rows), rows, max_band_height=height)
        if not bands:
            continue
        read = [read_band(band, index, len(bands), height, OUT) for index, band in enumerate(bands)]
        wanted = [number for band in read for number in band["rows"]]
        found = [number for band in read for number in band["read"]]
        missed = sorted(set(wanted) - set(found))
        silent = sum(1 for band in read if not band["read"])
        summary = {
            "max_height": height,
            "bands": len(bands),
            "band_height": max(band["height"] for band in read),
            "band_width": max(band["width"] for band in read),
            "rows": len(wanted),
            "numbers_read": len(found),
            "numbers_missed": missed,
            "bands_with_no_number": silent,
            "seconds": round(sum(band["seconds"] for band in read), 1),
        }
        report.append(summary)
        print(
            f"max {height}px -> bands {summary['bands']} (tallest {summary['band_height']}px): "
            f"numbers {summary['numbers_read']}/{summary['rows']} read"
            + (f", {silent} band(s) named nothing" if silent else "")
        )
    (OUT / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def _numbers_named(answer: str, wanted: list[int]) -> list[int]:
    """Which of a band's own numbers the answer names."""
    try:
        segments = json.loads(answer).get("segments", [])
    except json.JSONDecodeError:
        return []
    named = {number for segment in segments for number in segment.get("rows", [])}
    return [number for number in wanted if number in named]


def _words(fixture: Path) -> list[Word]:
    records = json.loads((fixture / "words.json").read_text(encoding="utf-8"))["words"]
    return [
        Word(
            record["x0"],
            record["y0"],
            record["x1"],
            record["y1"],
            baseline=record.get("baseline"),
            waistline=record.get("waistline"),
            line=record.get("line"),
        )
        for record in records
    ]


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    fixture = Path(args[args.index("--fixture") + 1]) if "--fixture" in args else FIXTURE
    heights = HEIGHTS
    if "--heights" in args:
        heights = tuple(int(value) for value in args[args.index("--heights") + 1].split(","))
    if not SCAN.is_file():
        print(f"SKIP {SCAN}: not on this box")
        return 0
    print(json.dumps(run(SCAN, fixture, heights), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
