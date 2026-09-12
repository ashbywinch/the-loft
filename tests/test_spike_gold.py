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
    "seg-1": [
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
    "seg-2": [
        17,
        18,
        19,
        20,
        21,
    ],
    "seg-3": [
        22,
        23,
        24,
        25,
        26,
        27,
    ],
    "seg-4": [
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
    "seg-5": [
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
    "seg-6": [
        59,
    ],
    "seg-7": [
        69,
    ],
    "seg-8": [
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
    "seg-9": [
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
    "seg-10": [
        105,
    ],
    "seg-11": [
        107,
    ],
    "seg-12": [
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
    "seg-13": [
        120,
        121,
    ],
    "seg-14": [
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
    "seg-15": [
        140,
        141,
        142,
        143,
        144,
    ],
    "seg-16": [
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
    "seg-17": [
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
    "seg-18": [
        172,
        173,
    ],
    "seg-19": [
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
    "seg-20": [
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
    "seg-21": [
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
    "seg-22": [
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
    "seg-23": [
        248,
        249,
        250,
        251,
        252,
    ],
    "seg-24": [
        254,
        255,
        256,
        257,
        258,
    ],
    "seg-25": [
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
    "seg-26": [
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
    ],
    "seg-27": [
        291,
        292,
        293,
        294,
        295,
        296,
        297,
        298,
        299,
        300,
        301,
    ],
    "seg-28": [
        302,
        303,
        304,
        305,
        306,
        307,
        308,
    ],
    "seg-29": [
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
    "seg-30": [
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
    "seg-31": [
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
    "seg-32": [
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
    "seg-33": [
        356,
        357,
        358,
        359,
        360,
        361,
        362,
        363,
    ],
    "seg-34": [
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
    "seg-35": [
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
    "seg-36": [
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
    "seg-37": [
        406,
        407,
        408,
        409,
        410,
        411,
        412,
        414,
        417,
        418,
        419,
        420,
        421,
        422,
        423,
        424,
        426,
    ],
    "seg-40": [
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
    ],
}


def test_gold_matches_the_adjudicated_mapping() -> None:
    """Every word sits in exactly the segment the user confirmed — a
    regression anywhere moves a word and this falls over. The bottom words
    still fail today (the split the user called worse) — that is the pinned
    defect, not a pass."""
    segments = build_gold(FIXTURE)
    expected_ids = {i for seg in EXPECTED_MAPPING.values() for i in seg}
    actual = {r: seg["id"] for seg in segments for r in seg["word_ids"]}
    for seg, ids in EXPECTED_MAPPING.items():
        for word in ids:
            assert actual.get(word) == seg, f"word {word}: got {actual.get(word)}, expected {seg}"
    from tools.spike_gold import INTERJECTION_WORDS

    assert set(actual) == expected_ids | INTERJECTION_WORDS, (
        f"claimed set differs: {sorted(set(actual) ^ (expected_ids | INTERJECTION_WORDS))[:10]}"
    )


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
    """The bottom interjection, adjudicated (user 2026-09-12): the words no
    yellow line colours (413, 416, 415, 425, 428) plus seg-39's last two
    (455, 430) — three lines of small writing, each its own segment."""
    segments = build_gold(FIXTURE)
    interjections = [s for s in segments if s["type"] == "interjection"]
    got = sorted(r for s in interjections for r in s["word_ids"])
    expected = [413, 416, 415, 425, 428, 455, 430]
    assert sorted(got) == sorted(expected), f"interjection words: {got} vs {expected}"
    assert len(interjections) == 3, f"interjection must be three lines, got {len(interjections)}"
