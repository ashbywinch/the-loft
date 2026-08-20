"""The layout pass's pure logic (tools/layout.py) — association + confidence.

The detection stage (tools/layout_detect.py) runs PaddleOCR under the
.venv-htr interpreter and is exercised against the real pages separately;
these tests pin the deterministic half: normalization, content-based line
association across reading orders, cross-reader word confidence, and the
published layout shape.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from tools.layout import (
    MATCH_THRESHOLD,
    Detection,
    associate_lines,
    build_layout,
    layout_detections,
    load_layout,
    normalize,
    rotate_detections,
    word_conf,
    words,
    write_layout,
)


def _det(box: list[float], text: str, score: float = 0.9) -> Detection:
    return Detection(box=box, text=text, score=score, words=[])


class TestNormalize:
    def test_case_and_whitespace(self) -> None:
        assert normalize("  Hello   WORLD ") == "hello world"

    def test_punctuation_stripped(self) -> None:
        # periods space the token (the P.S.I / P.S. I artifact), apostrophes
        # join it (the rec drops them), other punctuation vanishes
        assert normalize("P.S.] I had — a whole 'Grade 3A'!") == "p s i had a whole grade 3a"

    def test_apostrophe_joins(self) -> None:
        assert normalize("t'écrivons") == normalize("tecrivons")

    def test_split_artifact_normalizes(self) -> None:
        # the spike's P.S.I vs P.S. I: punctuation-only differences vanish
        assert normalize("P.S.I") == normalize("P.S. I")

    def test_diacritics_stripped(self) -> None:
        # the rec model loses accents — Chère must compare equal to Chere
        assert normalize("Chère") == normalize("Chere")

    def test_letter_confusion_survives(self) -> None:
        # the rec model's letter confusions ARE the flag signal
        assert normalize("Aloxandra") != normalize("Alexandra")


class TestWords:
    def test_tokens(self) -> None:
        assert words("Nous t'écrivons") == ["nous", "tecrivons"]

    def test_empty(self) -> None:
        assert words("!!!") == []


class TestAssociateLines:
    def test_reading_order_independent(self) -> None:
        # the engines read the page in different orders — content must win
        vlm = ["Chère Maman", "The body of the letter follows", "Postmark 27.9.63"]
        dets = [
            _det([0, 100, 100, 120], "Postmark 27.9.63"),  # detector reads the address FIRST
            _det([0, 200, 100, 220], "Chère Maman"),
            _det([0, 300, 100, 320], "The body of the letter follows"),
        ]
        matches, unmatched = associate_lines(vlm, dets)
        assert unmatched == []
        by_index = {m["vlm_index"]: m for m in matches}
        assert by_index[0]["rec_text"] == "Chère Maman"
        assert by_index[2]["rec_text"] == "Postmark 27.9.63"
        # matches come back in VLM line order
        assert [m["vlm_index"] for m in matches] == [0, 1, 2]

    def test_noisy_rec_text_tolerated(self) -> None:
        # the rec text noise is the confidence signal — the matcher must
        # still anchor lines whose overlap clears the threshold
        vlm = ["my fiist theory besson today", "a completely different line"]
        dets = [_det([0, 0, 10, 10], "my fiist theory besson today.")]
        matches, unmatched = associate_lines(vlm, dets)
        assert len(matches) == 1
        assert matches[0]["vlm_index"] == 0
        assert unmatched == []

    def test_below_threshold_fills_positionally(self) -> None:
        # the rec text never matched — the fallback still anchors the line
        # with the detection's geometry (2026-08-16: cursive pages never
        # content-match; the box is real, the text anchor is not)
        vlm = ["the quick brown fox"]
        dets = [_det([0, 0, 10, 10], "zzz qqq wwww eeee rrrr")]
        matches, unmatched = associate_lines(vlm, dets)
        assert len(matches) == 1
        assert matches[0]["box_source"] == "positional"
        assert matches[0]["box"] == [0, 0, 10, 10]
        assert unmatched == []

    def test_one_to_one_each_direction(self) -> None:
        # one VLM line may not claim two detector lines — the second
        # detector fills the second line positionally
        vlm = ["line alpha", "line beta"]
        dets = [
            _det([0, 0, 10, 10], "line alpha"),
            _det([0, 20, 10, 30], "line alpha"),
        ]
        matches, unmatched = associate_lines(vlm, dets)
        assert len(matches) == 2
        sources = sorted(m["box_source"] for m in matches)
        assert sources == ["content", "positional"]
        assert unmatched == []

    def test_positional_fill_is_reading_order(self) -> None:
        # the k-th boxless VLM line takes the k-th unmatched detection by
        # y-top, whatever the detection order in the input
        vlm = ["line one", "line two", "line three"]
        dets = [
            _det([0, 200, 10, 210], "noise zzz"),
            _det([0, 0, 10, 10], "noise yyy"),
            _det([0, 100, 10, 110], "noise xxx"),
        ]
        matches, unmatched = associate_lines(vlm, dets)
        by_index = {m["vlm_index"]: m for m in matches}
        assert by_index[0]["box"][1] == 0
        assert by_index[1]["box"][1] == 100
        assert by_index[2]["box"][1] == 200
        assert unmatched == []

    def test_extra_detections_stay_unmatched(self) -> None:
        vlm = ["only line"]
        dets = [
            _det([0, 0, 10, 10], "only line"),
            _det([0, 100, 10, 110], "extra region"),
            _det([0, 200, 10, 210], "another extra"),
        ]
        matches, unmatched = associate_lines(vlm, dets)
        assert len(matches) == 1
        assert len(unmatched) == 2

    def test_content_match_never_overridden(self) -> None:
        # the fallback fills only BOXLESS lines — a content anchor always
        # wins over the reading-order assignment
        vlm = ["line alpha", "line beta"]
        dets = [
            _det([0, 0, 10, 10], "line alpha"),
            _det([0, 50, 10, 60], "line beta"),
            _det([0, 200, 10, 210], "stray mark"),
        ]
        matches, unmatched = associate_lines(vlm, dets)
        by_index = {m["vlm_index"]: m for m in matches}
        assert by_index[0]["box_source"] == "content"
        assert by_index[1]["box_source"] == "content"
        assert unmatched == [dets[2]]


class TestWordConf:
    def test_agreement_flags_confusions(self) -> None:
        # the spike: fiist vs first, befoe vs before flag
        confs = word_conf(["fiist", "theory", "befoe"], ["first", "theory", "before"])
        assert confs == [0.0, 1.0, 0.0]

    def test_accent_insensitive_agreement(self) -> None:
        confs = word_conf(["Chère", "Maman"], ["Chere", "Maman"])
        assert confs == [1.0, 1.0]

    def test_extra_rec_words_do_not_flag(self) -> None:
        confs = word_conf(["had", "a", "whole"], ["had", "a", "whole", "grade"])
        assert confs == [1.0, 1.0, 1.0]

    def test_missing_vlm_word_flags(self) -> None:
        confs = word_conf(["P.S.]", "I", "had"], ["I", "had"])
        assert confs == [0.0, 1.0, 1.0]


class TestBuildLayout:
    def test_shape_and_order(self) -> None:
        vlm = "Chère Maman,\nNous t'écrivons pour te dire que tout va bien"
        dets = [
            _det([0, 100, 100, 120], "Nous tecrivons pour te dire que tout va bien"),
            _det([0, 50, 100, 70], "Chere Maman,"),
            _det([300, 400, 400, 420], "orphan detection line"),
        ]
        layout = build_layout("page-03.jpg", 1000, 500, vlm, dets)
        assert layout["page"] == "page-03.jpg"
        assert layout["width"] == 1000
        assert layout["height"] == 500
        assert [line["text"] for line in layout["lines"]] == [
            "Chère Maman,",
            "Nous t'écrivons pour te dire que tout va bien",
        ]
        # the first line matched the detector's box
        assert layout["lines"][0]["box"] == [0, 50, 100, 70]
        assert layout["lines"][0]["words"][0] == {"word": "Chère", "box": None, "conf": 1.0}
        # the unmatched detector line rides along with conf 0
        assert layout["unmatched"] == [{"box": [300, 400, 400, 420], "text": "orphan detection line", "conf": 0.0}]

    def test_unmatched_vlm_line_has_no_box(self) -> None:
        vlm = "line one\nline two that no detector line claims"
        dets = [_det([0, 0, 10, 10], "line one")]
        layout = build_layout("p.jpg", 100, 100, vlm, dets)
        assert layout["lines"][1]["box"] is None
        assert layout["lines"][1]["conf"] == 0.0
        assert all(w["conf"] == 0.0 for w in layout["lines"][1]["words"])

    def test_blank_lines_skipped(self) -> None:
        vlm = "\nline one\n\nline two\n"
        dets = [_det([0, 0, 10, 10], "line one"), _det([0, 20, 10, 30], "line two")]
        layout = build_layout("p.jpg", 100, 100, vlm, dets)
        assert len(layout["lines"]) == 2


class TestSelfReportFlags:
    """The flag source the user approved (2026-08-15): the transcription
    model's own doubt, not the noisy cross-reader agreement."""

    VLM = "line one here\nsecond line with a doubtful word"

    def test_selfreport_drives_the_flags(self) -> None:
        dets = [_det([0, 0, 10, 10], "line one here"), _det([0, 20, 10, 30], "second line with a doubtful word")]
        report = [{"line": 1, "word": "one"}, {"line": 2, "word": "doubtful"}]
        layout = build_layout("p.jpg", 100, 100, self.VLM, dets, selfreport=report)
        confs = [w["conf"] for line in layout["lines"] for w in line["words"]]
        # "one" and "doubtful" flag; the rest are the model's confident words
        assert layout["lines"][0]["words"][1] == {"word": "one", "box": None, "conf": 0.0}
        assert layout["lines"][1]["words"][-2] == {"word": "doubtful", "box": None, "conf": 0.0}
        assert sum(1 for c in confs if c == 0.0) == 2

    def test_struck_words_always_flag(self) -> None:
        vlm = "a ~~reading~~ lamp"
        dets = [_det([0, 0, 10, 10], "a reading lamp")]
        layout = build_layout("p.jpg", 100, 100, vlm, dets, selfreport=[])
        struck = next(w for w in layout["lines"][0]["words"] if "reading" in w["word"])
        assert struck["conf"] == 0.0
        # a clear word does not flag under an empty self-report
        assert layout["lines"][0]["words"][0]["conf"] == 1.0

    def test_no_selfreport_falls_back_to_cross_reader(self) -> None:
        # backward compatible: without a self-report the cross-reader
        # agreement drives the flags (the pre-2026-08-15 behavior)
        vlm = "the quick brown fiist theory"
        dets = [_det([0, 0, 10, 10], "the quick brown first theory")]
        layout = build_layout("p.jpg", 100, 100, vlm, dets)
        confs = [w["conf"] for w in layout["lines"][0]["words"]]
        assert confs == [1.0, 1.0, 1.0, 0.0, 1.0]  # fiist disagrees, the rest agree

    def test_selfreport_line_numbers_are_one_based(self) -> None:
        # the model cites 1-based lines; the layout lines are 0-based
        dets = [_det([0, 0, 10, 10], "line one here"), _det([0, 20, 10, 30], "second line")]
        report = [{"line": 2, "word": "second"}]
        layout = build_layout("p.jpg", 100, 100, self.VLM, dets, selfreport=report)
        assert layout["lines"][1]["words"][0]["conf"] == 0.0
        assert layout["lines"][0]["words"][0]["conf"] == 1.0

    def test_out_of_range_and_junk_entries_ignored(self) -> None:
        dets = [_det([0, 0, 10, 10], "line one here")]
        report = [{"line": 99, "word": "nope"}, {"line": "x", "word": "y"}, {"word": "no-line"}]
        layout = build_layout("p.jpg", 100, 100, "line one here", dets, selfreport=report)
        assert all(w["conf"] == 1.0 for w in layout["lines"][0]["words"])


