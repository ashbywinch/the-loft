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

from tools.word_numbering import unplaced

BATCH = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004")
DEFAULT_PAGE = BATCH / "oriented/page-01.jpg"
DEFAULT_DATA = Path("tests/fixtures/page01-wordseg")
DEFAULT_OUT = Path("research/spike-word-segmentation")
Box = tuple[float, float, float, float]


def _section_from(args: argparse.Namespace, data_dir: Path) -> tuple[float, float, float, float]:
    """The render section: the caller's --section when given, else the letter's
    ink extent from surface.json, padded."""
    if args.section is not None:
        x0, y0, x1, y1 = (float(v) for v in args.section.split(","))
        return (x0, y0, x1, y1)
    surface = json.loads((data_dir / "surface.json").read_text(encoding="utf-8"))
    pad = 60.0
    return (surface["x0"] - pad, surface["y0"] - pad, surface["x1"] + pad, surface["y1"] + pad)


def stage_and_draw(page: Image.Image, data_dir: Path, render: str, section: Box, scale: float) -> tuple:
    """The render pipeline's shared body: words.json -> words.numbered.json
    (the staged render ids, boxes, hues) -> the drawn image + chips. Every
    verb stages through this function, so the file and the pixels are one
    calculation, never two sorts that can drift."""
    from tools.word_numbering import draw_numbering, number_words, place_numbering

    words = json.loads((data_dir / "words.json").read_text(encoding="utf-8"))["words"]
    boxes = [(w["x0"], w["y0"], w["x1"], w["y1"]) for w in words]
    numbered = number_words(boxes)
    (data_dir / "words.numbered.json").write_text(
        json.dumps({"render": render, "section": section, "scale": scale, "words": numbered}, indent=1),
        encoding="utf-8",
    )
    scaled, chips = place_numbering(numbered, section, scale)
    return draw_numbering(page, section, numbered, scaled, chips, scale), chips, len(words)


def render(args: argparse.Namespace) -> int:
    """The numbered section: stage the numbering, draw it, save the image."""
    data_dir = args.data
    page = Image.open(args.page)
    section = _section_from(args, data_dir)
    image, chips, count = stage_and_draw(page, data_dir, args.name, section, args.scale)
    missing = unplaced(chips)
    out_dir = args.out / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{args.name}.png"
    image.save(path)
    print(f"rendered {count} words, section {section}, scale {args.scale} -> {path}")
    print(f"numbering staged -> {data_dir / 'words.numbered.json'}")
    print(f"unplaced chips: {len(missing)}" + (f" (render ids {missing[:20]})" if missing else ""))
    return 0


def map_words(args: argparse.Namespace) -> int:
    """A line's words, addressed by LINE label — never by render id. Prints
    each member with its box, so leftmost/rightmost are readable without
    knowing any id."""
    import json

    from tools.spike_gold import _render_ids, load_expected_mapping

    words = json.loads((args.data / "words.json").read_text(encoding="utf-8"))["words"]
    expected = load_expected_mapping()
    if args.line not in expected:
        print(f"no line {args.line}: roster is {sorted(expected, key=lambda s: (len(s), s))}")
        return 1
    page_of = {render: page for page, render in _render_ids(words).items()}
    for word in sorted(expected[args.line]):
        box = words[page_of[word]]
        print(f"  word {word}: x {box['x0']:.0f}-{box['x1']:.0f} y {box['y0']:.0f}-{box['y1']:.0f}")
    return 0


def map_move(args: argparse.Namespace) -> int:
    """Move words between lines by label: --words 413,416 --to 37. The only
    writer of the mapping file — no hand-editing the literal, no ids beyond
    the move list itself."""
    import json

    from tools.spike_gold import load_expected_mapping

    mapping_path = (
        Path(__file__).resolve().parents[1] / "research" / "spike-word-segmentation" / "gold" / "expected-mapping.json"
    )
    expected = load_expected_mapping(mapping_path)
    moving = [int(v) for v in args.words.split(",")]
    if args.to not in expected:
        print(f"no line {args.to}")
        return 1
    owners = {w: label for label, ids in expected.items() for w in ids}
    for word in moving:
        expected[owners[word]].remove(word)
    for word in moving:  # append in the move-list order, never re-sorted
        if word not in expected[args.to]:
            expected[args.to].append(word)
    mapping_path.write_text(
        json.dumps(
            {"lines": [{"label": label, "words": ids} for label, ids in expected.items()]},
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"moved {moving} -> line {args.to}")
    return 0


def locate(args: argparse.Namespace) -> int:
    """A render id back to its word: box + line, read from the staged
    words.numbered.json — the same file the image was drawn from, so a number
    on the page resolves by lookup, never by re-deriving the sort."""
    staged = json.loads((args.data / "words.numbered.json").read_text(encoding="utf-8"))
    words = json.loads((args.data / "words.json").read_text(encoding="utf-8"))["words"]
    by_render = {entry["render_id"]: entry for entry in staged["words"]}
    for raw in args.words.split(","):
        render_id = int(raw)
        entry = by_render[render_id]
        box = words[entry["page_index"]]
        print(
            f"  word {render_id}: page {entry['page_index']} x {box['x0']:.0f}-{box['x1']:.0f}"
            f" y {box['y0']:.0f}-{box['y1']:.0f} line {box['line']}"
        )
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

    page = Image.open(args.page)
    section = _section_from(args, args.data)
    image, _chips, universe = stage_and_draw(page, args.data, args.name, section, args.scale)
    panel = args.out / "responses" / f"{args.name}.png"
    panel.parent.mkdir(parents=True, exist_ok=True)
    image.save(panel)

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

    words_p = sub.add_parser("map-words", help="list a line's words by line label")
    words_p.add_argument("--data", type=Path, default=DEFAULT_DATA, help="the traced data dir")
    words_p.add_argument("--line", required=True, help="the line label (e.g. 41)")
    words_p.set_defaults(func=map_words)

    move_p = sub.add_parser("map-move", help="move words between lines by label")
    move_p.add_argument("--words", required=True, help="comma-separated word ids, e.g. 413,416")
    move_p.add_argument("--to", required=True, help="the destination line label")
    move_p.set_defaults(func=map_move)

    locate_p = sub.add_parser("locate", help="render ids back to their words' boxes")
    locate_p.add_argument("--data", type=Path, default=DEFAULT_DATA, help="the traced data dir")
    locate_p.add_argument("--words", required=True, help="comma-separated render ids, e.g. 47,72")
    locate_p.set_defaults(func=locate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
