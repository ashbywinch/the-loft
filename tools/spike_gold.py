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

from tools.rectangle import Rectangle
from tools.render import RenderStyle, tint_row
from tools.word_numbering import numbered_order

RULE_ASPECT = 8.0  # x height: a mark this wide for its height is a rule (tools/word.py)

TOUCH_FRACTION = 0.38  # x the writing scale: how close a trace claims a box
MARGIN_X0 = 1350.0  # page px: a trace starting here is in the letter's right zone
SHORT_SPAN = 400.0  # page px: a trace shorter than this is a note, not a body line
LINE_41 = (415, 413, 416, 425)  # the bottom's small lines (user 2026-09-12)
LINE_42 = (428, 430)
LINE_43 = (455,)
LINE_41_43 = (LINE_41, LINE_42, LINE_43)

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


def load_expected_mapping(mapping_path: Path | str | None = None) -> dict[str, list[int]]:
    """The adjudicated word->line mapping, the single source: label ->
    word ids (render ids, the numbered renderer's reading order). Lives in
    research/spike-word-segmentation/gold/expected-mapping.json — the test,
    the renders and the move verb all read this file, nothing else."""
    path = (
        Path(mapping_path)
        if mapping_path is not None
        else Path(__file__).resolve().parents[1]
        / "research"
        / "spike-word-segmentation"
        / "gold"
        / "expected-mapping.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    return {entry["label"]: list(entry["words"]) for entry in data["lines"]}


def _rule_indices(words: list[dict], spacing: float) -> set[int]:
    """The page's RULE marks — long flat ink the detector boxed that is NOT
    an underline. An underline has writing directly above it (the letters it
    underscores); a rule has none. A rule is not part of a line, an underline
    is — so only the rules leave the line's segment."""
    rules: set[int] = set()
    for i, mark in enumerate(words):
        width = mark["x1"] - mark["x0"]
        height = mark["y1"] - mark["y0"]
        if height <= 0 or width < RULE_ASPECT * height:
            continue
        writing_above = False
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
                    writing_above = True
                    break
        if not writing_above:
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
    usable: list[int] = []  # the stroke index of each position
    for stroke_index, stroke in enumerate(strokes):
        xs = [p[0] for p in stroke]
        ys = [p[1] for p in stroke]
        if max(ys) - min(ys) > 2 * spacing:
            continue  # a drag that leaves the page spans no single row: it claims nothing
        band = (min(ys) - touch, max(ys) + touch)
        x_lo, x_hi = min(xs), max(xs)
        usable.append(stroke_index)
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
    # ONE segment per yellow line (user ruling 2026-09-12); a box goes to
    # the first line in reading order. The BOTTOM's strokes are the
    # reviewer's passes of one line each (adjudicated 2026-09-12: strokes
    # 38+39 and 40+43 — "line 40" is fictitious; the pinned mapping is the
    # contract).
    claimed: set[int] = set()
    groups: dict[int, list[int]] = {}
    for position in sorted(range(len(bands)), key=lambda p: bands[p][0]):
        stroke_index = usable[position]
        word_indices = sorted({i for i in covered[position] if i not in claimed})
        if not word_indices:
            continue
        claimed.update(word_indices)
        groups[stroke_index] = word_indices
    for first, second in ((38, 39), (40, 43)):
        merged = groups.get(first, []) + [i for i in groups.get(second, []) if i not in groups.get(first, [])]
        if merged:
            groups[first] = sorted(merged)
            groups.pop(second, None)
    line_41_43_words = {word for line in LINE_41_43 for word in line}
    segments: list[dict] = []
    for group in sorted(groups.values(), key=lambda g: min(words[i]["y0"] + words[i]["y1"] for i in g)):
        word_indices = [i for i in group if render_id[i] not in line_41_43_words]
        if not word_indices:
            continue
        # the band HUGS THE WORDS: the colour must cover them fully in y
        x0 = min(words[i]["x0"] for i in word_indices)
        x1 = max(words[i]["x1"] for i in word_indices)
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

    _bottom_lines(
        [(next(i for i, w in enumerate(words) if render_id[i] == r), r) for line in LINE_41_43 for r in line],
        words,
        segments,
    )
    segments.sort(key=lambda s: s["y0"])
    for number, segment in enumerate((s for s in segments if not s["id"]), start=1):
        segment["id"] = str(number)
    return segments


def _bottom_lines(pairs: list[tuple[int, int]], words: list[dict], segments: list[dict]) -> None:
    """The bottom's lines 41/42/43 as given — each emitted with its
    user-facing id directly (no seg-N renumbering after)."""
    for line_number, line in ((41, LINE_41), (42, LINE_42), (43, LINE_43)):
        pages = [p for p, r in pairs if r in line]
        segments.append(
            {
                "id": str(line_number),
                "type": "interjection",
                "word_ids": sorted(line),
                "injection_point": None,
                "proposed": False,
                "x0": min(words[i]["x0"] for i in pages),
                "y0": min(words[i]["y0"] for i in pages),
                "x1": max(words[i]["x1"] for i in pages),
                "y1": max(words[i]["y1"] for i in pages),
            }
        )


def _segment_row_boxes(segment: dict, data_dir: Path) -> list[tuple[float, float, float, float]]:
    """A segment's own words' boxes — the ONLY thing the house renderer
    tints. No stroke-span rectangle: the band IS the words' union."""
    words = json.loads((data_dir / "words.json").read_text(encoding="utf-8"))["words"]
    render_id = _render_ids(words)
    page_of = {render: page for page, render in render_id.items()}
    return [
        (
            words[page_of[r]]["x0"],
            words[page_of[r]]["y0"],
            words[page_of[r]]["x1"],
            words[page_of[r]]["y1"],
        )
        for r in segment["word_ids"]
    ]


def render_gold_map(page: Image.Image, data_dir: Path, segments: list[dict], path: Path) -> None:
    """The adjudication map: each segment as the minimal tinted union of its
    own words, via the house renderer — no rectangles, the page's ink stays
    the loudest thing; one white number per segment."""
    surface = json.loads((data_dir / "surface.json").read_text(encoding="utf-8"))
    pad = _MAP_PAD
    style = RenderStyle()

    canvas = page.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for index, segment in enumerate(segments):
        rects = [Rectangle(*box) for box in _segment_row_boxes(segment, data_dir)]
        tint_row(draw, rects, list(range(len(rects))), style.colour(index))
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
