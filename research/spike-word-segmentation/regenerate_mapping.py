"""Regenerate the adjudicated word→segment mapping literal in the tests.

The mapping (tests/test_spike_gold.py::EXPECTED_MAPPING) is hard-coded on
purpose — a regression anywhere moves a word and the test falls over. This
script is its provenance: it regenerates the literal from the committed
fixture, applying the user's confirmed structure: per-yellow-line segments
everywhere, with the bottom's three main lines merged (strokes 37, 38+39,
40+43) as they were when the user confirmed them — and the two known defects
(the band crush, the interjection) intentionally left out.

Usage: .venv/bin/python research/spike-word-segmentation/regenerate_mapping.py
Prints the EXPECTED_MAPPING block to replace the one in tests/test_spike_gold.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.spike_gold import _render_ids, build_gold  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "page01-wordseg"


def _main() -> int:
    words = json.loads((FIXTURE / "words.json").read_text(encoding="utf-8"))["words"]
    page = json.loads((FIXTURE / "boxes.json").read_text(encoding="utf-8"))["page"]
    strokes = json.loads((FIXTURE / "strokes.json").read_text(encoding="utf-8"))["strokes"]
    rid = _render_ids(words)
    r_to_p = {r: p for p, r in rid.items()}

    unit = float(np.median([w["y1"] - w["y0"] for w in words]))
    touch = 0.38 * unit

    def covers(stroke_index: int) -> set[int]:
        stroke = strokes[stroke_index]
        xs = [p[0] * page["width"] for p in stroke]
        ys = [p[1] * page["height"] for p in stroke]
        return {
            rid[i]
            for i, w in enumerate(words)
            if min(xs) <= (w["x0"] + w["x1"]) / 2 <= max(xs)
            and min(ys) - touch <= (w["y0"] + w["y1"]) / 2 <= max(ys) + touch
        }

    def band_centre(ids: list[int]) -> float:
        return min((words[r_to_p[r]]["y0"] + words[r_to_p[r]]["y1"]) / 2 for r in ids)

    current = build_gold(FIXTURE)
    keep = [s for s in current if s["y1"] < 4414]  # the confirmed top/middle as-is
    b1 = sorted(covers(37))
    b2 = sorted(covers(38) | (covers(39) - covers(38)))
    b3 = sorted(covers(43) | (covers(40) - covers(43)))
    merged = keep + [{"word_ids": b1}, {"word_ids": b2}, {"word_ids": b3}]
    merged.sort(key=lambda s: band_centre(s["word_ids"]))
    labels = {frozenset(s["word_ids"]): f"seg-{i + 1}" for i, s in enumerate(merged)}
    mapping: dict[int, str] = {}
    for s in merged:
        label = labels[frozenset(s["word_ids"])]
        for r in s["word_ids"]:
            mapping[r] = label

    by_segment: dict[str, list[int]] = {}
    for r, seg in mapping.items():
        by_segment.setdefault(seg, []).append(r)

    print("EXPECTED_MAPPING = {")
    for seg in sorted(by_segment, key=lambda s: int(s.split("-")[1])):
        print(f"    {seg!r}: [")
        line = "        "
        for r in sorted(by_segment[seg]):
            chunk = f"{r}, "
            if len(line) + len(chunk) > 112:
                print(line.rstrip())
                line = "        "
            line += chunk
        print(line.rstrip())
        print("    ],")
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
