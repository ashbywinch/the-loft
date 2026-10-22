"""The column-region experiment: the ink's x-projection
segments the page into column regions; each region is read at its own
text orientation (upright, or rotated +90 when the boxes are vertical —
the postcard's message), the boxes remapped into the page frame. The
crops are the REGIONS — the message's full panel — so the rotated
lines fit, unlike the uniform grid's cut crops (the spike's lesson).

Usage: eval_regions.py <batch_id> <page> [--model MODEL]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

import numpy as np
from PIL import Image

from pipeline.evals.eval_crop_grid import read_crop
from pipeline.evals.eval_geometry import CropReading
from pipeline.layout import Layout
from pipeline.layout_line import LayoutLine
from tools.loft_paths import WORK_DIR


@dataclass(frozen=True)
class ColumnRegion:
    """One column region: the ink's x-range, from its first to its last
    inked column."""

    x0: int
    x1: int


def column_regions(image: Path, min_ink: int = 5) -> list[ColumnRegion]:
    """The ink's column clusters: the x-projection's valleys split the
    content into regions (the postcard's message column vs the address
    column)."""
    with Image.open(image) as im:
        arr = np.array(im.convert("L"))
    dark = (arr < 140).sum(axis=0)
    threshold = max(dark.max() * 0.05, min_ink)
    ink = dark > threshold
    regions: list[ColumnRegion] = []
    start: int | None = None
    gap = 0
    for x, has in enumerate(ink):
        if has:
            if start is None:
                start = x
            gap = 0
        elif start is not None:
            gap += 1
            # a gap this wide ends the region (the message/address split)
            if gap > 100:
                regions.append(ColumnRegion(start, x - gap))
                start = None
    if start is not None:
        regions.append(ColumnRegion(start, len(ink) - 1))
    # drop the near-empty regions (the projection noise)
    return [region for region in regions if region.x1 - region.x0 > 100]


@dataclass(frozen=True)
class InkRows:
    """The ink's row extent: the first and last inked rows of the page."""

    top: int
    bottom: int


def ink_y_range(image: Path) -> InkRows:
    """The ink's row extent — the regions' vertical span."""
    with Image.open(image) as im:
        arr = np.array(im.convert("L"))
    dark = (arr < 140).sum(axis=1)
    rows = np.where(dark > 3)[0]
    if len(rows) == 0:
        return InkRows(0, 0)
    return InkRows(int(rows.min()), int(rows.max()))


@dataclass(frozen=True)
class RegionsReport:
    """The column-region run's ledger: what the page read as, what failed,
    what it cost."""

    page: str
    regions: int
    failed_regions: int
    lines: int
    boxless: int
    tokens: int
    elapsed_s: float

    def to_dict(self) -> dict[str, Any]:
        """The report as its JSON record."""
        return {
            "page": self.page,
            "regions": self.regions,
            "failed_regions": self.failed_regions,
            "lines": self.lines,
            "boxless": self.boxless,
            "tokens": self.tokens,
            "elapsed_s": self.elapsed_s,
        }


# lucidlint: ignore long-param-list the region run's inputs are the page's state — no class for one call site
def run(
    batch_id: str,
    page: str,
    work_dir: Path,
    model: str = "z-ai/glm-4.6v",
    base_url: str | None = None,
    api_key: str | None = None,
) -> RegionsReport:
    """The column-region read: the ink's columns as the crops, each read
    at its orientation, the boxes stitched — the experiment's ledger for
    one page."""
    image_path = work_dir / batch_id / "oriented" / f"{page}.jpg"
    with Image.open(image_path) as im:
        width, height = im.size
    ink = ink_y_range(image_path)
    regions = column_regions(image_path)
    tokens = 0
    failed = 0
    lines: list[LayoutLine] = []
    started = monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        for i, region in enumerate(regions):
            crop = CropReading(
                float(region.x0),
                float(ink.top),
                float(region.x1 - region.x0),
                float(ink.bottom - ink.top),
                [],
            )
            read = read_crop(crop, image_path, Path(tmp), i, model, base_url or "", api_key)
            if read is None:
                failed += 1
                continue
            tokens += read.tokens
            for line in read.lines:
                lines.append(
                    LayoutLine(
                        index=0,
                        text=line.text,
                        box=[
                            line.box[0] + region.x0,
                            line.box[1] + ink.top,
                            line.box[2] + region.x0,
                            line.box[3] + ink.top,
                        ],
                        orientation=line.orientation,
                    )
                )
    elapsed = monotonic() - started
    lines.sort(key=_reading_position)
    for idx, line in enumerate(lines):
        line.index = idx
    assembled = Layout(page=page, width=width, height=height, lines=lines, unmatched=[])
    report = RegionsReport(
        page=page,
        regions=len(regions),
        failed_regions=failed,
        lines=len(lines),
        boxless=sum(1 for line in lines if not line.box),
        tokens=tokens,
        elapsed_s=round(elapsed, 1),
    )
    slug = model.replace("/", "-").replace("@", "")
    out = work_dir / batch_id / "ocr-guess" / f"{page}.regions-{slug}.json"
    out.write_text(json.dumps(assembled.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    report_path = work_dir / batch_id / "ocr-guess" / f"{page}.regions-report-{slug}.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    return report


@dataclass(frozen=True, order=True)
class ReadingPosition:
    """Where a line reads on the page: its box's top-left corner, ordered
    top-to-bottom and then left-to-right."""

    top: float
    left: float


def _reading_position(line: LayoutLine) -> ReadingPosition:
    """A line's reading position on the page: its box's top-left corner."""
    box = line.box or [0.0, 0.0, 0.0, 0.0]
    return ReadingPosition(top=box[1], left=box[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval_regions", description="The column-region experiment")
    parser.add_argument("batch_id")
    parser.add_argument("page")
    parser.add_argument("--model", default="z-ai/glm-4.6v")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR)
    args = parser.parse_args(argv)

    report = run(
        args.batch_id,
        args.page,
        args.work_dir,
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key or os.environ.get("OPENROUTER_API_KEY"),
    )
    print(json.dumps(report.to_dict(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
