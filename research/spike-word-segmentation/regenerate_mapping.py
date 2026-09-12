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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.spike_gold import _render_ids, build_gold  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "page01-wordseg"


def _main() -> int:
    words = json.loads((FIXTURE / "words.json").read_text(encoding="utf-8"))["words"]
    page = json.loads((FIXTURE / "boxes.json").read_text(encoding="utf-8"))["page"]
    strokes = json.loads((FIXTURE / "strokes.json").read_text(encoding="utf-8"))["strokes"]
    rid = _render_ids(words)
    r_to_p = {r: p for p, r in rid.items()}

    # the mapping = the extractor as adjudicated: every word the user
    # confirmed, with the extractor's own labels, EXCEPT the interjection
    # words (their own test). A change to the extractor that the user has
    # NOT confirmed shows up the moment the pinned test fails against this
    # literal — regenerate only after an adjudication.
    current = build_gold(FIXTURE)
    mapping: dict[int, str] = {}
    for s in current:
        if s["type"] == "interjection":
            continue
        for r in s["word_ids"]:
            mapping[r] = s["id"]

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
