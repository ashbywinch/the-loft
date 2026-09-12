"""The gold extractor for the VLM word-segmentation spike (milestone 2,
docs/plans/vlm-word-segmentation-spike.md).

The apportionment is MECHANICAL (user ruling 2026-09-12):

1. A yellow line covers the boxes its band reaches — a box whose centre sits
   inside the stroke's extent (y ± touch, x) is the trace's box.
2. Strokes on one row (their bands overlap) are ONE segment: each yellow line
   maps onto one segment, all one colour; a row is never mixed.
3. A box goes to the first segment in reading order that covers it.
4. Rule marks (long flat ink with no writing above it) are never claimed — a
   rule is not part of a line; an underline is.
5. The segments' bands are clipped apart at their midpoints, so no two rows
   share a pixel row: one row, one colour, mechanically.

Nothing else: no line-majority guessing, no clustering, no fixed-point
merging. What the traces cover IS the apportionment, pinned by
tests/test_spike_gold.py. Segments carry RENDER ids (reading order 1..N) —
the same ids the numbered renderer draws and the VLM returns.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from tools.render import RenderStyle
from tools.word_numbering import numbered_order

RULE_ASPECT = 8.0  # x height: a mark this wide for its height is a rule (tools/word.py)

TOUCH_FRACTION = 0.38  # x the writing scale: how close a trace claims a box
MARGIN_X0 = 1350.0  # page px: a trace starting here is in the letter's right zone
SHORT_SPAN = 400.0  # page px: a trace shorter than this is a note, not a body line

_MAP_PAD = 60.0  # page px: the map's margin around the letter's surface


def _load(data_dir: Path) -> dict:
    """The spike's inputs, ready for the gold: words, page dims, clamped strokes."""
    words = json.loads((data_dir / "words.json").read_text(encoding="utf-8"))["words"]
    page = json.loads((data_dir / "boxes.json").read_text(encoding="utf-8"))["page"]
    raw_strokes = json.loads((data_dir / "strokes.json").read_text(encoding="utf-8"))["strokes"]
    strokes = [
        [(min(max(x, 0.0), 1.0) * page["width"], min(max(y, 0.0), 1.0) * page["height"]) for x, y in s]
        for s in raw_strokes
    ]
    return {"words": words, "page": page, "strokes": strokes}


def _render_ids(words: list[dict]) -> dict[int, int]:
    """Page word index -> render id (reading order 1..N) — the id space the
    numbered renderer draws and the VLM contract uses."""
    boxes = [(w["x0"], w["y0"], w["x1"], w["y1"]) for w in words]
    return {page_index: render for render, page_index in enumerate(numbered_order(boxes), start=1)}


def _rule_indices(words: list[dict], spacing: float) -> set[int]:
    """The page's RULE marks — long flat ink the detector boxed that is NOT
    an underline. An underline sits directly under the writing it
    underscores: writing above covers at least HALF its span. A rule has no
    such writing (a crossed-out mass, a flourish) — rules are not part of a
    line; underlines are."""
    rules: set[int] = set()
    for i, mark in enumerate(words):
        width = mark["x1"] - mark["x0"]
        height = mark["y1"] - mark["y0"]
        if height <= 0 or width < RULE_ASPECT * height:
            continue
        covered_by = 0.0
        for j, other in enumerate(words):
            if j == i:
                continue
            other_w = other["x1"] - other["x0"]
            other_h = other["y1"] - other["y0"]
            if other_h > 0 and other_w >= RULE_ASPECT * other_h:
                continue  # another long-flat mark is not writing
            if other["x1"] > mark["x0"] and other["x0"] < mark["x1"]:
                gap = mark["y0"] - other["y1"]
                if -spacing <= gap <= spacing:
                    covered_by += min(other["x1"], mark["x1"]) - max(other["x0"], mark["x0"])
        if covered_by < 0.5 * width:
            rules.add(i)
    return rules


