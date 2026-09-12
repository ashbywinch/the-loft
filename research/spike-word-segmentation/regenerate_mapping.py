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
    """Print the adjudicated mapping block. The mapping FILE is the source;
    this only formats it as the old literal looked, for eyeballing diffs."""
    from tools.spike_gold import load_expected_mapping

    expected = load_expected_mapping()
    for seg in sorted(expected, key=int):
        print(f"    {seg!r}: [")
        line = "        "
        for r in expected[seg]:
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
