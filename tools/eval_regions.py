"""The column-region experiment (2026-08-22): the ink's x-projection
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
from pathlib import Path
from time import monotonic
from typing import Any

import numpy as np
from PIL import Image

from tools.eval_crop_grid import read_crop
from tools.eval_geometry import CropReading
from tools.loft_paths import WORK_DIR


def _column_regions(image: Path, min_ink: int = 5) -> list[tuple[int, int]]:
    """The ink's column clusters: the x-projection's valleys split the
    content into regions (the postcard's message column vs the address
    column). Returns the x-ranges [x0, x1]."""
    with Image.open(image) as im:
        arr = np.array(im.convert("L"))
    dark = (arr < 140).sum(axis=0)
    threshold = max(dark.max() * 0.05, min_ink)
    ink = dark > threshold
    regions: list[tuple[int, int]] = []
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
                regions.append((start, x - gap))
                start = None
    if start is not None:
        regions.append((start, len(ink) - 1))
    # drop the near-empty regions (the projection noise)
    return [(x0, x1) for x0, x1 in regions if x1 - x0 > 100]


def _ink_y_range(image: Path) -> tuple[int, int]:
    """The ink's row extent — the regions' vertical span."""
    with Image.open(image) as im:
        arr = np.array(im.convert("L"))
    dark = (arr < 140).sum(axis=1)
    rows = np.where(dark > 3)[0]
    if len(rows) == 0:
        return 0, 0
    return int(rows.min()), int(rows.max())


# lucidlint: ignore long-param-list the region run's inputs are the page's state — no class for one call site
def run(
    batch_id: str,
    page: str,
    work_dir: Path,
    model: str = "z-ai/glm-4.6v",
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """The column-region read: the ink's columns as the crops, each read
    at its orientation, the boxes stitched. Returns the report."""
    image_path = work_dir / batch_id / "oriented" / f"{page}.jpg"
    with Image.open(image_path) as im:
        width, height = im.size
    y0, y1 = _ink_y_range(image_path)
    regions = _column_regions(image_path)
    tokens = 0
    failed = 0
    lines: list[dict[str, Any]] = []
    started = monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        for i, (x0, x1) in enumerate(regions):
            crop = CropReading(float(x0), float(y0), float(x1 - x0), float(y1 - y0), [])
            read = read_crop(crop, image_path, Path(tmp), i, model, base_url or "", api_key)
            if read is None:
                failed += 1
                continue
            region_lines, used = read
            tokens += used
            for ln in region_lines:
                box = ln.get("box")
                if box:
                    ln["box"] = [box[0] + x0, box[1] + y0, box[2] + x0, box[3] + y0]
                lines.append(ln)
    elapsed = monotonic() - started
    lines.sort(key=lambda ln: (ln["box"][1], ln["box"][0]))
    for idx, ln in enumerate(lines):
        ln["index"] = idx
    assembled = {
        "page": page,
        "width": width,
        "height": height,
        "lines": lines,
        "unmatched": [],
    }
    report = {
        "page": page,
        "regions": len(regions),
        "failed_regions": failed,
        "lines": len(lines),
        "boxless": sum(1 for ln in lines if not ln.get("box")),
        "tokens": tokens,
        "elapsed_s": round(elapsed, 1),
    }
    slug = model.replace("/", "-").replace("@", "")
    out = work_dir / batch_id / "ocr-guess" / f"{page}.regions-{slug}.json"
    out.write_text(json.dumps(assembled, indent=1, ensure_ascii=False), encoding="utf-8")
    report_path = work_dir / batch_id / "ocr-guess" / f"{page}.regions-report-{slug}.json"
    report_path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


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
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
