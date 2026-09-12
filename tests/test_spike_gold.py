"""The gold extractor's contracts (tools/spike_gold.py), pinned on the
committed page-01 fixture (tests/fixtures/page01-wordseg/).

The rules the user demanded be validated:

- a word belongs to exactly ONE segment — no double colours on the map;
- one segment is one row — no merged rows painting over other segments;
- the id space is the render ids (1..N, reading order);
- the gold is deterministic — the adjudicator's terms never shift between runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.spike_gold import build_gold

FIXTURE = Path(__file__).parent / "fixtures" / "page01-wordseg"


def _segment_rows(segments: list[dict]) -> list[tuple[str, list[int]]]:
    return [(segment["id"], segment["word_ids"]) for segment in segments]


def test_a_word_belongs_to_exactly_one_segment() -> None:
    """No double-assignment: every word id appears at most once across the
    segments — the map's one-colour-per-segment contract."""
    segments = build_gold(FIXTURE)
    seen: set[int] = set()
    for segment in segments:
        for rid in segment["word_ids"]:
            assert rid not in seen, f"word {rid} assigned to two segments ({segment['id']})"
            seen.add(rid)


def test_word_ids_are_the_render_universe() -> None:
    """The gold speaks render ids: 1..N (the reading order the numbered
    renderer draws), no out-of-range ids."""
    words = json.loads((FIXTURE / "words.json").read_text(encoding="utf-8"))["words"]
    segments = build_gold(FIXTURE)
    universe = range(1, len(words) + 1)
    for segment in segments:
        for rid in segment["word_ids"]:
            assert rid in universe, f"{segment['id']} carries {rid}, outside 1..{len(words)}"


def test_the_gold_is_deterministic() -> None:
    """Two runs give identical segments — the adjudication's terms never
    shift between runs."""
    first = _segment_rows(build_gold(FIXTURE))
    second = _segment_rows(build_gold(FIXTURE))
    assert first == second


def test_gold_matches_the_committed_snapshot() -> None:
    committed_path = Path(__file__).parent.parent / "research" / "spike-word-segmentation" / "gold" / "gold.json"
    committed = json.loads(committed_path.read_text())["segments"]
    current = build_gold(FIXTURE)
    assert current == committed


def test_a_segment_mixes_no_strokes() -> None:
    """Each yellow line maps onto ONE segment (user ruling 2026-09-12): a
    segment's words must all come from a single stroke's covers. This is the
    multicoloured-line bug: the margin strokes were merged INTO the body rows
    (lines 8/9's margin stuff, the 34/35 interjection), so one segment held
    two yellow lines' words."""
    words = json.loads((FIXTURE / "words.json").read_text(encoding="utf-8"))["words"]
    unit = sorted(w["y1"] - w["y0"] for w in words)[len(words) // 2]
    touch = 0.38 * unit
    page = json.loads((FIXTURE / "boxes.json").read_text(encoding="utf-8"))["page"]
    strokes = json.loads((FIXTURE / "strokes.json").read_text(encoding="utf-8"))["strokes"]
    from tools.word_numbering import numbered_order

    order = numbered_order([(w["x0"], w["y0"], w["x1"], w["y1"]) for w in words])
    rid = {page_index: render for render, page_index in enumerate(order, start=1)}
    covers: dict[int, set[int]] = {}
    for stroke_index, stroke in enumerate(strokes):
        xs = [p[0] * page["width"] for p in stroke]
        ys = [p[1] * page["height"] for p in stroke]
        if max(ys) - min(ys) > 2 * unit * 1.6:
            continue
        covers[stroke_index] = {
            rid[i]
            for i, w in enumerate(words)
            if min(xs) <= (w["x0"] + w["x1"]) / 2 <= max(xs)
            and min(ys) - touch <= (w["y0"] + w["y1"]) / 2 <= max(ys) + touch
        }
    stroke_of: dict[int, int] = {}
    for stroke_index, ids in covers.items():
        for rid in ids:
            stroke_of[rid] = stroke_index
    for segment in build_gold(FIXTURE):
        owners = {stroke_of[rid] for rid in segment["word_ids"] if rid in stroke_of}
        assert len(owners) <= 1, (
            f"{segment['id']} mixes the words of {len(owners)} yellow lines "
            f"{sorted(owners)} — each yellow line is one segment"
        )


def test_each_band_covers_its_words() -> None:
    """The colour must cover the words it labels fully in y (user 2026-09-12:
    labels 6/10 were right but their bands were crushed by the old clip) — a
    band's y-extent spans its own words' boxes."""
    words = json.loads((FIXTURE / "words.json").read_text(encoding="utf-8"))["words"]
    from tools.spike_gold import _render_ids

    rid = _render_ids(words)
    page_of = {render: page for page, render in rid.items()}
    for segment in build_gold(FIXTURE):
        word_ys = [words[page_of[r]] for r in segment["word_ids"]]
        assert segment["y0"] <= min(w["y0"] for w in word_ys), f"{segment['id']} band starts below its words"
        assert segment["y1"] >= max(w["y1"] for w in word_ys), f"{segment['id']} band ends above its words"
