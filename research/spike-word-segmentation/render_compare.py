"""Comparison sheets: the blocked cases stacked side by side for the user.

Domain content only (which rendered cases in which group); composition is
tools.page_visuals.stack_sheets + review_image. The case sheets themselves
come from render_split_cases.py — this script only stacks them.
Usage: .venv/bin/python research/spike-word-segmentation/render_compare.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from tools.page_visuals import review_image, stack_sheets

CASES = Path(__file__).resolve().parent / "split-cases"
OUT = Path(__file__).resolve().parent / "evidence"

# comparison name -> the rendered case sheets it stacks, top to bottom
GROUPS = {
    "compare-pair": ["case10_twowords", "case8_oneword"],
    "compare-slivers": ["case15_bug_slivers"],
    "compare-three": ["case11_pair", "case6_oneword", "case9_oneword"],
    "compare-rule": ["case16_rule"],
}


def _main() -> int:
    for name, members in GROUPS.items():
        sheets = [Image.open(CASES / f"{member}.png") for member in members]
        contact = stack_sheets(sheets)
        out = OUT / f"{name}.jpg"
        out.write_bytes(review_image(contact))
        print(f"{name} <- {members} -> {out} ({out.stat().st_size // 1024}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