class TestWriteLoadLayout:
    def test_atomic_round_trip(self, tmp_path) -> None:
        layout = build_layout("p.jpg", 100, 100, "one line", [_det([0, 0, 100, 20], "one line")])
        path = tmp_path / "p.layout.json"
        write_layout(layout, path)
        assert json.loads(path.read_text(encoding="utf-8")) == layout
        assert load_layout(path) == layout


class TestRotateDetections:
    """The reviewer's orientation fix re-anchors the boxes by a rigid remap
    (2026-08-16) — the rotation must be exact and order-preserving."""

    def test_identity(self) -> None:
        dets = [_det([10, 20, 30, 40], "text")]
        assert rotate_detections(dets, 0, 100, 200) == dets

    def test_90_cw(self) -> None:
        dets = [_det([10, 20, 30, 40], "text")]
        # 90° CW in a 100×200 image: (x, y) -> (h - y, x)
        out = rotate_detections(dets, 1, 100, 200)
        assert out[0]["box"] == [160, 10, 180, 30]  # [200-40, 10, 200-20, 30]
        assert out[0]["text"] == "text"

    def test_180(self) -> None:
        dets = [_det([10, 20, 30, 40], "text")]
        out = rotate_detections(dets, 2, 100, 200)
        assert out[0]["box"] == [70, 160, 90, 180]  # [100-30, 200-40, 100-10, 200-20]

    def test_270_cw(self) -> None:
        dets = [_det([10, 20, 30, 40], "text")]
        out = rotate_detections(dets, 3, 100, 200)
        assert out[0]["box"] == [20, 70, 40, 90]  # [y0, w-x1, y1, w-x0]

    def test_reading_order_preserved(self) -> None:
        # two boxes in y-order stay in the same relative order after 90° CW
        # (a rigid rotation preserves the reading axis)
        dets = [_det([0, 0, 10, 10], "first"), _det([0, 100, 10, 110], "second")]
        out = rotate_detections(dets, 1, 100, 200)
        tops = [d["box"][1] for d in out]
        assert tops == sorted(tops)
        assert out[0]["text"] == "first"


