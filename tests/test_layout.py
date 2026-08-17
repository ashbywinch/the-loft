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
        layout = build_layout("p.jpg", 100, 100, "one line", [_det([0, 0, 10, 10], "one line")])
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


def test_multi_layout_orders_zero_first_then_next_directions() -> None:
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


def test_load_orientation_hint_needs_two_distinct_directions(tmp_path: Path) -> None:
    """The sidecar is honoured only when it reports at least two distinct
    orientations — a single-direction report keeps the plain path."""
    from tools.layout import load_orientation_hint

    two = tmp_path / "two.json"
    two.write_text(
        '[{"region": "message", "degrees": 0}, {"region": "address", "degrees": 270}]',
        encoding="utf-8",
    )
    assert load_orientation_hint(two) == [0, 270]
    one = tmp_path / "one.json"
    one.write_text('[{"region": "message", "degrees": 0}]', encoding="utf-8")
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
