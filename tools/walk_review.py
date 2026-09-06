"""The layout contact sheets (2026-08-25): every stored layout drawn onto
its own scan — the instrument that catches GEOMETRICALLY wrong but
STRUCTURALLY valid layouts. The gates cannot catch page-01's class of
fault (boxes pass validation yet sit off the handwriting); only eyes
can, and eyes need the boxes rendered on the ink. Born the day the
user asked "will the first page look correct?" and the answer was no.

Usage: PYTHONPATH=. .venv/bin/python -m tools.walk_review [batch_id ...]
Writes work/<batch>/ocr-guess/layout-sheets/<page>.png and prints one
line per boxed page.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

from tools.layout import load_layout_store
from tools.loft_paths import WORK_DIR
from tools.pipeline_store import PipelineStore

MAX_SHEET_WIDTH = 1600  # vision-legible; scans here are 3000-4000px


def annotate_page(image_path: Path, layout: dict, out_path: Path) -> int:
    """Draw the layout's line boxes (red, indexed) on the page image."""
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        scale = min(1.0, MAX_SHEET_WIDTH / im.width)
        if scale < 1.0:
            im = im.resize((round(im.width * scale), round(im.height * scale)))
        draw = ImageDraw.Draw(im)
        n = 0
        for line in layout.get("lines", []):
            box = line.get("box")
            if not box:
                continue
            x0, y0, x1, y1 = (v * scale for v in box)
            draw.rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=3)
            draw.text((x0 + 4, y0 + 2), str(line.get("index", n)), fill=(255, 0, 0))
            n += 1
        out_path.parent.mkdir(parents=True, exist_ok=True)
        im.save(out_path)
        return n


def main(argv: list[str] | None = None) -> int:
    batches = argv if argv else [p.name for p in sorted(WORK_DIR.iterdir()) if p.is_dir()]
    store = PipelineStore(WORK_DIR)
    for batch in batches:
        guess_dir = WORK_DIR / batch / "ocr-guess"
        if not guess_dir.is_dir():
            continue
        sheets = guess_dir / "layout-sheets"
        for layout_path in sorted(guess_dir.glob("*.layout.json")):
            page = layout_path.name.replace(".layout.json", "")
            image_path = WORK_DIR / batch / "oriented" / f"{page}.jpg"
            if not image_path.is_file():
                continue
            try:
                layout = load_layout_store(store, str(layout_path.relative_to(WORK_DIR)))
            except Exception as exc:
                print(f"{batch}/{page}: UNLOADABLE ({exc})")
                continue
            n = annotate_page(image_path, layout, sheets / f"{page}.png")
            print(f"{batch}/{page}: {n} boxes -> {sheets / (page + '.png')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
