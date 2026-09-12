"""Draw the EXPECTED state: EXPECTED_MAPPING tints via the house renderer.

The map the test pins: every expected segment as the minimal tinted union
of its own words (tint_row), one white number per segment. This is what the
test says is correct — adjudicate THIS, not the extractor's current output.
Usage: .venv/bin/python research/spike-word-segmentation/render_expected_map.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from tools.page import Page
from tools.render import render_rows
from tools.row import Row
from tools.spike_gold import _render_ids
from tools.word import Word

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "page01-wordseg"
OUT = Path(__file__).resolve().parent / "gold" / "expected-map.png"

words = json.loads((FIXTURE / "words.json").read_text(encoding="utf-8"))["words"]
surface = json.loads((FIXTURE / "surface.json").read_text(encoding="utf-8"))
page = Image.open("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")
body = open(Path(__file__).resolve().parents[2] / "tests" / "test_spike_gold.py").read()
start = body.index("EXPECTED_MAPPING = {")
end = body.index("def test_gold_matches_the_adjudicated_mapping")
ns: dict = {}
exec("mapping_block = " + body[start:end].replace("EXPECTED_MAPPING = {", "{", 1), {}, ns)
expected = ns["mapping_block"]
order = sorted(expected, key=lambda s: (0 if s.startswith("seg-") else 1, int(re.search(r"(\d+)", s).group(1)) if re.search(r"(\d+)", s) else 999))
render_id = _render_ids(words)
page_of = {render: page for page, render in render_id.items()}
page_model = Page(
    [
        Word(w["x0"], w["y0"], w["x1"], w["y1"], baseline=w.get("baseline"), waistline=w.get("waistline"))
        for w in words
    ],
    float(np.mean([w["y1"] - w["y0"] for w in words])) * 1.6,
)
rows = [Row(words=sorted(page_of[r] for r in expected[s])) for s in order]
rendered = render_rows(page, page_model, rows)
pad = 60.0
crop = rendered.crop(
    (int(surface["x0"] - pad), int(surface["y0"] - pad), int(surface["x1"] + pad), int(surface["y1"] + pad))
)
draw = ImageDraw.Draw(crop)
font = ImageFont.load_default(size=28)
for index, name in enumerate(order, start=1):
    xs = [words[page_of[r]]["x0"] for r in expected[name]]
    ys = [(words[page_of[r]]["y0"] + words[page_of[r]]["y1"]) / 2 for r in expected[name]]
    cx = min(xs) - surface["x0"] + pad
    cy = sum(ys) / len(ys) - surface["y0"] + pad
    label = str(index)
    tb = draw.textbbox((0, 0), label, font=font)
    draw.rounded_rectangle(
        (cx - 30 - (tb[2] - tb[0]), cy - 14, cx - 22, cy + 14),
        radius=6, fill=(255, 255, 255), outline=(60, 60, 60), width=2,
    )
    draw.text((cx - 26 - (tb[2] - tb[0]), cy - 12), label, fill=(20, 20, 20), font=font)
crop.save(OUT)
print("expected map ->", OUT, "| segments:", len(order))