class TestLayoutDetections:
    def test_reconstruction_round_trip(self) -> None:
        layout = build_layout(
            "p.jpg",
            100,
            100,
            "line one\nline two",
            [_det([0, 0, 10, 10], "line one"), _det([0, 50, 10, 60], "noise")],
        )
        dets = layout_detections(layout)
        assert len(dets) == 2
        by_box = {tuple(d["box"]): d for d in dets}
        assert by_box[(0, 0, 10, 10)]["text"] == "line one"
        assert by_box[(0, 50, 10, 60)]["text"] == "noise"
        # re-running the association on the reconstruction reproduces the layout
        rebuilt = build_layout("p.jpg", 100, 100, "line one\nline two", dets)
        assert rebuilt["lines"][0]["box"] == layout["lines"][0]["box"]
        assert rebuilt["lines"][0]["box_source"] == layout["lines"][0]["box_source"]


def test_threshold_is_named() -> None:
    # the matcher's tolerance is a named constant — not a magic number
    assert isinstance(MATCH_THRESHOLD, float)
    assert 0.0 < MATCH_THRESHOLD < 1.0


def test_build_layout_uses_the_vlm_boxes_when_present(tmp_path: Path) -> None:
    """The VLM's OWN per-line boxes anchor the lines (normalized 0-1000 ->
    image px) — the rec association is skipped for them. Without geometry
    the page keeps the old association (2026-08-16: the geometry must come
    from the model that READ the page, not the rec that merges lines)."""
    from tools.layout import build_layout

    vlm_text = "piano-practising facilities. At the\nmoment it looks awfully complicated,"
    layout = build_layout(
        "p1.jpg",
        1000,
        2000,
        vlm_text,
        [],  # no detections at all — the VLM geometry stands alone
        vlm_boxes={0: [219, 496, 760, 526], 1: [234, 513, 733, 543]},
    )
    assert layout["lines"][0]["box"] == [219.0, 992.0, 760.0, 1052.0]  # x*1000/1000, y*2000/1000
    assert layout["lines"][0]["box_source"] == "vlm"
    assert layout["lines"][1]["box_source"] == "vlm"
    # a line the VLM gave no box for falls back to the old association
    assert layout["lines"][0]["text"] == "piano-practising facilities. At the"


def test_build_layout_without_vlm_boxes_keeps_the_association(tmp_path: Path) -> None:
    from tools.layout import build_layout

    vlm_text = "line one\nline two"
    layout = build_layout("p1.jpg", 100, 200, vlm_text, [])
    assert layout["lines"][0]["box"] is None  # no detections, no geometry — boxless
    assert layout["lines"][0].get("box_source") is None  # no anchor, no source label


