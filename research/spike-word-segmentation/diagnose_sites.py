"""Diagnostic zooms for adjudicating EXPECTED_MAPPING by eye (spike workbench).

Renders each disputed site with the EXPECTED assignment: minimal tint unions
(house tint_row), every word box in its segment's colour with its render id
on it, and the map's positional labels. For the user's eyes AND mine — check
these before touching the extractor.
Usage: .venv/bin/python research/spike-word-segmentation/diagnose_sites.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image, ImageDraw, ImageFont

from tools.rectangle import Rectangle
from tools.render import RenderStyle, tint_row
from tools.word_numbering import numbered_order

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "page01-wordseg"
SCAN = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
OUTDIR = Path(__file__).resolve().parent / "diagnose"

# name -> (x0, y0, x1, y1, scale) in page px
SITES = {
    "site_27_28": (430, 3620, 2150, 3920, 1.5),
    "site_bottom": (430, 4380, 2150, 4642, 1.5),
    "site_67": (1350, 2480, 2150, 2660, 2.0),
    "site_10_11": (1000, 2640, 2150, 2860, 2.0),
    "site_39_40_41": (1300, 4470, 2050, 4642, 2.0),
}


def _load_expected() -> dict[str, list[int]]:
    body = (Path(__file__).resolve().parents[2] / "tests" / "test_spike_gold.py").read_text()
    start = body.index("EXPECTED_MAPPING = {")
    end = body.index("def test_gold_matches_the_adjudicated_mapping")
    ns: dict = {}
    exec("mapping_block = " + body[start:end].replace("EXPECTED_MAPPING = {", "{", 1), {}, ns)
    return ns["mapping_block"]


def _public_render_ids(words: list[dict]) -> dict[int, int]:
    """Page index -> render id (reading order) — the public form of the
    renderer's own numbering."""
    boxes = [(w["x0"], w["y0"], w["x1"], w["y1"]) for w in words]
    return {page: render for render, page in enumerate(numbered_order(boxes), start=1)}


def _order_key(name: str) -> tuple[int, int]:
    """Map labels run seg-1..seg-N in reading order, then the int- lines."""
    match = re.search(r"(\d+)", name)
    number = int(match.group(1)) if match else 999
    return (0 if name.startswith("seg-") else 1, number)


def _main() -> int:
    words = json.loads((FIXTURE / "words.json").read_text())["words"]
    expected = _load_expected()
    order = sorted(expected, key=_order_key)
    label_of = {name: i + 1 for i, name in enumerate(order)}
    render_id = _public_render_ids(words)
    page_of = {render: page for page, render in render_id.items()}
    style = RenderStyle()
    colour_of = {name: style.colour(i)[:3] for i, name in enumerate(order)}

    page = Image.open(SCAN).convert("RGB")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    for site, (x0, y0, x1, y1) in ((k, v[:4]) for k, v in SITES.items()):
        scale = SITES[site][4]
        crop = page.crop((int(x0), int(y0), int(x1), int(y1)))
        w, h = int(crop.width * scale), int(crop.height * scale)
        crop = crop.resize((w, h), Image.Resampling.LANCZOS)
        draw = ImageDraw.Draw(crop, "RGBA")
        owner = {r: name for name, ids in expected.items() for r in ids}
        # tints first (minimal unions, like the expected map)
        for name in order:
            boxes = [
                words[page_of[r]]
                for r in expected[name]
                if x0 < words[page_of[r]]["x1"] and words[page_of[r]]["x0"] < x1
            ]
            if not boxes:
                continue
            rects = [
                Rectangle(
                    (b["x0"] - x0) * scale,
                    (b["y0"] - y0) * scale,
                    (b["x1"] - x0) * scale,
                    (b["y1"] - y0) * scale,
                )
                for b in boxes
            ]
            tint_row(draw, rects, list(range(len(rects))), style.colour(order.index(name)))
        # boxes + render ids
        font = ImageFont.load_default(size=22)
        for r in sorted(owner):
            w = words[page_of[r]]
            if w["x1"] < x0 or w["x0"] > x1 or w["y1"] < y0 or w["y0"] > y1:
                continue
            bx0, by0, bx1, by1 = (
                (w["x0"] - x0) * scale,
                (w["y0"] - y0) * scale,
                (w["x1"] - x0) * scale,
                (w["y1"] - y0) * scale,
            )
            draw.rectangle([bx0, by0, bx1, by1], outline=colour_of[owner[r]] + (255,), width=3)
            draw.text(
                (bx0 + 3, by0 + 2),
                str(r),
                fill=(15, 15, 15),
                stroke_width=2,
                stroke_fill=(255, 255, 255),
                font=font,
            )
        # segment labels
        labelfont = ImageFont.load_default(size=30)
        for name in order:
            xs = [words[page_of[r]]["x0"] for r in expected[name] if x0 < words[page_of[r]]["x1"]]
            ys = [
                (words[page_of[r]]["y0"] + words[page_of[r]]["y1"]) / 2
                for r in expected[name]
                if x0 < words[page_of[r]]["x1"] and words[page_of[r]]["x0"] < x1
            ]
            if not xs or not ys:
                continue
            cx = (min(xs) - x0) * scale
            cy = sum(ys) / len(ys)
            cy = max(y0 + 30, min(y1 - 30, cy))
            cy = (cy - y0) * scale
            label = str(label_of[name])
            tb = draw.textbbox((0, 0), label, font=labelfont)
            draw.rounded_rectangle(
                (cx - 44 - (tb[2] - tb[0]), cy - 18, cx - 30, cy + 18),
                radius=8,
                fill=(255, 255, 255, 255),
                outline=(60, 60, 60, 255),
                width=2,
            )
            draw.text((cx - 40 - (tb[2] - tb[0]), cy - 15), label, fill=(20, 20, 20), font=labelfont)
        out = OUTDIR / f"{site}.png"
        crop.save(out)
        print(f"{site} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