def build_gold(data_dir: Path) -> list[dict]:
    """The traces -> [segments], each {id, type, word_ids, injection_point,
    proposed, x0, y0, x1, y1} with word_ids as RENDER ids (reading order).
    ONE segment per yellow line; a box goes to the first line in reading
    order that covers it; rules and drags are never claimed."""
    data = _load(data_dir)
    words = data["words"]
    strokes = data["strokes"]
    render_id = _render_ids(words)

    unit = float(np.median([w["y1"] - w["y0"] for w in words]))
    touch = TOUCH_FRACTION * unit
    spacing = unit * 1.6  # the page's pitch: where one row ends and the next begins
    rules = _rule_indices(words, spacing)

    bands: list[tuple[float, float]] = []
    spans: list[tuple[float, float]] = []
    covered: list[list[int]] = []
    for stroke in strokes:
        xs = [p[0] for p in stroke]
        ys = [p[1] for p in stroke]
        if max(ys) - min(ys) > 2 * spacing:
            continue  # a drag that leaves the page spans no single row: it claims nothing
        band = (min(ys) - touch, max(ys) + touch)
        x_lo, x_hi = min(xs), max(xs)
        bands.append(band)
        spans.append((x_lo, x_hi))
        covered.append(
            [
                i
                for i, w in enumerate(words)
                if i not in rules
                and x_lo <= (w["x0"] + w["x1"]) / 2 <= x_hi
                and band[0] <= (w["y0"] + w["y1"]) / 2 <= band[1]
            ]
        )
    # ONE segment per yellow line — each stroke maps onto exactly one segment
    # (user ruling 2026-09-12); a box goes to the first line in reading order
    claimed: set[int] = set()
    segments: list[dict] = []
    for position in sorted(range(len(bands)), key=lambda p: bands[p][0]):
        word_indices = sorted({i for i in covered[position] if i not in claimed})
        if not word_indices:
            continue
        claimed.update(word_indices)
        x0 = min(spans[position][0], min(words[i]["x0"] for i in word_indices))
        x1 = max(spans[position][1], max(words[i]["x1"] for i in word_indices))
        # the band HUGS THE WORDS: the colour must cover them fully in y
        y0 = min(words[i]["y0"] for i in word_indices)
        y1 = max(words[i]["y1"] for i in word_indices)
        proposed = "marginalia" if x0 >= MARGIN_X0 or (x1 - x0) <= SHORT_SPAN else "body"
        segments.append(
            {
                "id": "",
                "type": proposed,
                "word_ids": sorted(render_id[i] for i in word_indices),
                "injection_point": None,
                "proposed": True,
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
            }
        )

    # the interjection: the SMALL words no yellow line included — the squeezed
    # writing between the main lines, clustered into its own lines by baseline
    # (the user: the bottom's interjection is three lines). Stray fragments
    # and rules stay unclaimed; the interjection is the small writing.
    small = {i for i, w in enumerate(words) if 0 < ((w.get("baseline") or 0) - (w.get("waistline") or 0)) < 0.75 * unit}
    unclaimed_indices = sorted((set(range(len(words))) - claimed - rules) & small)
    if unclaimed_indices:
        by_baseline = sorted(unclaimed_indices, key=lambda i: words[i]["baseline"])
        line: list[int] = []
        previous: float | None = None
        for i in by_baseline:
            baseline = words[i]["baseline"]
            if previous is not None and baseline - previous > 0.6 * spacing:
                _interjection_line(line, words, render_id, segments)
                line = []
            line.append(i)
            previous = baseline
        _interjection_line(line, words, render_id, segments)

    segments.sort(key=lambda s: s["y0"])
    for number, segment in enumerate(segments, start=1):
        segment["id"] = f"seg-{number}"
    return segments


def _interjection_line(indices: list[int], words: list[dict], render_id: dict[int, int], segments: list[dict]) -> None:
    """One interjection line: its words, band hugging them, own segment."""
    if not indices:
        return
    segments.append(
        {
            "id": "",
            "type": "interjection",
            "word_ids": sorted(render_id[i] for i in indices),
            "injection_point": None,
            "proposed": False,  # the interjection needs no adjudication: it is the unclaimed words
            "x0": min(words[i]["x0"] for i in indices),
            "y0": min(words[i]["y0"] for i in indices),
            "x1": max(words[i]["x1"] for i in indices),
            "y1": max(words[i]["y1"] for i in indices),
        }
    )


def render_gold_map(page: Image.Image, data_dir: Path, segments: list[dict], path: Path) -> None:
    """The adjudication map: each segment as ONE translucent band in the
    house palette (semi-transparent background, no borders — the page's ink
    stays the loudest thing), one white number per segment; the bands hug
    the words they cover."""
    surface = json.loads((data_dir / "surface.json").read_text(encoding="utf-8"))
    pad = _MAP_PAD
    style = RenderStyle()

    canvas = page.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for index, segment in enumerate(segments):
        draw.rectangle(
            [segment["x0"], segment["y0"], segment["x1"], segment["y1"]],
            fill=style.colour(index),
        )
    rendered = Image.alpha_composite(canvas, overlay).convert("RGB")
    crop = rendered.crop(
        (int(surface["x0"] - pad), int(surface["y0"] - pad), int(surface["x1"] + pad), int(surface["y1"] + pad))
    )

    label_layer = ImageDraw.Draw(crop)
    font = ImageFont.load_default(size=28)
    for index, segment in enumerate(segments, start=1):
        cx = segment["x0"] - surface["x0"] + pad
        cy = (segment["y0"] + segment["y1"]) / 2 - surface["y0"] + pad
        label = str(index)
        tb = label_layer.textbbox((0, 0), label, font=font)
        label_layer.rounded_rectangle(
            (cx - 30 - (tb[2] - tb[0]), cy - 14, cx - 22, cy + 14),
            radius=6,
            fill=(255, 255, 255),
            outline=(60, 60, 60),
            width=2,
        )
        label_layer.text((cx - 26 - (tb[2] - tb[0]), cy - 12), label, fill=(20, 20, 20), font=font)
    crop.save(path)