def test_load_vlm_boxes_reads_the_sidecar(tmp_path: Path) -> None:
    from tools.layout import load_vlm_boxes

    p = tmp_path / "p1.vlm.json"
    p.write_text(
        '{"total_tokens": 11000, "lines": [{"text": "a", "box": [1, 2, 3, 4]}, {"text": "b", "box": [5, 6, 7, 8]}]}',
        encoding="utf-8",
    )
    assert load_vlm_boxes(p) == {0: [1.0, 2.0, 3.0, 4.0], 1: [5.0, 6.0, 7.0, 8.0]}
    assert load_vlm_boxes(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert load_vlm_boxes(bad) is None
    nolines = tmp_path / "nolines.json"
    nolines.write_text('{"total_tokens": 5}', encoding="utf-8")
    assert load_vlm_boxes(nolines) is None


def test_layout_detections_keeps_the_vlm_text_as_the_anchor(tmp_path: Path) -> None:
    """The rotation's rebuild re-associates VLM-anchored lines exactly —
    their OWN text is the content anchor (no rec text exists for them)."""
    from tools.layout import build_layout, layout_detections

    layout = build_layout(
        "p1.jpg",
        1000,
        2000,
        "line one\nline two",
        [],
        vlm_boxes={0: [0, 0, 100, 100]},
    )
    dets = layout_detections(layout)
    assert dets[0]["text"] == "line one"
    assert dets[0]["box"] == layout["lines"][0]["box"]


def test_admission_gate_requires_real_text_at_the_orientation() -> None:
    """A line is admitted only when the recognizer read real text:
    confidence AND plausibility — never on box shape alone (VR15)."""
    from tools.layout import admission_gate

    assert admission_gate("HERNSPETH HOUSE", 0.93)
    assert not admission_gate("mo", 0.5)  # two letters but low confidence
    assert not admission_gate("m", 0.99)  # confident but a single letter
    assert not admission_gate("", 0.99)


def test_remap_box_maps_back_to_the_original_frame() -> None:
    """A 90° pass's rotated-frame box maps back to the original image —
    the top of the rotated frame is the original's right edge."""
    from tools.layout import remap_box

    # 200x100 original; rotated -90° (clockwise, expand) the frame is
    # 100x200. A box at the top of the rotated frame (centered) lands on
    # the original's right edge, vertically centered.
    box = remap_box([40, 0, 60, 20], 90, (200, 100), (100, 200))
    assert box[2] > 195  # the far edge touches the right side (200)
    assert 30 < box[1] < 70 and 30 < box[3] < 70  # y near the center (50)


def test_admit_and_remap_keeps_only_real_text() -> None:
    """The recognition-driven admission: real words at the orientation
    are kept and remapped; garbage (single letters, low confidence) is
    rejected — its box is NOT remapped (no claimed geometry)."""
    from tools.layout import admit_and_remap

    dets: list[Detection] = [
        {"box": [40, 0, 60, 20], "text": "HERNSPETH HOUSE", "score": 0.93, "words": []},
        {"box": [0, 0, 10, 10], "text": "mo", "score": 0.5, "words": []},
        {"box": [5, 5, 15, 15], "text": "HERNSPETH HOUSE", "score": 0.5, "words": []},
        {"box": [10, 10, 20, 20], "text": "m", "score": 0.99, "words": []},
    ]
    kept, rejected = admit_and_remap(dets, 90, (200, 100), (100, 200))
    assert len(kept) == 1
    assert kept[0]["text"] == "HERNSPETH HOUSE"
    assert kept[0]["box"][2] > 195  # remapped to the original frame (right edge)
    assert len(rejected) == 3


def test_multi_layout_words_carry_text_and_flag_weak_lines() -> None:
    """The multi-orientation layout's words are reviewable (2026-08-17):
    each word carries its TEXT (the review renders word.word — a word
    without it renders blank) and a line the rec read weakly flags its
    words (conf 0.0 — the red doubt + the mark-fine button, VR4). The
    reproduced fault: the combined layout's words were {box, conf} only —
    the postcard's review showed blank lines and no check buttons."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        200,
        100,
        [
            (
                0,
                [
                    {
                        "text": "weak line",
                        "box": [1, 1, 5, 5],
                        "score": 0.9,
                        "words": [{"box": [1, 1, 2, 2]}, {"box": [3, 1, 5, 2]}],
                    }
                ],
            ),
            (
                270,
                [{"text": "clean", "box": [10, 10, 20, 20], "score": 1.0, "words": [{"box": [10, 10, 20, 20]}]}],
            ),
        ],
    )
    weak = layout["lines"][0]
    assert [w["word"] for w in weak["words"]] == ["weak", "line"]
    assert all(w["conf"] == 0.0 for w in weak["words"])  # the doubt + the check button
    clean = layout["lines"][1]
    assert clean["words"][0]["word"] == "clean"
    assert clean["words"][0]["conf"] == 1.0  # a confident read stays clean


def test_multi_layout_orientation_comes_from_the_pass_not_the_report() -> None:
    """The line's reading orientation is the PASS where the rec read it
    (the detector's detection pass), not the report's estimated degrees.
    The report can say 90° while the 270° pass actually read the text —
    the per-line rotation must use 270° (so the viewRotation makes the
    text readable). The reproduced fault (2026-08-17): the report's 90°
    made the per-line rotation 180° off, leaving the text unreadable."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        1000,
        1000,
        [
            (0, [{"text": "POST CARD", "box": [101, 51, 299, 99], "score": 0.99, "words": []}]),
            (270, [{"text": "onorrow", "box": [501, 201, 899, 399], "score": 0.9, "words": []}]),
        ],
        report_lines=[
            {"index": 0, "box": [100, 50, 300, 100], "degrees": 0},
            {"index": 1, "box": [500, 200, 900, 400], "degrees": 90},  # the report says 90°
        ],
        vlm_text="POST CARD\nWe are from beauford",
    )
    message = [ln for ln in layout["lines"] if "beauford" in ln["text"]]
    assert message, "the message line must be present"
    assert message[0]["orientation"] == 270, (
        f"the orientation must be 270 (the pass that read it), was {message[0]['orientation']}"
    )


def test_multi_layout_anchors_the_vlm_text_to_its_own_boxes() -> None:
    """VR14: every piece of text has a bounding box, and the box holds the
    words it claims (2026-08-17 — the reproduced fault: the lines carried
    the rec's fragments mispaired with the det's boxes, so the review's
    text was nonsense and the boxes didn't match the words). With the
    model's per-line geometry the lines ARE the model's transcription
    anchored to its own boxes; a rec detection agreeing on content marks
    the line confident; rec lines no VLM line claims stay as flagged
    extras — and the fragment duplicates of an anchored line drop (the
    dedupe keeps the richer reading)."""
    from tools.layout import multi_layout

    report_lines = [
        {"text": "POST CARD", "box": [100, 50, 300, 100], "degrees": 0},
        {"text": "Printed in Great Britain", "box": [100, 110, 400, 140], "degrees": 0},
        {"text": "We are from beauford", "box": [500, 200, 900, 400], "degrees": 270},
    ]
    passes = [
        (
            0,
            [
                {"text": "POST CARD", "box": [101, 51, 299, 99], "score": 0.99, "words": []},
                {"text": "Printed in Great Britain", "box": [101, 111, 399, 139], "score": 0.98, "words": []},
                {"text": "HERNSPETH", "box": [150, 500, 200, 900], "score": 0.95, "words": []},  # the model missed this
            ],
        ),
        (
            270,
            [
                {  # the rec's fragment of the message
                    "text": "onorrow",
                    "box": [501, 201, 899, 399],
                    "score": 0.9,
                    "words": [],
                },
            ],
        ),
    ]
    layout = multi_layout("p1.jpg", 1000, 1000, passes, report_lines=report_lines)
    texts = [ln["text"] for ln in layout["lines"]]
    # physical reading order (2026-08-20): the reading-start corner sorts
    # top-to-bottom — POST CARD (y50), Printed (y110), the 270° message
    # (start y400), then the extra HERNSPETH (y500). The fragment duplicate
    # of the anchored message line drops.
    assert texts == ["POST CARD", "Printed in Great Britain", "We are from beauford", "HERNSPETH"]
    by_text = {ln["text"]: ln for ln in layout["lines"]}
    # every line has a box; the anchored lines carry the MODEL's box (scaled
    # from the normalized 0-1000 frame) — the box holds the words it claims
    assert by_text["POST CARD"]["box"] == [100.0, 50.0, 300.0, 100.0]
    assert all(ln["box"] for ln in layout["lines"])
    # the rec agreed on the header -> confident; the message -> the rec's
    # fragment did not agree -> flagged (the honest doubt)
    assert all(w["conf"] == 1.0 for w in by_text["POST CARD"]["words"])
    assert all(w["conf"] == 0.0 for w in by_text["We are from beauford"]["words"])
    assert by_text["We are from beauford"]["orientation"] == 270
    # the model-missed rec line stays, flagged, at its pass orientation
    assert by_text["HERNSPETH"]["orientation"] == 0
    assert all(w["conf"] == 0.0 for w in by_text["HERNSPETH"]["words"])


def test_dedupe_drops_fragment_duplicates_by_content() -> None:
    """The fragment extras (2026-08-17 — the real postcard's 'HOUSE,' next
    to 'HERNSPETH HOUSE,' and 'Printed' next to 'Printed in Great
    Britain'): a short line whose tokens are a strict subset of another
    line's is the same text read as a fragment — dropped even when the
    mirror passes' remaps landed its box elsewhere (the box-overlap rule
    alone misses them)."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        1000,
        1000,
        [
            (
                0,
                [
                    {"text": "Printed in Great Britain", "box": [100, 100, 500, 140], "score": 0.98, "words": []},
                    {
                        "text": "Printed",
                        "box": [600, 300, 700, 340],
                        "score": 0.97,
                        "words": [],
                    },  # the fragment, far away
                ],
            ),
            (
                270,
                [
                    {"text": "HERNSPETH HOUSE,", "box": [100, 500, 200, 900], "score": 0.99, "words": []},
                    {"text": "HOUSE,", "box": [400, 500, 500, 900], "score": 0.95, "words": []},  # the fragment
                ],
            ),
        ],
    )
    texts = [ln["text"] for ln in layout["lines"]]
    assert "Printed" not in texts
    assert "HOUSE," not in texts
    assert "Printed in Great Britain" in texts
    assert "HERNSPETH HOUSE," in texts


def test_dedupe_never_drops_the_anchored_report_lines() -> None:
    """The box-overlap dedupe is for the REC extras — the anchored lines
    are the model's authoritative transcription, and its estimated boxes
    can overlap between DISTINCT lines (2026-08-17: the eval caught
    'POST CARD.' being dropped when the model's 180° box overlapped a
    longer line's box)."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        1000,
        1000,
        [],
        report_lines=[
            {"text": "POST CARD.", "box": [100, 100, 900, 140], "degrees": 0},
            {"text": "ONLY THE ADDRESS TO BE WRITTEN HERE.", "box": [100, 101, 900, 160], "degrees": 0},
        ],
    )
    texts = [ln["text"] for ln in layout["lines"]]
    assert "POST CARD." in texts  # a real line survives even when its box overlaps
    assert "ONLY THE ADDRESS TO BE WRITTEN HERE." in texts


def test_multi_layout_uses_the_guess_text_located_by_the_report() -> None:
    """v3 (2026-08-17): the layout's text is the GUESS's authoritative
    transcription; the report LOCATES each line (box + degrees keyed by
    the line index) — a partial report degrades only the geometry, never
    the text (the reproduced fault: the report's own transcription varied
    between calls and could drop whole paragraphs)."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        1000,
        1000,
        [
            (0, [{"text": "POST CARD", "box": [101, 51, 299, 99], "score": 0.99, "words": []}]),
            (270, [{"text": "onorrow", "box": [501, 201, 899, 399], "score": 0.9, "words": []}]),
        ],
        report_lines=[
            {"index": 0, "box": [100, 50, 300, 100], "degrees": 0},
            {"index": 1, "box": [500, 200, 900, 400], "degrees": 270},
            {"index": 2, "box": [0, 0, 0, 0], "degrees": 0},  # not located
        ],
        vlm_text="POST CARD\nWe are from beauford\na line the report could not locate",
    )
    texts = [ln["text"] for ln in layout["lines"]]
    assert texts[0] == "POST CARD"
    assert "We are from beauford" in texts
    assert "a line the report could not locate" in texts  # the text survives a missing box
    by_text = {ln["text"]: ln for ln in layout["lines"]}
    assert by_text["POST CARD"]["box"] == [100.0, 50.0, 300.0, 100.0]  # the report's located box
    assert by_text["POST CARD"]["conf"] == 1.0  # the rec content-agreed
    assert by_text["We are from beauford"]["box"] == [500.0, 200.0, 900.0, 400.0]
    assert all(w["conf"] == 0.0 for w in by_text["We are from beauford"]["words"])  # the rec didn't agree
    assert by_text["a line the report could not locate"]["box"] is None  # flagged, boxless


def test_validate_layout_rejects_bad_boxes() -> None:
    """The fail-fast guard (2026-08-17): a layout whose line has a box
    that is degenerate or outside the image must never reach the front
    end — the reviewer must never see wrong boxes. Returns the
    violations; a clean layout passes."""
    from tools.layout import validate_layout

    good = {
        "width": 1000,
        "height": 2000,
        "lines": [
            {"text": "post card", "box": [100, 100, 300, 140]},
            {"text": "message", "box": [50, 500, 250, 540]},
            {"text": "no box", "box": None},
        ],
    }
    assert validate_layout(good) == []
    bad_out = {"width": 1000, "height": 2000, "lines": [{"text": "x", "box": [100, 100, 1500, 140]}]}
    assert validate_layout(bad_out), "a box outside the image must fail"
    bad_degenerate = {"width": 1000, "height": 2000, "lines": [{"text": "x", "box": [100, 100, 100, 200]}]}
    assert validate_layout(bad_degenerate), "a degenerate box must fail"
    bad_neg = {"width": 1000, "height": 2000, "lines": [{"text": "x", "box": [-50, 100, 300, 140]}]}
    assert validate_layout(bad_neg), "a negative coordinate must fail"

    """The combined layout shows the 0° lines first, then each next
    direction, each line carrying the orientation it was read at (VR15)."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        200,
        100,
        [
            (270, [{"text": "HARBOTTLE, MORPETH", "box": [10, 10, 20, 20], "score": 0.9, "words": []}]),
            (0, [{"text": "We are from beauford", "box": [1, 1, 5, 5], "score": 0.95, "words": []}]),
        ],
    )
    assert [line["text"] for line in layout["lines"]] == ["We are from beauford", "HARBOTTLE, MORPETH"]
    assert [line["orientation"] for line in layout["lines"]] == [0, 270]
    assert layout["unmatched"] == []


