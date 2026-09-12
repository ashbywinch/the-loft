"""The VLM word-segmentation spike driver (docs/plans/vlm-word-segmentation-spike.md).

Subcommands land per milestone; each is complete when it ships. The spike's
inputs are artifact-parameterized (page path + data dir), so the postcard and
the handwritten form join by pointing the driver at their traced data.

    render — the numbered-boxes image for a section (milestone 1)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

from tools.word_numbering import render_numbered, unplaced

BATCH = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004")
DEFAULT_PAGE = BATCH / "oriented/page-01.jpg"
DEFAULT_DATA = Path("tests/fixtures/page01-wordseg")
DEFAULT_OUT = Path("research/spike-word-segmentation")


def _section_from(args: argparse.Namespace, data_dir: Path) -> tuple[float, float, float, float]:
    """The render section: the caller's --section when given, else the letter's
    ink extent from surface.json, padded."""
    if args.section is not None:
        x0, y0, x1, y1 = (float(v) for v in args.section.split(","))
        return (x0, y0, x1, y1)
    surface = json.loads((data_dir / "surface.json").read_text(encoding="utf-8"))
    pad = 60.0
    return (surface["x0"] - pad, surface["y0"] - pad, surface["x1"] + pad, surface["y1"] + pad)


def render(args: argparse.Namespace) -> int:
    """One numbered section: the crop, per-word hues, collision-free chips."""
    data_dir = args.data
    words = json.loads((data_dir / "words.json").read_text(encoding="utf-8"))["words"]
    boxes = [(w["x0"], w["y0"], w["x1"], w["y1"]) for w in words]
    page = Image.open(args.page)
    section = _section_from(args, data_dir)
    image, chips = render_numbered(page, section, boxes, args.scale)
    missing = unplaced(chips)
    out_dir = args.out / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{args.name}.png"
    image.save(path)
    print(f"rendered {len(words)} words, section {section}, scale {args.scale} -> {path}")
    print(f"unplaced chips: {len(missing)}" + (f" (render ids {missing[:20]})" if missing else ""))
    return 0


def attempt(args: argparse.Namespace) -> int:
    """One whole-section VLM attempt (milestone 3): render the numbered
    section, prompt in schema v1, call through the house route (cached),
    validate + reconcile the answer, save the response. The gold must be
    adjudicated before the call is worth firing — the command is ready; when
    to run it is the checkpoint."""
    import json

    import tools.vlm_cache as cache
    from tools.spike_vlm_contract import (
        SYSTEM_PROMPT,
        parse_answer,
        reconcile,
        user_prompt,
        validate_segments,
    )
    from tools.vlm import transcribe_image_vlm
    from tools.word_numbering import render_numbered

    words = json.loads((args.data / "words.json").read_text(encoding="utf-8"))["words"]
    boxes = [(w["x0"], w["y0"], w["x1"], w["y1"]) for w in words]
    page = Image.open(args.page)
    section = _section_from(args, args.data)
    image, chips = render_numbered(page, section, boxes, args.scale)
    panel = args.out / "responses" / f"{args.name}.png"
    panel.parent.mkdir(parents=True, exist_ok=True)
    image.save(panel)

    universe = len(words)
    spec = {"model": "dynamic/image", "system": SYSTEM_PROMPT, "user": user_prompt(universe)}
    cached = cache.load_cached_read(panel, spec)
    if cached is not None:
        text, tokens = cached
    else:
        text, usage = transcribe_image_vlm(panel, system=SYSTEM_PROMPT, user_text=user_prompt(universe))
        tokens = usage.get("total_tokens", 0)
        cache.store_read(panel, spec, text, tokens)

    segments = validate_segments(parse_answer(text), universe)
    assigned, problems = reconcile(segments, universe)
    out = {
        "name": args.name,
        "universe": universe,
        "segments": [vars(s) for s in segments],
        "problems": problems,
        "tokens": tokens,
    }
    saved = args.out / "responses" / f"{args.name}.json"
    saved.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"attempt {args.name}: {len(segments)} segments, {tokens} tokens -> {saved}")
    if problems:
        print("reconciliation problems:")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("reconciliation: complete — every rendered word assigned exactly once")
    return 0


def gold(args: argparse.Namespace) -> int:
    """The gold: the yellow traces -> segments, their covered words, proposed
    types. The user adjudicates the proposals before any VLM call (ruling #1,
    the spike plan)."""
    from tools.spike_gold import build_gold, render_gold_map

    data_dir = args.data
    gold_path = args.out / "gold" / "gold.json"
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    segments = build_gold(data_dir)
    gold_path.write_text(json.dumps({"segments": segments}, indent=1), encoding="utf-8")
    page = Image.open(args.page)
    map_path = args.out / "gold" / "gold-map.png"
    render_gold_map(page, data_dir, segments, map_path)
    print(f"gold: {len(segments)} segments -> {gold_path}")
    print(f"gold map -> {map_path}")
    for segment in segments:
        print(
            f"  {segment['id']}: {segment['type']:<12} {len(segment['word_ids']):3d} words  "
            f"y {segment['y0']:.0f}-{segment['y1']:.0f}  x {segment['x0']:.0f}-{segment['x1']:.0f}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    render_p = sub.add_parser("render", help="the numbered-boxes image for a section")
    render_p.add_argument("--page", type=Path, default=DEFAULT_PAGE, help="the scan (archive path)")
    render_p.add_argument("--data", type=Path, default=DEFAULT_DATA, help="the traced data dir")
    render_p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where the artifacts land")
    render_p.add_argument("--name", default="page01-wholepage", help="output file name")
    render_p.add_argument("--scale", type=float, default=1.0, help="section scale (small words need >=2)")
    render_p.add_argument("--section", default=None, help="x0,y0,x1,y1 in page px — default: the letter's surface")
    render_p.set_defaults(func=render)

    gold_p = sub.add_parser("gold", help="the yellow traces -> gold segments (adjudicate first)")
    gold_p.add_argument("--page", type=Path, default=DEFAULT_PAGE, help="the scan (archive path)")
    gold_p.add_argument("--data", type=Path, default=DEFAULT_DATA, help="the traced data dir")
    gold_p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where the artifacts land")
    gold_p.set_defaults(func=gold)

    attempt_p = sub.add_parser("attempt", help="one whole-section VLM attempt (schema v1, cached)")
    attempt_p.add_argument("--page", type=Path, default=DEFAULT_PAGE, help="the scan (archive path)")
    attempt_p.add_argument("--data", type=Path, default=DEFAULT_DATA, help="the traced data dir")
    attempt_p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where the artifacts land")
    attempt_p.add_argument("--name", default="page01-wholepage", help="the attempt's name")
    attempt_p.add_argument("--scale", type=float, default=1.0, help="section scale")
    attempt_p.add_argument("--section", default=None, help="x0,y0,x1,y1 in page px — default: the surface")
    attempt_p.set_defaults(func=attempt)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
