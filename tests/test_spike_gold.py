"""The gold extractor's contracts (tools/spike_gold.py), pinned on the
committed page-01 fixture (tests/fixtures/page01-wordseg/).

The map contract, ruled by the user (2026-09-12): each segment renders as the
minimal tinted union of its own words, via the house renderer
(tools/render.py::render_rows + tint_row) — joined word boxes only, no
stroke-span rectangles. That minimality is the whole point: a slightly
diagonal segment's bbox rectangle would eat words from the lines above and
below in its corners. EXPECTED_MAPPING below is the word->segment truth the
map check reads.

The other rules: a word belongs to exactly ONE segment; the id space is the
render ids (1..N); the gold is deterministic — terms never shift between
runs."""

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


# THE ADJUDICATED MAPPING, hard-coded (user 2026-09-12): every word's segment
# exactly as confirmed — per-yellow-line segments everywhere; the bottom's
# three main lines merged as they were before the split. The two known
# defects are deliberately NOT pinned here: the band crush and the
# interjection (their own failing tests).
EXPECTED_MAPPING = {
    "1": [
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
    ],
    "2": [
        17,
        18,
        19,
        20,
        21,
    ],
    "3": [
        22,
        23,
        24,
        25,
        26,
        27,
    ],
    "4": [
        34,
        35,
        36,
        37,
        38,
        39,
        40,
        41,
        42,
        43,
        44,
        45,
        46,
        47,
        48,
        49,
        50,
    ],
    "5": [
        52,
        53,
        54,
        55,
        56,
        57,
        58,
        61,
        62,
        63,
        64,
        65,
        66,
        67,
    ],
    "6": [
        59,
        60,
    ],
    "7": [
        69,
        70,
    ],
    "8": [
        75,
        76,
        77,
        78,
        79,
        80,
        81,
        82,
        83,
        84,
        85,
        86,
        87,
        88,
        89,
        90,
    ],
    "9": [
        92,
        94,
        95,
        96,
        97,
        98,
        99,
        101,
        102,
        103,
        104,
    ],
    "10": [
        105,
    ],
    "11": [
        107,
    ],
    "12": [
        110,
        111,
        112,
        114,
        115,
        116,
        117,
        118,
        119,
    ],
    "13": [
        120,
        121,
    ],
    "14": [
        126,
        128,
        129,
        130,
        131,
        132,
        133,
        134,
        135,
        136,
        137,
        138,
        139,
    ],
    "15": [
        140,
        141,
        142,
        143,
        144,
    ],
    "16": [
        146,
        147,
        148,
        149,
        150,
        151,
        152,
        153,
        154,
        155,
        156,
        157,
        158,
    ],
    "17": [
        159,
        160,
        161,
        162,
        163,
        164,
        165,
        166,
        167,
        168,
        169,
        170,
        171,
    ],
    "18": [
        172,
        173,
    ],
    "19": [
        174,
        175,
        176,
        177,
        178,
        179,
        180,
        181,
        182,
        183,
        184,
        185,
        186,
        187,
        188,
        189,
        190,
    ],
    "20": [
        197,
        198,
        199,
        200,
        201,
        202,
        203,
        204,
        205,
        206,
        207,
    ],
    "21": [
        209,
        210,
        211,
        212,
        213,
        214,
        215,
        216,
        217,
        218,
        219,
        220,
        221,
        222,
        223,
        224,
        225,
    ],
    "22": [
        227,
        228,
        229,
        230,
        231,
        232,
        233,
        234,
        235,
        236,
        237,
        238,
        239,
        240,
        241,
        242,
        243,
        244,
        245,
        246,
        247,
    ],
    "23": [
        248,
        249,
        250,
        251,
        252,
    ],
    "24": [
        254,
        255,
        256,
        257,
        258,
    ],
    "25": [
        259,
        260,
        261,
        262,
        263,
        264,
        265,
        266,
        267,
        268,
        269,
        270,
        271,
        272,
    ],
    "26": [
        273,
        274,
        275,
        276,
        277,
        278,
        279,
        280,
        281,
        282,
        283,
        284,
        285,
        286,
        287,
        288,
        289,
        291,
        292,
    ],
    "27": [
        293,
        294,
        295,
        296,
        297,
        298,
    ],
    "28": [
        299,
        300,
        301,
        302,
        303,
        304,
        305,
        307,
        308,
    ],
    "29": [
        309,
        310,
        311,
        312,
        313,
        314,
        316,
        317,
        318,
        319,
        320,
        321,
        322,
        323,
        324,
    ],
    "30": [
        326,
        327,
        328,
        329,
        330,
        331,
        332,
        333,
        334,
        335,
        336,
    ],
    "31": [
        337,
        338,
        339,
        340,
        341,
        342,
        343,
        344,
        345,
        346,
    ],
    "32": [
        347,
        348,
        349,
        350,
        351,
        352,
        353,
        354,
        355,
    ],
    "33": [
        356,
        357,
        358,
        359,
        360,
        361,
        362,
        363,
    ],
    "34": [
        366,
        367,
        368,
        369,
        370,
        371,
        372,
        373,
        374,
        375,
        376,
        377,
        378,
        379,
    ],
    "35": [
        381,
        382,
        383,
        384,
        385,
        386,
        387,
        388,
        389,
    ],
    "36": [
        391,
        392,
        393,
        394,
        395,
        396,
        397,
        398,
        399,
        400,
        401,
        402,
        403,
        404,
        405,
    ],
    "37": [
        406,
        407,
        408,
        409,
        410,
        411,
        412,
        413,
        414,
        415,
        416,
        417,
        418,
        420,
        421,
        423,
        424,
        425,
    ],
    "40": [
        427,
        429,
        431,
        432,
        433,
        434,
        435,
        436,
        437,
        438,
        439,
        440,
        441,
        442,
        443,
        444,
        445,
        446,
        447,
        448,
        449,
        450,
        451,
        452,
        453,
        454,
        455,
    ],
    "41": [415, 413, 416, 425],
    "42": [428, 430],
}