def test_multi_layout_keeps_only_the_best_reading_of_a_region() -> None:
    """The same physical strip read in several passes keeps only the
    richest reading — the postcard's vertical text read at 0°, 90° and
    270° (MHOTH vs HARBOTTLE, MORPETH at IoU 0.97): the wrong-direction
    garbage must not survive next to the real text."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        200,
        100,
        [
            (90, [{"text": "MHOTH", "box": [10, 10, 20, 60], "score": 0.9, "words": []}]),
            (270, [{"text": "HARBOTTLE, MORPETH", "box": [10, 10, 20, 60], "score": 0.9, "words": []}]),
            (0, [{"text": "With Greetings", "box": [30, 30, 40, 80], "score": 0.95, "words": []}]),
        ],
    )
    texts = [line["text"] for line in layout["lines"]]
    assert "MHOTH" not in texts
    assert "HARBOTTLE, MORPETH" in texts
    assert "With Greetings" in texts
    assert len(layout["lines"]) == 2


def test_load_orientation_hint_needs_two_distinct_directions(tmp_path: Path) -> None:
    """The sidecar is honoured only when it reports at least two distinct
    orientations — a single-direction report keeps the plain path."""
    from tools.layout import load_orientation_hint

    two = tmp_path / "two.json"
    two.write_text(
        '{"orientation_hint": [{"region": "message", "degrees": 0},'
        ' {"region": "address", "degrees": 270}], "lines": []}',
        encoding="utf-8",
    )
    assert load_orientation_hint(two) == [0, 270]
    one = tmp_path / "one.json"
    one.write_text('{"orientation_hint": [{"region": "message", "degrees": 0}], "lines": []}', encoding="utf-8")
    assert load_orientation_hint(one) == []
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert load_orientation_hint(bad) == []
    assert load_orientation_hint(tmp_path / "missing.json") == []


def test_orientation_passes_mirror_a_reported_vertical_direction() -> None:
    """A reported 90 (or 270) also runs its mirror pass — the model flips
    between the two for the same physical block between calls, and the
    wrong direction leaves the block upside-down (rejected, silently
    missed). The mirror costs one detection run, no model call."""
    from tools.layout import orientation_passes

    assert orientation_passes([0, 90]) == [0, 90, 270]
    assert orientation_passes([0, 270]) == [0, 90, 270]
    assert orientation_passes([0, 180]) == [0, 180]  # no mirror for 0/180


def _stub_paddleocr() -> None:
    """layout_detect imports paddleocr at module top — the main venv has no
    such module (PaddleOCR lives in .venv-htr). Stub it so the fail-loud
    logic is testable here without the heavy import."""
    import sys
    import types

    if "paddleocr" not in sys.modules:
        mod = types.ModuleType("paddleocr")
        mod.PaddleOCR = object  # type: ignore[attr-defined]  # the engine is injected; the class is never constructed
        sys.modules["paddleocr"] = mod


def test_layout_run_batch_fails_loud_on_explicit_page_without_guess(tmp_path: Path) -> None:
    """A layout for an explicitly requested page with no guess text must
    fail loudly (return 2), never silently skip — the bad page-02 layout
    was exactly a geometry-only build (2026-08-20)."""
    _stub_paddleocr()
    from tools.layout_detect import run_batch

    work = tmp_path
    (work / "adopt-0001" / "oriented").mkdir(parents=True)
    (work / "adopt-0001" / "ocr-guess").mkdir(parents=True)
    (work / "adopt-0001" / "oriented" / "p1.jpg").write_bytes(b"jpeg")

    class _FakeEngine:
        def predict(self, *args, **kwargs):  # pragma: no cover — must not be reached
            raise AssertionError("engine must not run for a missing guess")

    # explicitly requested page with no guess text -> fatal
    rc = run_batch("adopt-0001", ["p1.jpg"], work, _FakeEngine())
    assert rc == 2


def test_layout_run_batch_skips_implicit_page_without_guess(tmp_path: Path) -> None:
    """An unrequested page with no guess text is skipped with a stderr
    warning and a summary — the batch keeps going, but loudly."""
    _stub_paddleocr()
    from tools.layout_detect import run_batch

    work = tmp_path
    (work / "adopt-0001" / "oriented").mkdir(parents=True)
    (work / "adopt-0001" / "ocr-guess").mkdir(parents=True)
    (work / "adopt-0001" / "oriented" / "p1.jpg").write_bytes(b"jpeg")

    class _FakeEngine:
        def predict(self, *args, **kwargs):  # pragma: no cover — must not be reached
            raise AssertionError("engine must not run for a missing guess")

    rc = run_batch("adopt-0001", None, work, _FakeEngine())
    assert rc == 0  # batch continues, page skipped loudly


def test_reading_order_sorts_top_to_bottom_then_left_to_right() -> None:
    from tools.layout import order_lines_by_reading

    lines = [
        {"index": 0, "box": [100, 300, 300, 320], "orientation": 0},
        {"index": 1, "box": [100, 100, 300, 120], "orientation": 0},
        {"index": 2, "box": [400, 100, 600, 120], "orientation": 0},
    ]
    ordered = order_lines_by_reading(lines)
    assert [ln["index"] for ln in ordered] == [1, 2, 0]  # top band left→right, then the lower line


def test_reading_order_180_line_sorts_by_bottom_right() -> None:
    """An upside-down line's first character sits at the visual bottom-right
    of its box — it sorts by (x1, y1), not (x0, y0). A 180° line PHYSICALLY
    higher on the page still reads first (its reading-start y is smaller)."""
    from tools.layout import order_lines_by_reading

    lines = [
        {"index": 0, "box": [100, 100, 300, 120], "orientation": 180},
        {"index": 1, "box": [100, 200, 300, 220], "orientation": 0},
    ]
    # the 180 line's reading start is (300, 120) — y=120, ABOVE the 0 line's
    # (100, 200) — so it reads first despite being upside down
    ordered = order_lines_by_reading(lines)
    assert [ln["index"] for ln in ordered] == [0, 1]


def test_reading_order_90_line_sorts_by_top_of_vertical_text() -> None:
    """A 90° line reads top-to-bottom; its first character is the top-left
    of the tall box — it sorts by (x0, y0)."""
    from tools.layout import order_lines_by_reading

    lines = [
        {"index": 0, "box": [100, 400, 160, 900], "orientation": 90},
        {"index": 1, "box": [100, 100, 300, 120], "orientation": 0},
    ]
    ordered = order_lines_by_reading(lines)
    assert [ln["index"] for ln in ordered] == [1, 0]  # the header at y100 first, then the 90° message


def test_reading_order_270_line_sorts_by_bottom_left() -> None:
    """A 270° line reads bottom-to-top; its first character is the bottom
    of the box — (x0, y1)."""
    from tools.layout import order_lines_by_reading

    lines = [
        {"index": 0, "box": [100, 100, 160, 900], "orientation": 270},
        {"index": 1, "box": [100, 50, 300, 70], "orientation": 0},
    ]
    # the 270 line's reading start is (100, 900) — BELOW the 0° line (100, 50)
    ordered = order_lines_by_reading(lines)
    assert [ln["index"] for ln in ordered] == [1, 0]


def test_reading_order_handles_exact_near_cardinal_angles() -> None:
    """The clip classifier returns exact angles (88.4, 271.2, 358.7). The
    reading-start corner is chosen by quadrant; the stored orientation is
    NOT rounded."""
    from tools.layout import order_lines_by_reading, reading_start

    assert reading_start([100, 100, 300, 120], 358.7) == (100, 100)  # near 0 → top-left
    assert reading_start([100, 100, 300, 120], 88.4) == (100, 100)  # near 90 → top-left
    assert reading_start([100, 100, 300, 120], 181.5) == (300, 120)  # near 180 → bottom-right
    assert reading_start([100, 100, 300, 120], 271.2) == (100, 120)  # near 270 → bottom-left

    lines = [
        {"index": 0, "box": [100, 400, 300, 420], "orientation": 88.4},
        {"index": 1, "box": [100, 100, 300, 120], "orientation": 358.7},
    ]
    ordered = order_lines_by_reading(lines)
    assert [ln["index"] for ln in ordered] == [1, 0]


def test_reading_order_preserves_line_index() -> None:
    """The sort reorders the display list but keeps each line's index — the
    review surface keys edits and selections by index."""
    from tools.layout import order_lines_by_reading

    lines = [
        {"index": 7, "box": [100, 300, 300, 320], "orientation": 0},
        {"index": 3, "box": [100, 100, 300, 120], "orientation": 0},
    ]
    ordered = order_lines_by_reading(lines)
    assert [ln["index"] for ln in ordered] == [3, 7]


def test_reading_order_boxless_lines_last_in_input_order() -> None:
    from tools.layout import order_lines_by_reading

    lines = [
        {"index": 0, "box": [100, 300, 300, 320], "orientation": 0},
        {"index": 1, "text": "no box"},
        {"index": 2, "box": [100, 100, 300, 120], "orientation": 0},
    ]
    ordered = order_lines_by_reading(lines)
    assert [ln["index"] for ln in ordered] == [2, 0, 1]


def test_reading_order_is_stable_for_equal_starts() -> None:
    from tools.layout import order_lines_by_reading

    lines = [
        {"index": 0, "box": [100, 100, 300, 120], "orientation": 0},
        {"index": 1, "box": [100, 100, 300, 120], "orientation": 0},
    ]
    ordered = order_lines_by_reading(lines)
    assert [ln["index"] for ln in ordered] == [0, 1]  # ties keep input order


def test_reading_order_degenerate_box_does_not_crash() -> None:
    from tools.layout import order_lines_by_reading

    lines = [
        {"index": 0, "box": [100, 300, 300, 320], "orientation": 0},
        {"index": 1, "box": [50, 50, 50, 50], "orientation": 0},  # zero-area
        {"index": 2, "box": [0, 0, 10, 10], "orientation": 0},
    ]
    ordered = order_lines_by_reading(lines)
    assert len(ordered) == 3


def test_validate_layout_orientation_matches_box_aspect() -> None:
    """Gate A (2026-08-20): a line's orientation must be consistent with its
    box's aspect. A wide box (width >> height) holds horizontal text (axis
    near 0/180); a tall box holds vertical text (axis near 90/270). The
    check uses the orientation's AXIS (mod 180) so exact angles work —
    a 88.4° line is vertical-axis and must have a tall box. Fails only on
    the CLEARLY wrong cases (aspect >= 2x against a clearly-opposite
    axis); diagonal angles and near-square boxes pass (lenient)."""
    from tools.layout import validate_layout

    def _layout(lines):
        return {"width": 1000, "height": 1000, "lines": lines}

    # clearly-wide box labeled with a vertical axis -> violation
    assert validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 500, 50], "orientation": 90}]))
    assert validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 500, 50], "orientation": 88.4}]))
    assert validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 500, 50], "orientation": 271.2}]))
    # clearly-tall box labeled with a horizontal axis -> violation
    assert validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 50, 500], "orientation": 0}]))
    assert validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 50, 500], "orientation": 358.7}]))
    assert validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 50, 500], "orientation": 180}]))


def test_validate_layout_orientation_consistent_cases_pass() -> None:
    from tools.layout import validate_layout

    def _layout(lines):
        return {"width": 1000, "height": 1000, "lines": lines}

    # wide box with horizontal axis -> pass
    assert not validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 500, 50], "orientation": 0}]))
    assert not validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 500, 50], "orientation": 180}]))
    assert not validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 500, 50], "orientation": 358.7}]))
    # tall box with vertical axis -> pass
    assert not validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 50, 500], "orientation": 90}]))
    assert not validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 50, 500], "orientation": 271.2}]))
    # near-square box -> pass regardless (ambiguous, skip)
    assert not validate_layout(_layout([{"text": "x" * 5, "box": [0, 0, 60, 50], "orientation": 90}]))
    # diagonal axis with a wide box -> pass (lenient; a 45° line is diagonal)
    assert not validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 500, 300], "orientation": 45}]))
    # moderate aspect (1.5x) against a vertical axis -> pass (not clearly wrong)
    assert not validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 300, 200], "orientation": 90}]))
    # no orientation field -> pass (nothing to check)
    assert not validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 500, 50]}]))
    # no box -> pass (the existing gate handles boxless lines elsewhere)
    assert not validate_layout(_layout([{"text": "x" * 25, "orientation": 90}]))


def test_validate_layout_text_length_matches_box_extent() -> None:
    """Gate B (2026-08-20): a line's recognized text length must not be
    WILDLY out of sync with the box's reading-axis extent. The reading
    axis is the width for a horizontal line (axis near 0/180) and the
    height for a vertical one (axis near 90/270). A 500px-wide box holding
    3 characters is absurd (the box is empty or the text is truncated);
    a 50px box holding 40 characters is also absurd. The gate is LOOSE —
    only the wildly-out cases (outside ~3-80 px per character) fail, so
    handwriting variance and short fragments never false-positive."""
    from tools.layout import validate_layout

    def _layout(lines):
        return {"width": 1000, "height": 1000, "lines": lines}

    # a wide box (500px) with a 3-char text -> ~167 px/char: wildly out
    assert validate_layout(_layout([{"text": "abc", "box": [0, 0, 500, 50], "orientation": 0}]))
    # a narrow box (50px) with a 40-char text -> ~1.25 px/char: wildly out
    assert validate_layout(_layout([{"text": "x" * 40, "box": [0, 0, 50, 50], "orientation": 0}]))
    # a tall box (500px) with a 3-char text at 90° -> the axis is the height
    assert validate_layout(_layout([{"text": "abc", "box": [0, 0, 50, 500], "orientation": 90}]))
    # an empty text with a box -> wildly out (nothing there)
    assert validate_layout(_layout([{"text": "", "box": [0, 0, 500, 50], "orientation": 0}]))


def test_validate_layout_text_length_reasonable_cases_pass() -> None:
    from tools.layout import validate_layout

    def _layout(lines):
        return {"width": 1000, "height": 1000, "lines": lines}

    # a 500px box with ~25 chars -> ~20 px/char: plausible handwriting
    assert not validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 500, 50], "orientation": 0}]))
    # a short fragment ("N.B") in a small box -> plausible
    assert not validate_layout(_layout([{"text": "N.B", "box": [0, 0, 120, 50], "orientation": 0}]))
    # a vertical 500px box with ~25 chars at 90° -> axis is the height
    assert not validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 50, 500], "orientation": 90}]))
    # no box -> pass (handled elsewhere)
    assert not validate_layout(_layout([{"text": "anything", "orientation": 0}]))
    # no orientation -> the axis defaults to the width (horizontal)
    assert not validate_layout(_layout([{"text": "x" * 25, "box": [0, 0, 500, 50]}]))


class TestRecognizeExtra:
    """The clip->rotate->recognize flow for extra (rec-only) lines
    (2026-08-20, user's direction): a line the rec engine read as a
    fragment is clipped from the ORIGINAL image, rotated UPRIGHT by its
    orientation, and recognized there — the de-rotated reading, never
    the rotated-frame garbage. Fail fast (drop the line) when the clip
    is out of bounds, recognition returns nothing, or the recognized
    text is wildly out of sync with the box's reading axis (Gate C)."""

    def _png(self, tmp_path, w: int, h: int, rgb=(200, 200, 200)) -> Path:
        img = Image.new("RGB", (w, h), rgb)
        path = tmp_path / "page.png"
        img.save(path)
        return path

    def test_clip_is_rotated_upright_before_recognition(self, tmp_path) -> None:
        """A 90° line's clip must reach the recognizer UPRIGHT — the
        box [0, 0, 50, 100] in a 100x100 image holds vertical text; the
        recognizer must see the 100x50 (de-rotated) crop, not the tall
        sliver. A fragment is the rec's rotated-frame reading; the
        upright clip is what the model can actually read."""
        from tools.layout import recognize_extra

        image = self._png(tmp_path, 100, 100)
        seen: list[Path] = []

        def fake_recognize(crop: Path) -> str | None:
            seen.append(crop)
            with Image.open(crop) as im:
                assert im.size == (100, 50), f"clip must be upright 100x50, got {im.size}"
            return "the upright line"

        text = recognize_extra(image, [0, 0, 50, 100], 90, fake_recognize)
        assert text == "the upright line"
        assert len(seen) == 1

    def test_180_flips_the_clip(self, tmp_path) -> None:
        from tools.layout import recognize_extra

        image = self._png(tmp_path, 100, 60)
        seen: list[Path] = []

        def fake_recognize(crop: Path) -> str | None:
            seen.append(crop)
            with Image.open(crop) as im:
                assert im.size == (100, 60)
            return "flipped line"

        assert recognize_extra(image, [0, 0, 100, 60], 180, fake_recognize) == "flipped line"
        assert len(seen) == 1

    def test_empty_recognition_drops_the_line(self, tmp_path) -> None:
        """Gate C: recognition that returns nothing must DROP the line —
        never admit garbage or a blank line with a box."""
        from tools.layout import recognize_extra

        image = self._png(tmp_path, 100, 100)
        assert recognize_extra(image, [0, 0, 100, 20], 0, lambda crop: None) is None
        assert recognize_extra(image, [0, 0, 100, 20], 0, lambda crop: "   ") is None

    def test_out_of_sync_text_drops_the_line(self, tmp_path) -> None:
        """Gate C: the recognized text must match the box's proportions
        — 40 characters in a 50px reading axis is impossible; the line
        is dropped (a wildly wrong clip read must not anchor)."""
        from tools.layout import recognize_extra

        image = self._png(tmp_path, 100, 100)
        long = "x" * 40
        assert recognize_extra(image, [0, 0, 50, 20], 0, lambda crop: long) is None

    def test_out_of_bounds_box_drops_without_calling(self, tmp_path) -> None:
        from tools.layout import recognize_extra

        image = self._png(tmp_path, 100, 100)
        called = False

        def fake_recognize(crop: Path) -> str | None:
            nonlocal called
            called = True
            return "never"

        assert recognize_extra(image, [80, 0, 150, 20], 0, fake_recognize) is None
        assert not called

    def test_multi_layout_extras_use_the_recognized_text(self, tmp_path) -> None:
        """The wire-through: multi_layout's extra lines are replaced by
        the clip-recognized reading; a failed recognition DROPS the
        line entirely — the rec fragment never reaches the review."""
        from tools.layout import multi_layout

        image = self._png(tmp_path, 200, 200)
        passes = [
            (
                0,
                [
                    {
                        "text": "anchored line",
                        "box": [10, 10, 150, 30],
                        "score": 0.9,
                        "words": [],
                    }
                ],
            ),
            (
                90,
                [
                    {
                        "text": "frag",
                        "box": [10, 50, 30, 150],
                        "score": 0.8,
                        "words": [],
                    }
                ],
            ),
        ]
        recognized: list[str] = []

        def fake_recognize(crop: Path) -> str | None:
            recognized.append(crop.name)
            return "the true text" if len(recognized) == 1 else None

        layout = multi_layout(
            "p1.jpg",
            200,
            200,
            passes,
            report_lines=[{"index": 0, "box": [50, 50, 750, 150], "degrees": 0, "text": "anchored line"}],
            vlm_text="anchored line",
            image=image,
            recognize=fake_recognize,
        )
        texts = [ln["text"] for ln in layout["lines"]]
        assert "anchored line" in texts
        assert "the true text" in texts  # the first extra recognized
        assert "frag" not in texts  # the second extra's recognition failed -> dropped
