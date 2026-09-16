"""The gold extractor's contracts (tools/spike_gold.py), pinned on the
committed page-01 fixture (tests/fixtures/page01-wordseg/).

The mapping (gold/expected-mapping.json) is the single source: label ->
word ids, read by the test, the renders and the move verb. The roster of
lines is pinned — a deleted line fails instead of weakening the test.
Band numbers are checked against the mapping (never pixels: reading word
numbers off a picture tests the render, not the change)."""

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
    segment's words come from one yellow line — except the adjudicated
    bottom passes (strokes 38+39, 40+43 are the reviewer's passes of ONE
    line each — "line 40" is fictitious) and the interjection lines.
    """
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
    allowed_pairs = {(38, 39), (40, 43)}  # the adjudicated passes (2026-09-12)
    for segment in build_gold(FIXTURE):
        owners = {stroke_of[rid] for rid in segment["word_ids"] if rid in stroke_of}
        pair_ok = any(len(owners) == 2 and first in owners and second in owners for first, second in allowed_pairs)
        assert len(owners) <= 1 or pair_ok, (
            f"{segment['id']} mixes the words of {len(owners)} yellow lines "
            f"{sorted(owners)} — each yellow line is one segment"
        )


def test_gold_matches_the_adjudicated_mapping() -> None:
    """Every word sits in exactly the line the user confirmed — a regression
    anywhere moves a word and this falls over. The mapping file is the
    single source (gold/expected-mapping.json); the line roster is pinned
    too, so a deleted line fails instead of weakening the test."""
    from tools.spike_gold import load_expected_mapping

    expected = load_expected_mapping()
    assert sorted(expected, key=int) == [str(n) for n in list(range(1, 38)) + [40, 41, 42]], (
        f"line roster changed: {sorted(expected)}"
    )
    segments = build_gold(FIXTURE)
    expected_ids = {i for ids in expected.values() for i in ids}
    actual = {r: seg["id"] for seg in segments for r in seg["word_ids"]}
    for seg, ids in expected.items():
        for word in ids:
            assert actual.get(word) == seg, f"word {word}: got {actual.get(word)}, expected {seg}"
    assert set(actual) == expected_ids, f"claimed set differs: {sorted(set(actual) ^ expected_ids)[:10]}"


def test_each_band_covers_its_words() -> None:
    """The colour must cover the words it labels fully in y — the crush on
    labels 6/10/13 is a known defect (user 2026-09-12)."""
    words = json.loads((FIXTURE / "words.json").read_text(encoding="utf-8"))["words"]
    from tools.spike_gold import _render_ids

    rid = _render_ids(words)
    page_of = {render: page for page, render in rid.items()}
    for segment in build_gold(FIXTURE):
        word_ys = [words[page_of[r]] for r in segment["word_ids"]]
        assert segment["y0"] <= min(w["y0"] for w in word_ys), f"{segment['id']} band starts below its words"
        assert segment["y1"] >= max(w["y1"] for w in word_ys), f"{segment['id']} band ends above its words"


def test_the_bottom_interjection_is_three_lines() -> None:
    """The bottom's small writing, adjudicated (user 2026-09-12): 41 =
    (415, 413, 416, 425), 42 = (428, 430), 43 = (455). 40 is
    the last main line ending at 454 — 455 belongs to 43, never to a
    main line."""
    segments = build_gold(FIXTURE)
    actual = {r: seg["id"] for seg in segments for r in seg["word_ids"]}
    assert actual.get(455) == "43", f"word 455 in {actual.get(455)} — 43's word"
    assert actual.get(430) == "42", f"word 430 in {actual.get(430)} — 42's word"
    mains = [s for s in segments if s["id"] == "40"]
    assert len(mains) == 1 and mains[0]["type"] == "body", "40 must be the single last-main segment"
    assert mains[0]["word_ids"][-1] == 454, f"40 ends at 454, ends {mains[0]['word_ids'][-3:]}"
    got = sorted(r for s in segments if s["id"] in ("41", "42", "43") for r in s["word_ids"])
    expected = [413, 416, 415, 425, 428, 455, 430]
    assert sorted(got) == sorted(expected), f"bottom lines' words: {got} vs {expected}"


def test_the_map_paints_words_not_rectangles() -> None:
    """The map contract (user 2026-09-12): each segment's band is EXACTLY
    the union of its own expected words' boxes — no wider in x, no taller
    in y. The stroke-span rectangle is forbidden: a slightly diagonal
    segment's bbox eats lines above/below in its corners. The renderer
    paints that union via the house tint_row, so a correct band cannot
    mis-paint. NOTE: this checks build_gold's band NUMBERS against the
    mapping, never pixels — cross-checking word numbers on a picture only
    tests the render, not the change."""
    words = json.loads((FIXTURE / "words.json").read_text(encoding="utf-8"))["words"]
    from tools.spike_gold import _render_ids, load_expected_mapping

    expected = load_expected_mapping()
    rid = _render_ids(words)
    page_of = {render: page for page, render in rid.items()}
    covered = {r for ids in expected.values() for r in ids}
    unclaimed = sorted(set(range(1, len(words) + 1)) - covered)
    print(f"\nunclaimed render ids ({len(unclaimed)}): {unclaimed[:40]}")
    for segment in build_gold(FIXTURE):
        if segment["id"] not in expected:
            continue  # bottom small lines have their own test
        ids = expected[segment["id"]]
        want = (
            min(words[page_of[r]]["x0"] for r in ids),
            min(words[page_of[r]]["y0"] for r in ids),
            max(words[page_of[r]]["x1"] for r in ids),
            max(words[page_of[r]]["y1"] for r in ids),
        )
        got = (segment["x0"], segment["y0"], segment["x1"], segment["y1"])
        assert got == want, f"{segment['id']} band {got} != its words' union {want}"