def test_gold_matches_the_adjudicated_mapping() -> None:
    """Every word sits in exactly the segment the user confirmed — a
    regression anywhere moves a word and this falls over. EXPECTED_MAPPING
    is the whole letter including the bottom's line-41/42/43."""
    segments = build_gold(FIXTURE)
    expected_ids = {i for seg in EXPECTED_MAPPING.values() for i in seg}
    actual = {r: seg["id"] for seg in segments for r in seg["word_ids"]}
    for seg, ids in EXPECTED_MAPPING.items():
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
    the union of its own expected words' boxes (EXPECTED_MAPPING, the
    confirmed assignment) — no wider in x, no taller in y. The stroke-span
    rectangle is forbidden: a slightly diagonal segment's bbox eats lines
    above/below in its corners (seg-38 absorbed neighbours; 6/7 lost
    right-side words under clipped corners; the bottom's line-43 tint). The
    renderer then paints that union via the house tint_row (joined word
    boxes), so a correct band cannot mis-paint.

    All three corners — the words no trace covers — stay unclaimed: the
    render must offer the VLM no invented word."""
    words = json.loads((FIXTURE / "words.json").read_text(encoding="utf-8"))["words"]
    from tools.spike_gold import _render_ids

    rid = _render_ids(words)
    page_of = {render: page for page, render in rid.items()}
    covered = {r for ids in EXPECTED_MAPPING.values() for r in ids}
    unclaimed = sorted(set(range(1, len(words) + 1)) - covered)
    print(f"\nunclaimed render ids ({len(unclaimed)}): {unclaimed[:40]}")
    for segment in build_gold(FIXTURE):
        if segment["id"] not in EXPECTED_MAPPING:
            continue  # interjection lines have their own test
        ids = EXPECTED_MAPPING[segment["id"]]
        want = (
            min(words[page_of[r]]["x0"] for r in ids),
            min(words[page_of[r]]["y0"] for r in ids),
            max(words[page_of[r]]["x1"] for r in ids),
            max(words[page_of[r]]["y1"] for r in ids),
        )
        got = (segment["x0"], segment["y0"], segment["x1"], segment["y1"])
        assert got == want, f"{segment['id']} band {got} != its words' union {want}"
