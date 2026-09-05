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

import pytest
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
        dets = [_det([0, 0, 200, 20], "zzz qqq wwww eeee rrrr")]
        matches, unmatched = associate_lines(vlm, dets)
        assert len(matches) == 1
        assert matches[0]["box_source"] == "positional"
        assert matches[0]["box"] == [0, 0, 200, 20]
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
            _det([0, 200, 100, 220], "noise zzz"),
            _det([0, 0, 100, 20], "noise yyy"),
            _det([0, 100, 100, 120], "noise xxx"),
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

    def test_write_layout_store_stamps_the_store_version(self, tmp_path) -> None:
        """The layout's revision (2026-08-22): every store write stamps
        the version — a rebuild creates a NEW revision, and the drafts
        payload carries it so the review surface can DETECT a stale
        layout instead of rendering yesterday's boxes (the architectural
        gap: five copies of a layout, no way to tell which is newest).
        The same path re-run: 1, then 2."""
        from tools.layout import load_layout_store, write_layout_store
        from tools.pipeline_store import PipelineStore

        store = PipelineStore(tmp_path)
        layout = {"page": "p1.jpg", "width": 100, "height": 100, "lines": [], "unmatched": []}
        path = "b/ocr-guess/p1.layout.json"
        write_layout_store(layout, store, path)
        assert load_layout_store(store, path)["revision"] == 1
        write_layout_store(layout, store, path)
        assert load_layout_store(store, path)["revision"] == 2

    def test_every_line_carries_its_index(self, tmp_path) -> None:
        """2026-09-04 (user: "the transcript on screen is just 'A picture
        of life in music college' repeated over and over again"): the
        review surface keys the verify/edit state, the box clicks and the
        dual-pane links on ``line.index`` — and the pipeline's writers did
        not all emit it. Every line's index was ``undefined`` in the
        browser, so ONE "Verified" tap ran
        ``lines.find(l => l.index === undefined)``, matched the FIRST
        line, and saved line 0's text as the edit for every row: the
        whole page rendered as its first line. The writer stamps the
        position; the reader assigns it for the files already on disk."""
        layout = {
            "page": "p.jpg",
            "width": 100,
            "height": 100,
            "lines": [
                {"text": "one", "box": [0, 0, 90, 18]},
                {"text": "two", "box": [0, 30, 90, 48]},
            ],
            "unmatched": [],
        }
        path = tmp_path / "p.layout.json"
        write_layout(layout, path)
        # the WRITE stamped the position into the file
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert [ln["index"] for ln in on_disk["lines"]] == [0, 1]
        # a file written WITHOUT them (every layout on disk today) loads
        # with the position assigned
        bare = {
            "page": "q.jpg",
            "width": 100,
            "height": 100,
            "lines": [{"text": "one", "box": [0, 0, 90, 18]}, {"text": "two", "box": [0, 30, 90, 48]}],
        }
        q = tmp_path / "q.layout.json"
        q.write_text(json.dumps(bare), encoding="utf-8")
        loaded = load_layout(q)
        assert [ln["index"] for ln in loaded["lines"]] == [0, 1]
        # the store path too — the drafts payload's actual consumer
        # (review finding, PR 30: the plain-file assertions left the
        # versioned store's index assignment untested)
        from tools.layout import load_layout_store, write_layout_store
        from tools.pipeline_store import PipelineStore

        store = PipelineStore(tmp_path)
        spath = "b/ocr-guess/p.layout.json"
        write_layout_store(bare, store, spath)
        on_store = load_layout_store(store, spath)
        assert [ln["index"] for ln in on_store["lines"]] == [0, 1]


def test_layout_payload_declares_the_box_frame() -> None:
    """2026-08-22: the payload declares the boxes' coordinate frame — the
    ORIGINAL image's pixels, the same space as width/height — so a reader
    can check, never assume (the VLM-canvas drift was a box in the wrong
    frame that looked valid: right size, right proportions, gates pass)."""
    from tools.layout import Layout

    layout = Layout("p.jpg", 100, 200, [], [])
    assert layout.to_dict()["box_space"] == "original-image"


def test_validate_layout_rejects_a_boxless_line() -> None:
    """2026-08-22 (user: "I want boxless lines to fail during the pipeline
    run so we can figure out how to fix our pipeline!"): a line without a
    box is an unfinished pipeline result — the page must FAIL loudly at
    the write, never reach the review as a flag-riddled layout."""
    from tools.gates import validate_layout

    layout = {
        "page": "p1.jpg",
        "width": 100,
        "height": 100,
        "lines": [
            {"index": 0, "text": "boxed line", "box": [0, 0, 50, 10], "conf": 1.0, "words": []},
            {"index": 1, "text": "boxless line", "box": None, "conf": 0.0, "words": []},
        ],
        "unmatched": [],
    }
    assert validate_layout(layout)


def test_write_layout_store_refuses_a_boxless_line(tmp_path: Path) -> None:
    """The write gate (2026-08-22): a layout with a boxless line is
    refused — the pipeline run fails loudly for that page, and the
    reviewer never sees a half-anchored layout."""
    from tools.layout import write_layout_store
    from tools.pipeline_store import PipelineStore

    store = PipelineStore(tmp_path)
    layout = {
        "page": "p1.jpg",
        "width": 100,
        "height": 100,
        "lines": [{"index": 0, "text": "boxless line", "box": None, "conf": 0.0, "words": []}],
        "unmatched": [],
    }
    with pytest.raises(ValueError, match="boxless"):
        write_layout_store(layout, store, "b/ocr-guess/p1.layout.json")


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
            [_det([0, 0, 100, 20], "line one"), _det([0, 50, 120, 70], "noise")],
        )
        dets = layout_detections(layout)
        assert len(dets) == 2
        by_box = {tuple(d["box"]): d for d in dets}
        assert by_box[(0, 0, 100, 20)]["text"] == "line one"
        assert by_box[(0, 50, 120, 70)]["text"] == "noise"
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
    assert layout["lines"][0]["box_source"] == "report"
    assert layout["lines"][1]["box_source"] == "report"
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
    from tools.layout import is_admissible as admission_gate

    assert admission_gate("HERNSPETH HOUSE", 0.93)
    assert not admission_gate("mo", 0.5)  # two letters but low confidence
    assert not admission_gate("m", 0.99)  # confident but a single letter
    assert not admission_gate("", 0.99)


def test_remap_box_maps_back_to_the_original_frame() -> None:
    """A 90° pass's rotated-frame box maps back to the original image —
    the top of the rotated frame is the original's right edge."""
    from tools.layout import remap_box

    # 200x100 original; rotated -90° (clockwise, expand) the frame is
    # 100x200. A box at the top of the rotated frame (y=0-20) maps back
    # to the original's LEFT edge, vertically centered (2026-08-20: the
    # old matrix form mirrored this to the right edge — page-03's rebuilt
    # layout put the letter's lines at the image top).
    box = remap_box([40, 0, 60, 20], 90, (200, 100), (100, 200))
    assert box[0] < 5  # the far edge touches the left side (0)
    assert 30 < box[1] < 70 and 30 < box[3] < 70  # y near the center (50)
    # 270° (CCW): the top of the rotated frame maps back to the original's
    # right edge — the mirror of the 90° case.
    box270 = remap_box([40, 0, 60, 20], 270, (200, 100), (100, 200))
    assert box270[2] > 195  # the far edge touches the right side (200)
    assert 30 < box270[1] < 70 and 30 < box270[3] < 70


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
    assert kept[0]["box"][0] < 5  # remapped to the original frame (left edge — 2026-08-20 fix)
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


def test_anchor_prefers_the_disjoint_positional_ink_when_the_rec_read_the_line() -> None:
    """page-01 (2026-08-22): the location report's boxes sit in the VLM's
    compressed canvas — the whole letter squeezed into the top of the
    0-1000 frame — so the scaled report box lands ~500px ABOVE the real
    text (the title region claimed by 'Last term I was called upon').
    The positional match's box is only the line's real region when the
    rec READ the line's text there (the rec_words agree) — then the
    ink wins over the disjoint estimate. The review's dual-pane
    alignment (the line at the image's view) is only as true as the
    boxes."""
    from tools.layout import Anchor

    anchor = Anchor(
        report_line={"text": "Last term I was called upon to play in t", "box": [220, 481, 790, 494], "degrees": 0},
        match={
            "vlm": "Last term I was called upon to play in t",
            "vlm_index": 10,
            "box": [560, 2600, 2010, 2660],  # the rec's ink — the REAL region
            "box_source": "positional",
            "orientation": 0,
            "rec_words": ["last", "term", "i", "was", "called", "upon", "to", "play", "in", "the", "college", "opera"],
        },
        text="Last term I was called upon to play in the Orchestra",
        width=2544,
        height=4642,
    )
    assert anchor.box == [560, 2600, 2010, 2660]
    assert anchor.box_source == "positional"


def test_anchor_disjoint_positional_with_unrelated_reading_keeps_the_report_box() -> None:
    """The other half of the same rule (2026-08-22): the order-based
    fallback CAN mispair — the rec's 17 detections vs the guess's 31
    lines means the tail's positional boxes are the wrong lines' ink.
    When the rec did NOT read the line's text at the match's box (the
    rec_words disagree), the match's box is unrelated ink and must not
    displace a good report box — the pre-existing test
    (report_box_anchors_over_a_positional_match) pins the same case at
    the layout level."""
    from tools.layout import Anchor

    anchor = Anchor(
        report_line={"text": "Last term I was called upon to play in t", "box": [220, 481, 790, 494], "degrees": 0},
        match={
            "vlm": "Last term I was called upon to play in t",
            "vlm_index": 10,
            "box": [560, 2600, 2010, 2660],
            "box_source": "positional",
            "orientation": 0,
            "rec_words": ["ortra", "for", "3", "eope"],  # the rec read a DIFFERENT line there
        },
        text="Last term I was called upon to play in the Orchestra",
        width=2544,
        height=4642,
    )
    assert anchor.box == [559.68, 2232.802, 2009.76, 2293.148]
    assert anchor.box_source == "report"


def test_anchor_report_box_still_refines_an_agreeing_positional_box() -> None:
    """The regression guard: when the report's estimate AGREES with the
    positional ink (the same region), the report box is the per-line
    refinement and wins — the pre-2026-08-22 behavior stays for the
    normal pages (02-12), where the report's boxes are on the text."""
    from tools.layout import Anchor

    anchor = Anchor(
        report_line={"text": "Last term I was called upon to play in t", "box": [220, 481, 790, 494], "degrees": 0},
        match={
            "vlm": "Last term I was called upon to play in t",
            "vlm_index": 10,
            "box": [560, 2230, 2010, 2300],  # overlaps the report's scaled box
            "box_source": "positional",
            "orientation": 0,
            "rec_words": ["last", "term", "i", "was", "called"],
        },
        text="Last term I was called upon to play in the Orchestra",
        width=2544,
        height=4642,
    )
    assert anchor.box == [559.68, 2232.802, 2009.76, 2293.148]
    assert anchor.box_source == "report"


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
        ],
    }
    assert validate_layout(good) == []
    bad_out = {"width": 1000, "height": 2000, "lines": [{"text": "x", "box": [100, 100, 1500, 140]}]}
    assert validate_layout(bad_out), "a box outside the image must fail"
    bad_degenerate = {"width": 1000, "height": 2000, "lines": [{"text": "x", "box": [100, 100, 100, 200]}]}
    assert validate_layout(bad_degenerate), "a degenerate box must fail"
    bad_neg = {"width": 1000, "height": 2000, "lines": [{"text": "x", "box": [-50, 100, 300, 140]}]}
    assert validate_layout(bad_neg), "a negative coordinate must fail"


def test_stitch_crop_box_maps_the_crop_local_frame_into_the_page() -> None:
    """The crop-grid's stitch (2026-08-22): the model measures each line
    within a crop's own frame (normalized 0-1000 in the crop); the
    stitch maps that local box into the page by the crop's known
    offset — the page box, exactly."""
    from tools.eval_geometry import CropReading, stitch_crop_box

    crop = CropReading(x=500.0, y=700.0, w=400.0, h=300.0, lines=[])

    local: list[float] = [100, 200, 600, 250]  # normalized 0-1000 in the crop
    assert stitch_crop_box(crop, local) == [540.0, 760.0, 740.0, 775.0]
    # the crop's origin adds, the crop's size scales
    assert stitch_crop_box(crop, [0, 0, 1000, 1000]) == [500.0, 700.0, 900.0, 1000.0]


def test_gate_b_calibrates_the_ceiling_by_glyph_size() -> None:
    """2026-08-22's absolute 80/160 ceilings assumed handwriting scale;
    2026-08-26 replaced them with a ceiling that scales with the box's
    OWN perpendicular extent (x1.7, floor 30) — a letter's advance is
    proportional to its glyph size, so big print is legitimate while
    mislabeled normal-height rows stay tight. This test pins both the
    survivors and the consciously-flipped assertions."""
    from tools.gates import text_extent_violation

    # the postcard's message line: 19 chars in a 1539px-tall vertical
    # box, width 169 -> ceiling 287: passes (as before)
    assert text_extent_violation("decent day tomorrow", [215, 544, 384, 2083], 90) is None
    # the absurd vertical: 3 chars in a 1500px box -> 500 px/char vs a
    # 50px-wide column's ceiling of 85: still caught
    assert text_extent_violation("abc", [0, 0, 50, 1500], 90) is not None
    # FLIPPED (2026-08-26): 81 px/char on a 50px-tall row is now
    # plausible big-ish handwriting (ceiling 85) — the old horizontal
    # 80 absolute ceiling refused it; sparsity is judged per glyph size
    assert text_extent_violation("abc", [0, 0, 243, 50], 0) is None
    # FLIPPED (2026-08-26): 10 chars at 150 px/char along a 50px-wide
    # vertical column means 150px between 50px-tall glyphs — absurd
    # sparsity under the glyph-size rule (ceiling 85): now caught,
    # where the old 160 vertical ceiling let it through
    assert text_extent_violation("x" * 10, [0, 0, 50, 1500], 90) is not None


def test_transcription_line_count_plausible() -> None:
    """The collapse detector (2026-08-25): the birth certificate's model
    read folded 26 measured rows into one line — every row then carried
    the same 323-char blob and Gate B refused the page. Conservative:
    only pages with >= 10 measured rows are judged (photo captions
    fragment into more rows than real lines)."""
    from tools.ink import transcription_line_count_plausible as plausible

    assert not plausible(2, 26)  # the birth-cert collapse
    assert plausible(24, 26)  # a healthy letter
    assert plausible(11, 26)  # the 40% floor
    assert plausible(1, 5)  # few rows: any count accepted
    assert plausible(4, 10)  # exactly 40% passes


def test_ink_match_labels_assigns_by_order() -> None:
    """The order-based label matching (2026-08-22, the user's item 2):
    each row's y-center, as a fraction of the content's span, picks the
    transcription line at the same fraction — the 1:1 case."""
    from tools.ink import match_labels

    # three rows evenly spaced down a 900px span
    rows = [[0.0, 0.0, 100.0, 100.0], [0.0, 300.0, 100.0, 400.0], [0.0, 600.0, 100.0, 700.0]]
    lines = ["first line", "second line", "third line"]
    assert match_labels(rows, lines) == lines


def test_ink_match_labels_handles_merged_rows() -> None:
    """The rec's rows can merge two lines (its det is coarse on
    cursive) — a merged row gets the line at its center, and the
    assignment never collapses to one band."""
    from tools.ink import match_labels

    rows = [
        [0.0, 0.0, 100.0, 100.0],
        [0.0, 180.0, 100.0, 280.0],
        [0.0, 360.0, 100.0, 460.0],
        [0.0, 540.0, 100.0, 640.0],
        [0.0, 720.0, 100.0, 820.0],
    ]
    lines = ["one", "two", "three", "four", "five"]
    labels = match_labels(rows, lines)
    assert len(set(labels)) >= 4, f"the assignment must not collapse: {labels}"


def test_ink_match_labels_falls_back_when_the_overlap_is_degenerate() -> None:
    """The schematic full-page boxes (every row matches the same band —
    the letter's read) must fall back to the proportional assignment,
    not label every row with the first line."""
    from tools.ink import match_labels

    rows = [[0.0, 0.0, 100.0, 100.0], [0.0, 300.0, 100.0, 400.0], [0.0, 600.0, 100.0, 700.0]]
    lines = ["first line", "second line", "third line"]
    bands = [(0.0, 50.0, lines[0]), (0.0, 50.0, lines[0]), (0.0, 50.0, lines[0])]
    assert match_labels(rows, lines, bands) == lines


def test_ink_match_labels_keeps_the_overlap_when_it_is_not_degenerate() -> None:
    """The rotated panel's trustworthy bands (the postcard) keep the
    y-overlap refinement — the proportional is the fallback."""
    from tools.ink import match_labels

    rows = [[0.0, 0.0, 100.0, 100.0], [0.0, 300.0, 100.0, 400.0], [0.0, 600.0, 100.0, 700.0]]
    lines = ["first line", "second line", "third line"]
    bands = [(0.0, 150.0, "first line"), (250.0, 450.0, "second line"), (550.0, 750.0, "third line")]
    assert match_labels(rows, lines, bands) == lines


def test_ink_cluster_rows_splits_side_by_side_pieces() -> None:
    """The x-split (2026-08-22): the rec's y-band clustering can merge
    side-by-side pieces - the postcard's date and the HERNSPETH sharing
    a band - and the union would span the blank middle, tripping the
    text-extent gates. The split at wide x-gaps gives each side its own
    row with a tighter box."""
    from tools.ink import cluster_rows, union

    pieces = [
        [208.0, 188.0, 241.0, 206.0],
        [1206.0, 147.0, 1589.0, 216.0],
        [1604.0, 147.0, 1900.0, 214.0],
    ]
    rows = cluster_rows(pieces)
    assert len(rows) == 2
    left = union(rows[0])
    right = union(rows[1])
    assert left[2] - left[0] < 100
    assert right[0] > 1100


def test_ink_cluster_rows_keeps_a_lines_words_together() -> None:
    """The split must NOT break a single line whose words sit close
    together (the normal case) - only the wide gaps split."""
    from tools.ink import cluster_rows

    pieces = [[0.0, 0.0, 100.0, 20.0], [110.0, 0.0, 220.0, 20.0], [240.0, 0.0, 350.0, 20.0]]
    rows = cluster_rows(pieces)
    assert len(rows) == 1


def test_ink_cluster_row_thresholds_are_scale_invariant() -> None:
    """The thresholds derive from the measured piece sizes (2026-08-22):
    the same layout at half the scan resolution must cluster the same
    way - the absolute pixel gaps were tuned on one batch and would
    merge every row at a different scale."""
    from tools.ink import cluster_rows

    def page(scale: float) -> list[list[float]]:
        out = []
        for r in range(3):
            for c in range(3):
                x = (c * 300 + 50) * scale
                y = (r * 90 + 20) * scale
                out.append([x, y, x + 200 * scale, y + 40 * scale])
        return out

    full = cluster_rows(page(1.0))
    half = cluster_rows(page(0.5))
    assert len(full) == 3 and len(half) == 3, (
        f"the scale must not change the clustering: full={len(full)}, half={len(half)}"
    )


def test_ink_cluster_rows_splits_a_runaway_row() -> None:
    """The tall-split (2026-08-25): single-linkage chaining merges
    pieces whose every ADJACENT gap is small into a row spanning many
    real lines - the birth certificate's form table chained 40 cells
    into one 290px row (6.2x its own piece scale), the photo's big
    handwriting 13 pieces into 1077px (6.3x). One line's extent cannot
    exceed ~2.5x its own pieces' median height; an over-tall row splits
    at its internal gaps until every part is plausible."""
    from tools.ink import cluster_rows, union

    # three tight text bands (h=40) at staggered x's, centers 25px
    # apart - every adjacent pair chains under the y-gap threshold,
    # total extent 190px = 4.75x the piece height
    pieces = []
    for i in range(8):
        y = 100.0 + i * 25.0
        x = 100.0 + (i % 3) * 400.0
        pieces.append([x, y, x + 150.0, y + 40.0])
    rows = cluster_rows(pieces)
    assert len(rows) >= 3, f"chained into {len(rows)} row(s)"
    for row in rows:
        u = union(row)
        assert u[3] - u[1] <= 2.5 * 40.0 + 1e-9


def test_ink_cluster_rows_keeps_a_tall_but_legitimate_line() -> None:
    """A slanting cursive line with ascenders is ONE row: its extent
    stays within ~2x its pieces' scale. The split must not shred real
    lines - only the implausible ones."""
    from tools.ink import cluster_rows

    pieces = [
        [100.0, 100.0, 300.0, 150.0],  # h=50
        [320.0, 115.0, 520.0, 165.0],
        [540.0, 130.0, 740.0, 180.0],  # drift 30px over the line; extent 80px = 1.6x
    ]
    rows = cluster_rows(pieces)
    assert len(rows) == 1


def test_multi_layout_orders_zero_first_then_each_next_direction() -> None:
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
    """The block order clusters the lines by ink and reads the blocks
    top-to-bottom; same-y-band blocks keep their input order (the old
    reading-start sort's left-to-right tie-break is subsumed by the
    block clustering — side-by-side blocks are separate clusters)."""
    from tools.reading import order_lines as order_lines_by_blocks

    lines = [
        {"index": 0, "box": [100, 300, 300, 320], "orientation": 0},
        {"index": 1, "box": [100, 100, 300, 120], "orientation": 0},
        {"index": 2, "box": [400, 100, 600, 120], "orientation": 0},
    ]
    ordered = order_lines_by_blocks(lines)
    assert [ln["index"] for ln in ordered] == [1, 2, 0]  # top band first, then the lower line


def test_layout_run_batch_returns_1_when_a_page_is_refused(tmp_path: Path) -> None:
    """2026-08-22 (user: boxless lines must FAIL the pipeline run): a page
    whose layout the gates refuse (a boxless line) makes the run FAIL —
    return 1, never a silent 0 with the page missing from the output."""
    from PIL import Image

    _stub_paddleocr()
    from tools.layout_detect import run_batch

    work = tmp_path
    (work / "adopt-0001" / "oriented").mkdir(parents=True)
    (work / "adopt-0001" / "ocr-guess").mkdir(parents=True)
    Image.new("RGB", (200, 100), (200, 200, 200)).save(work / "adopt-0001" / "oriented" / "p1.jpg")
    (work / "adopt-0001" / "ocr-guess" / "p1.txt").write_text("boxed line\nboxless line", encoding="utf-8")

    class _FakeEngine:
        def predict(self, input, return_word_box=False):
            return [
                {
                    "dt_polys": [[[0, 0], [100, 0], [100, 20], [0, 20]]],
                    "rec_texts": ["boxed line"],
                    "rec_scores": [0.9],
                    "text_word_region": [],
                }
            ]

    rc = run_batch("adopt-0001", None, work, _FakeEngine())
    assert rc == 1


def test_reading_order_180_line_reads_after_the_upright_header() -> None:
    """An upside-down (180°) line's block sorts by its box top — a block
    physically higher reads first; the orientation itself is untouched
    (never rounded)."""
    from tools.reading import order_lines as order_lines_by_blocks

    lines = [
        {"index": 0, "box": [100, 100, 300, 120], "orientation": 180},
        {"index": 1, "box": [100, 200, 300, 220], "orientation": 0},
    ]
    ordered = order_lines_by_blocks(lines)
    assert [ln["index"] for ln in ordered] == [0, 1]
    assert ordered[0]["orientation"] == 180  # the exact angle survives


def test_reading_order_handles_exact_near_cardinal_angles() -> None:
    """The clip classifier returns exact angles (88.4, 271.2, 358.7); the
    block order clusters by ink (orientation-independent) and never
    rounds the stored orientation."""
    from tools.reading import order_lines as order_lines_by_blocks

    lines = [
        {"index": 0, "box": [100, 400, 300, 420], "orientation": 88.4},
        {"index": 1, "box": [100, 100, 300, 120], "orientation": 358.7},
    ]
    ordered = order_lines_by_blocks(lines)
    assert [ln["index"] for ln in ordered] == [1, 0]
    assert ordered[1]["orientation"] == 88.4


def test_reading_order_preserves_line_index() -> None:
    """The ordering reorders the display list but keeps each line's index —
    the review surface keys edits and selections by index."""
    from tools.reading import order_lines as order_lines_by_blocks

    lines = [
        {"index": 7, "box": [100, 300, 300, 320], "orientation": 0},
        {"index": 3, "box": [100, 100, 300, 120], "orientation": 0},
    ]
    ordered = order_lines_by_blocks(lines)
    assert [ln["index"] for ln in ordered] == [3, 7]


def test_reading_order_boxless_lines_last_in_input_order() -> None:
    from tools.reading import order_lines as order_lines_by_blocks

    lines = [
        {"index": 0, "box": [100, 300, 300, 320], "orientation": 0},
        {"index": 1, "text": "no box"},
        {"index": 2, "box": [100, 100, 300, 120], "orientation": 0},
    ]
    ordered = order_lines_by_blocks(lines)
    assert [ln["index"] for ln in ordered] == [2, 0, 1]


def test_reading_order_is_stable_for_equal_starts() -> None:
    from tools.reading import order_lines as order_lines_by_blocks

    lines = [
        {"index": 0, "box": [100, 100, 300, 120], "orientation": 0},
        {"index": 1, "box": [100, 100, 300, 120], "orientation": 0},
    ]
    ordered = order_lines_by_blocks(lines)
    assert [ln["index"] for ln in ordered] == [0, 1]  # ties keep input order


def test_reading_order_degenerate_box_does_not_crash() -> None:
    from tools.reading import order_lines as order_lines_by_blocks

    lines = [
        {"index": 0, "box": [100, 300, 300, 320], "orientation": 0},
        {"index": 1, "box": [50, 50, 50, 50], "orientation": 0},  # zero-area
        {"index": 2, "box": [0, 0, 10, 10], "orientation": 0},
    ]
    ordered = order_lines_by_blocks(lines)
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
    # no box -> FAILS (2026-08-22, user: boxless lines must fail the
    # pipeline run so the geometry pass gets fixed — the older
    # boxless-passes rule is superseded)
    assert validate_layout(_layout([{"text": "x" * 25, "orientation": 90}]))


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
    # no box -> FAILS (2026-08-22, user: boxless lines must fail the
    # pipeline run so the geometry pass gets fixed)
    assert validate_layout(_layout([{"text": "anything", "orientation": 0}]))
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

    def _png(self, tmp_path, w: int, h: int, rgb=(40, 40, 40)) -> Path:
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


def test_multi_layout_trusts_clip_report_degrees_over_the_pass() -> None:
    """A clip-sourced report's located degrees are the line's TRUE
    orientation (the clip classifier measures the exact angle of the
    actual text — the designed fix for the full-page call's 90-vs-270
    flip). The pass orientation is a rotated-frame artifact: page-03's
    horizontal lines were content-matched during the mirrored 90° pass
    and labeled 90° — wrong for the UI rotation and the reading order.
    With ``trust_report_degrees`` (the clip source), the located degrees
    win; without it the full-page report's estimates stay untrusted
    (the 2026-08-17 decision, test above)."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        1000,
        1000,
        [
            (0, [{"text": "POST CARD", "box": [101, 51, 299, 99], "score": 0.99, "words": []}]),
            (90, [{"text": "my first Theory", "box": [501, 201, 999, 252], "score": 0.9, "words": []}]),
        ],
        report_lines=[
            {"index": 0, "box": [100, 50, 300, 100], "degrees": 0},
            # the clip classifier located the line at 0 (it IS horizontal);
            # the 90° pass merely read the mirrored frame
            {"index": 1, "box": [500, 200, 1000, 252], "degrees": 0},
        ],
        vlm_text="POST CARD\nmy first Theory lesson to",
        trust_report_degrees=True,
    )
    line = [ln for ln in layout["lines"] if "Theory" in ln["text"]][0]
    assert line["orientation"] == 0, f"the located degrees must win over the pass, was {line['orientation']}"


def test_multi_layout_uses_the_match_box_when_the_report_box_misses_the_ink() -> None:
    """The report's located box is an anchor only when it claims the same
    ink the rec matched — page-03's transcription boxes sat ~200px above
    the real text (the model's estimate failed), while the detector found
    the line. A report box disjoint from the matched detection is an
    estimate, not geometry: the layout must use the rec match's box
    (2026-08-20)."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        1000,
        1000,
        [
            (
                0,
                [
                    {
                        "text": "P.S. I had a whole Grade 3A",
                        "box": [100, 400, 480, 440],  # the rec found the text HERE
                        "score": 0.95,
                        "words": [],
                    }
                ],
            ),
        ],
        report_lines=[
            # the report claims the line ~200px ABOVE the actual text
            {"index": 0, "box": [100, 150, 480, 190], "degrees": 0},
        ],
        vlm_text="P.S. I had a whole Grade 3A",
    )
    line = layout["lines"][0]
    assert line["box"] == [100, 400, 480, 440], f"the rec match's box must win, was {line['box']}"


def test_multi_layout_rejects_an_inconsistent_report_angle_on_a_wide_box() -> None:
    """Even a TRUSTED (clip) report's angle must be geometry-validated:
    a 90° label on a 501x51 (wide) box is the classifier's error — the
    box says horizontal text, so the line's orientation resolves to the
    aspect-consistent 0 (2026-08-20: the clip classifier misread 2 of
    page-03's tiny crops as 90°)."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        1000,
        1000,
        [
            (
                90,
                [
                    {
                        "text": "my first Theory lesson",
                        "box": [100, 200, 601, 251],  # wide: horizontal text
                        "score": 0.9,
                        "words": [],
                    }
                ],
            ),
        ],
        report_lines=[{"index": 0, "box": [100, 200, 601, 251], "degrees": 90}],
        vlm_text="my first Theory lesson",
        trust_report_degrees=True,
    )
    line = layout["lines"][0]
    assert line["orientation"] == 0, f"the wide box must force 0, was {line['orientation']}"


def test_multi_layout_extras_force_the_aspect_consistent_orientation() -> None:
    """The extras' orientations are geometry-validated too: an extra
    detected during the 90° pass but with a wide (merged) box is
    horizontal text — the pass label is a rotated-frame artifact, the
    line's orientation is 0 (2026-08-20: page-03's refused rebuild)."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        1000,
        1000,
        [
            (
                90,
                [
                    {
                        "text": "When Dr W. saw & di",
                        "box": [100, 100, 351, 220],  # wide -> horizontal
                        "score": 0.9,
                        "words": [],
                    }
                ],
            ),
        ],
        report_lines=None,
    )
    line = layout["lines"][0]
    assert line["orientation"] == 0, f"the wide extra box must force 0, was {line['orientation']}"


def test_build_layout_leaves_a_wildly_oversized_positional_box_boxless() -> None:
    """The positional fallback's guard (2026-08-20): a boxless VLM line
    takes an unmatched detection's box ONLY when the box plausibly holds
    the line's text — page-05's '③' (one glyph) was paired with a 552px
    detection box, which refused the whole page at the write gate. The
    absurd box is dropped (the line stays boxless, flagged), never
    assigned — the page stays reviewable."""
    from tools.layout import build_layout

    layout = build_layout(
        "p1.jpg",
        1000,
        1000,
        "a real line\n③",
        [
            {"box": [100, 100, 600, 140], "text": "a real line", "score": 0.95, "words": []},
            {"box": [50, 500, 602, 589], "text": "garbage", "score": 0.9, "words": []},  # 552px wide
        ],
    )
    by_text = {ln["text"]: ln for ln in layout["lines"]}
    assert by_text["a real line"]["box"] == [100, 100, 600, 140]
    assert by_text["③"]["box"] is None, "the absurd positional box must be dropped, not assigned"
    # the drop is per-line: a plausible positional box still anchors
    layout2 = build_layout(
        "p1.jpg",
        1000,
        1000,
        "a real line\nN.B",
        [
            {"box": [100, 100, 600, 140], "text": "a real line", "score": 0.95, "words": []},
            {"box": [50, 500, 150, 540], "text": "garbage", "score": 0.9, "words": []},  # 100px for 3 chars
        ],
    )
    by2 = {ln["text"]: ln for ln in layout2["lines"]}
    assert by2["N.B"]["box"] == [50, 500, 150, 540]


def test_multi_layout_report_box_anchors_over_a_positional_match() -> None:
    """The report's located box is the v3 anchor for a line the rec never
    content-matched: the POSITIONAL match's box is unrelated ink (the
    k-th unmatched detection), not evidence — a good report box must win
    over it (2026-08-20: layout-5's correct anchors would have been
    replaced by the positional boxes). A CONTENT match's box still wins
    when the report box misses the ink (the disjoint case, tested
    above)."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        1000,
        1000,
        [
            (
                0,
                [
                    {
                        "text": "POST CARD",
                        "box": [101, 51, 299, 99],
                        "score": 0.99,
                        "words": [],
                    },
                ],
            ),
        ],
        report_lines=[
            {"index": 0, "box": [100, 50, 300, 100], "degrees": 0},
            # the report located line 1 at the left margin; the positional
            # match box is the unrelated HERNSPETH detection
            {"index": 1, "box": [50, 400, 100, 500], "degrees": 0},
        ],
        vlm_text="POST CARD\ncritic's view. To quote:",
    )
    by_text = {ln["text"]: ln for ln in layout["lines"]}
    critic = by_text["critic's view. To quote:"]
    assert critic["box_source"] == "report-unconfirmed"
    assert critic["box"] == [50.0, 400.0, 100.0, 500.0], f"the report's box must anchor, was {critic['box']}"


def test_multi_layout_false_content_match_cannot_override_the_report_box() -> None:
    """The postcard (2026-08-20): a 2-word line ('E    R') false-matches a
    rec detection whose box is a 1341px merged band — the rec read the
    stamp region as a few words containing 'e'/'r', clearing the Jaccard
    bar. A content match's box only overrides the report's location when
    the box plausibly holds the line's text (Gate B's own rule): the
    1341px band for 6 characters is a false match; the report's located
    box anchors instead."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        3500,
        2215,
        [
            (
                0,
                [
                    {
                        "text": "e r",  # the rec's noisy stamp reading
                        "box": [1998, 988, 3339, 1316],  # a 1341px merged band
                        "score": 0.95,
                        "words": [],
                    }
                ],
            ),
        ],
        report_lines=[
            {"index": 0, "box": [900, 76, 950, 101], "degrees": 0},  # the located stamp text, tight
        ],
        vlm_text="E    R",
    )
    line = layout["lines"][0]
    assert line["text"] == "E    R"
    # the report's scaled box: 900/1000*3500 = 3150 ... 950/1000*3500 = 3325
    assert line["box"][0] == 3150, f"the report's located box must anchor, was {line['box']}"
    assert line["box"][2] == 3325


def test_multi_layout_drops_the_box_when_no_candidate_holds_the_text() -> None:
    """When neither the report's box nor the match's box plausibly holds
    the line's text (the postcard's stamp lines — the location call's
    boxes are loose for printed graphics), the line goes BOXLESS (flagged)
    rather than anchoring a wildly wrong box that refuses the whole page
    (2026-08-20)."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        3500,
        2215,
        [
            (
                0,
                [
                    {
                        "text": "e r",
                        "box": [1998, 988, 3339, 1316],
                        "score": 0.95,
                        "words": [],
                    }
                ],
            ),
        ],
        report_lines=[
            {"index": 0, "box": [821, 76, 964, 101], "degrees": 0},  # 501px for 'E    R' — still too loose
        ],
        vlm_text="E    R",
    )
    assert layout["lines"][0]["box"] is None, "no candidate holds the text — boxless, flagged"


def test_build_layout_keeps_the_transcription_order_for_margin_blocks() -> None:
    """The single-orientation reading order (2026-08-20, user's
    requirement): a page's transcription order IS the block-aware reading
    — the model read the page block-by-block (page-03: the P.S. margin
    top-to-bottom, then the address block, then the body; each block's
    text order = its physical order). The reading-start sort read
    ROW-by-row across the same y-band, interleaving the margin blocks
    (P.S. line, Postmark, theory line, Queen's House — 10+ image
    bounces). The single path keeps the transcription order: the display
    matches the transcription, and the image moves block-by-block (one
    jump), never bouncing."""
    from tools.layout import build_layout

    layout = build_layout(
        "p1.jpg",
        1000,
        1000,
        "P.S. line one\ntheory paper\nPostmark 27.9.63\nQueen's House",
        [
            {"box": [100, 100, 300, 140], "text": "P.S. line one", "score": 0.95, "words": []},
            {"box": [100, 150, 300, 190], "text": "theory paper", "score": 0.95, "words": []},
            {"box": [400, 102, 600, 142], "text": "Postmark", "score": 0.95, "words": []},
            {"box": [400, 152, 600, 192], "text": "Queen's House", "score": 0.95, "words": []},
        ],
    )
    texts = [ln["text"] for ln in layout["lines"]]
    # the transcription order — NOT the reading-start interleave
    assert texts == ["P.S. line one", "theory paper", "Postmark 27.9.63", "Queen's House"], texts


def test_multi_layout_keeps_the_physical_reading_order() -> None:
    """The multi-orientation reading order (the postcard, 2026-08-20):
    the transcription order scrambled the multi reading (the 90° body's
    top fragments sorted before the 0° margin), so the physical
    reading-start sort in the dominant frame still applies — each
    orientation block reads top-to-bottom in its frame position, the
    rotations change once per block, never per line."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        1000,
        1000,
        [
            (
                270,
                [
                    {
                        "text": "message line",
                        "box": [700, 400, 900, 900],  # the 270° message at the bottom-right
                        "score": 0.9,
                        "words": [],
                    }
                ],
            ),
            (
                0,
                [
                    {"text": "POST CARD", "box": [101, 51, 299, 99], "score": 0.99, "words": []},
                ],
            ),
        ],
        report_lines=[
            {"index": 0, "box": [100, 50, 300, 100], "degrees": 0},
            {"index": 1, "box": [700, 400, 900, 900], "degrees": 270},
        ],
        vlm_text="POST CARD\nmessage line",
    )
    texts = [ln["text"] for ln in layout["lines"]]
    # the 270° message reads upright with its reading-start ABOVE the
    # 0° POST CARD? No — POST CARD (y50) is physically above the message
    # (y400): the physical order reads POST CARD first.
    assert texts == ["POST CARD", "message line"], texts
    # and the 270° line keeps its orientation (the reading frame, not a
    # per-line rotation flip)
    msg = [ln for ln in layout["lines"] if ln["text"] == "message line"][0]
    assert msg["orientation"] == 270


def test_dedupe_regions_survives_boxless_lines() -> None:
    """The boxless anchored lines (2026-08-20 — the arbitration drops a
    box when no candidate holds the text) must not crash the dedupe: the
    region-overlap check skips lines without a box — the postcard's
    rebuild crashed on a None box in _box_area."""
    from tools.layout import dedupe_regions

    lines = [
        {"index": 0, "text": "E    R", "box": None, "conf": 0.0, "box_source": "report-unconfirmed"},
        {"index": 1, "text": "extra fragment", "box": [0, 0, 100, 20], "conf": 0.0, "box_source": "multi"},
    ]
    out = dedupe_regions(lines)
    assert [ln["text"] for ln in out] == ["E    R", "extra fragment"]


def test_multi_layout_keeps_text_order_when_orientations_resolve_single() -> None:
    """page-03 (2026-08-20): a single-orientation letter took the multi
    path because the report's line degrees ({0, 90}) triggered it — but
    the aspect rule corrected every line to 0 (wide boxes). With ONE
    resolved orientation, the reading order is the TRANSCRIPTION order
    (the margin blocks read block-by-block, never interleaved); the
    physical sort applies only to genuinely multi-orientation pages
    (the postcard)."""
    from tools.layout import multi_layout

    layout = multi_layout(
        "p1.jpg",
        1000,
        1000,
        [
            (
                90,
                [
                    # the rec read the horizontal lines during the 90° pass
                    {"text": "P.S. line one", "box": [100, 100, 300, 140], "score": 0.9, "words": []},
                    {"text": "theory paper", "box": [100, 150, 300, 190], "score": 0.9, "words": []},
                    {"text": "Postmark", "box": [400, 102, 600, 142], "score": 0.9, "words": []},
                ],
            ),
        ],
        report_lines=[
            {"index": 0, "box": [100, 100, 300, 140], "degrees": 0},
            {"index": 1, "box": [100, 150, 300, 190], "degrees": 0},
            {"index": 2, "box": [400, 102, 600, 142], "degrees": 90},  # a garbage label — aspect-corrected to 0
        ],
        vlm_text="P.S. line one\ntheory paper\nPostmark",
        trust_report_degrees=True,
    )
    texts = [ln["text"] for ln in layout["lines"]]
    assert texts == ["P.S. line one", "theory paper", "Postmark"], texts
    assert all(ln["orientation"] == 0 for ln in layout["lines"])


def test_block_order_reads_each_block_whole() -> None:
    """The block-aware reading order (2026-08-20, user's requirement): the
    lines cluster into physical blocks (lines sharing ink), each block
    reads WHOLE — the postcard's printed top (0°), then the vertical
    message, then the address — never the reading-start sort's row-by-row
    interleave of overlapping blocks (the 0° top and the 90° message
    bounced per line). Within a block, the TRANSCRIPTION order is
    preserved."""
    from tools.reading import order_lines as order_lines_by_blocks

    lines = [
        {"index": 0, "text": "POST CARD", "box": [1575, 73, 2240, 222], "orientation": 0},
        {"index": 1, "text": "Printed in Great Britain", "box": [1295, 246, 1995, 301], "orientation": 0},
        {"index": 2, "text": "We are from", "box": [1277, 343, 1540, 975], "orientation": 90},
        {"index": 3, "text": "beauford & Mrs", "box": [1505, 235, 1662, 1108], "orientation": 90},
        {"index": 4, "text": "Paul Wink", "box": [1999, 988, 3339, 1316], "orientation": 0},
        {"index": 5, "text": "47 Brighton Grove", "box": [2142, 1376, 3479, 1692], "orientation": 0},
    ]
    ordered = order_lines_by_blocks(lines)
    texts = [ln["text"] for ln in ordered]
    # the printed top (block 1), then the message (block 2), then the
    # address (block 3) — each whole, no interleave
    assert texts == [
        "POST CARD",
        "Printed in Great Britain",
        "We are from",
        "beauford & Mrs",
        "Paul Wink",
        "47 Brighton Grove",
    ], texts


def test_block_order_keeps_boxless_lines_in_place() -> None:
    """A boxless line has no block — it stays in its transcription
    position (the postcard's stamp lines, boxless after the arbitration,
    read after the address block)."""
    from tools.reading import order_lines as order_lines_by_blocks

    lines = [
        {"index": 0, "text": "message line", "box": [100, 100, 200, 900], "orientation": 90},
        {"index": 1, "text": "POSTAGE", "box": None, "orientation": 0},
    ]
    assert [ln["text"] for ln in order_lines_by_blocks(lines)] == ["message line", "POSTAGE"]


def test_validate_layout_catches_duplicate_region_claims() -> None:
    """Gate E (2026-08-20): two lines whose boxes claim the same region
    with DIFFERENT text is a geometry failing — the postcard's location
    report gave 'We are from' and 'beauford & Mrs' the SAME box (the
    model's message geometry duplicated). The same text in one region is
    the dedupe's job (a fragment); different texts in one region is
    ambiguity the review must see."""
    from tools.layout import validate_layout

    layout = {
        "width": 3500,
        "height": 2215,
        "lines": [
            {"text": "We are from", "box": [1505, 235, 1662, 1108], "orientation": 90},
            {"text": "beauford & Mrs", "box": [1505, 235, 1662, 1108], "orientation": 90},  # the same box
        ],
    }
    viol = validate_layout(layout)
    assert any("same region" in v for v in viol), viol
    # the same text in one region is NOT a duplicate-region violation
    layout["lines"][1]["text"] = "We are from"
    assert not [v for v in validate_layout(layout) if "same region" in v]


def test_drop_inkless_boxes_removes_blank_estimates(tmp_path) -> None:
    """Gate D (2026-08-20): a line's box must contain the ink it claims —
    page-03's transcription boxes sat ~200px above the real text, and a
    well-proportioned box in a blank region is an ESTIMATE, not an
    anchor (the gates cannot see it: in-bounds, aspect-consistent,
    text-synced). The layout stage checks the ink and drops the box —
    the line stays flagged, the page stays reviewable."""
    from tools.layout import drop_inkless_boxes

    img = Image.new("RGB", (200, 200), (255, 255, 255))
    for x in range(100, 140):
        for y in range(20, 40):
            img.putpixel((x, y), (40, 40, 40))  # ink at the TOP
    img.save(tmp_path / "p1.png")
    lines = [
        {"index": 0, "text": "real line", "box": [100, 20, 140, 40]},  # on the ink
        {"index": 1, "text": "P.S. I had a whole", "box": [100, 150, 180, 190]},  # blank region
    ]
    dropped = drop_inkless_boxes(lines, tmp_path / "p1.png")
    assert dropped == 1
    assert lines[0]["box"] == [100, 20, 140, 40]
    assert lines[1]["box"] is None, "the blank-region box is an estimate — dropped, flagged"


def test_box_overlap_is_intersection_over_the_smaller_box() -> None:
    """2026-08-20: the zero-division guard was ``min(a, b, eps)`` — the
    epsilon is the MINIMUM, so every overlap divided by 1e-9 and any
    1px intersection read as ~1e12. The dedupe, the anchor arbitration
    and Gate E all consumed the inflated value. The overlap is the
    intersection over the SMALLER box: identical = 1, disjoint = 0,
    half-covered = 0.5."""
    from tools.box import overlap as _box_overlap

    assert _box_overlap([0, 0, 100, 100], [0, 0, 100, 100]) == 1.0
    assert _box_overlap([0, 0, 100, 100], [200, 200, 300, 300]) == 0.0
    # the taller strip covers half the wide box's area, the wide box
    # fully contains the strip — over the SMALLER (the strip) = 1.0
    assert _box_overlap([0, 0, 100, 100], [25, 0, 75, 100]) == 1.0
    # half the smaller box's area is inside the other
    assert _box_overlap([0, 0, 100, 100], [50, 0, 150, 100]) == 0.5


def test_drop_conflicting_boxes_keeps_the_confirmed_anchor() -> None:
    """Gate E as a correction (2026-08-22): when two lines claim the same
    region with DIFFERENT text, the lower-confidence line's box is an
    estimate that shadows the confirmed anchor — page-03's boxless
    'critic's view. To quote:' box sat on the P.S. margin, refusing the
    whole page at the serve gate. The lower-conf box drops (the line
    stays flagged); the confirmed anchor keeps its region."""
    from tools.layout import drop_conflicting_boxes

    lines = [
        {"index": 0, "text": "P.S. I had a whole Grade 3A", "box": [526, 2247, 1044, 2294], "conf": 1.0},
        {"index": 1, "text": "critic's view. To quote:", "box": [517, 2247, 1048, 2302], "conf": 0.0},
        {"index": 2, "text": "theory paper", "box": [540, 2297, 1042, 2340], "conf": 1.0},
    ]
    dropped = drop_conflicting_boxes(lines)
    assert dropped == 1
    assert lines[0]["box"] == [526, 2247, 1044, 2294]
    assert lines[1]["box"] is None, "the unconfirmed claim on the anchor's region must drop"
    assert lines[2]["box"] == [540, 2297, 1042, 2340]


def test_box_line_count_by_projection() -> None:
    """The cheap multi-line gate (2026-08-25): the vision audit caught
    boxes enclosing 3-4 handwriting lines apiece (1782635795946's stale
    layout). A box's row-projection counts the separated ink bands it
    holds — pure PIL, no model. Bands separated by a clear blank gap
    are distinct lines; a line's own ascender/descender gaps are too
    small to split it."""
    from PIL import Image, ImageDraw

    from tools.box import text_line_count

    # one line of "writing": a wavy band with internal thin gaps
    im = Image.new("L", (400, 200), 255)
    d = ImageDraw.Draw(im)
    for x0 in range(40, 360, 21):
        d.rectangle([x0, 90, min(x0 + 13, 360), 111], fill=0)
    assert text_line_count([0, 0, 400, 200], im) == 1

    # two clean lines with a real leading gap between them
    im2 = Image.new("L", (400, 200), 255)
    d2 = ImageDraw.Draw(im2)
    d2.rectangle([40, 30, 360, 51], fill=0)
    d2.rectangle([40, 120, 360, 141], fill=0)
    assert text_line_count([0, 0, 400, 200], im2) == 2


def test_empty_box_has_no_lines() -> None:
    from PIL import Image

    from tools.box import text_line_count

    im = Image.new("L", (200, 100), 255)
    assert text_line_count([10, 10, 190, 90], im) == 0


def test_has_ink_sees_pencil_on_photo_paper() -> None:
    """Faint-pencil regression (2026-08-26): the Silver-Wedding photo's
    annotations are pencil (~level 170) on cream card (~220) — the fixed
    <128 cutoff called every box blank and the serve-walk refused pages
    whose boxes were visibly on the writing. Ink must be measured
    against the crop's OWN paper level."""
    from PIL import Image, ImageDraw

    from tools.box import has_ink

    im = Image.new("L", (300, 100), 220)
    d = ImageDraw.Draw(im)
    d.rectangle([20, 45, 280, 54], fill=168)
    assert has_ink([0, 0, 300, 100], im)

    blank = Image.new("L", (300, 100), 235)
    assert not has_ink([0, 0, 300, 100], blank)


def test_split_by_bands_divides_a_multi_line_union() -> None:
    """Band-split feedback (2026-08-26): when a measured union spans
    several handwriting lines, the image itself gives the true line
    boundaries — the projection's ink bands. Splitting before label
    matching turns too-few-rows into accurate-rows instead of refusing
    the page (the birth certificates' 40-vs-25 mismatch)."""
    from PIL import Image, ImageDraw

    from tools.ink import split_by_bands

    im = Image.new("L", (400, 200), 255)
    d = ImageDraw.Draw(im)
    d.rectangle([40, 30, 360, 51], fill=0)
    d.rectangle([60, 120, 340, 141], fill=0)
    parts = split_by_bands([20, 10, 380, 190], im)
    assert len(parts) == 2
    top, bottom = sorted(parts, key=lambda b: b[1])
    assert 25 <= top[1] <= 35 and 45 <= top[3] <= 58  # the first band's rows
    assert 115 <= bottom[1] <= 125 and 135 <= bottom[3] <= 148


def test_split_by_bands_keeps_single_line_boxes_whole() -> None:
    from PIL import Image, ImageDraw

    from tools.ink import split_by_bands

    im = Image.new("L", (400, 200), 255)
    d = ImageDraw.Draw(im)
    d.rectangle([40, 90, 360, 111], fill=0)
    box = [20, 80, 380, 120]
    assert split_by_bands(box, im) == [box]


def test_layout_skip_requires_ink_provenance() -> None:
    """The stale-shield fix (2026-08-26): page-01/08/11 served garbage
    for days because their OLD-pipeline layouts validated structurally
    clean, so the clean-skip protected them from every pipeline fix.
    Only layouts written by the current ink machinery (every line
    carrying box_source='ink') earn the skip."""
    from tools.eval_batch import layout_is_current

    assert layout_is_current({"lines": [{"box_source": "ink", "box": [0, 0, 1, 1]}]})
    assert not layout_is_current({"lines": [{"box_source": "model", "box": [0, 0, 1, 1]}]})
    assert not layout_is_current({"lines": [{"box": [0, 0, 1, 1]}]})
    assert not layout_is_current({"lines": []})


def test_gate_b_ceiling_scales_with_glyph_size() -> None:
    """The scale-aware Gate B (2026-08-26): the absolute px/char ceiling
    assumed handwriting scale and refused correctly-boxed BIG print —
    '57 Varieties' at 90 px/char on the Heinz crest, 'REMINDER',
    'POST CARD'. A letter's advance scales with its own glyph size, so
    the ceiling is the box's PERPENDICULAR extent × 1.7: big-print rows
    are also tall, mislabeled normal-height rows stay tight."""
    from tools.gates import glyph_extent_violation

    # big print: tall row, few large characters — legitimately 90px/char
    assert glyph_extent_violation("57 Varieties", [0, 0, 1080, 220], 0) is None
    # normal-height row, sparse text: still refused (the mismatch guard)
    assert glyph_extent_violation("Windsor.", [0, 0, 1150, 55], 0) is not None


def test_gate_b_density_direction_unchanged() -> None:
    """Too-many-chars-in-a-small-box still fails exactly as before —
    the birth certificates' 67-char labels on tiny rows."""
    from tools.gates import glyph_extent_violation

    assert glyph_extent_violation("x" * 67, [0, 0, 45, 300], 90) is not None


def test_selfreport_flags_mark_words_in_the_layout() -> None:
    """The wiring seam (2026-08-26): the self-report stage exists
    (selfreport_words + build_layout's conf-0.0 flagging) but the batch
    never runs it — the UI's "red words are ones the machine wasn't
    sure of" promise goes unmet on every served layout. These helpers
    are the missing link: tokenize a line into the layout's word dicts
    and mark the flagged ones."""
    from tools.text import flag_line_words, selfreport_by_line

    words = flag_line_words("No peace eh? Hah !", {"peace"})
    flagged = [w["word"] for w in words if w["conf"] == 0.0]
    assert flagged == ["peace"], flagged
    assert all(w["conf"] == 1.0 for w in words if w["word"] != "peace")

    # the report cites "Peace" — matching is case/punct-insensitive
    words2 = flag_line_words("No peace eh?", {"Peace"})
    assert [w["word"] for w in words2 if w["conf"] == 0.0] == ["peace"]

    # the line→flags map, 0-based, keyed per line index
    report = [{"line": 2, "word": "gen"}, {"line": 1, "word": "qualms"}]
    by_line = selfreport_by_line(report, 3)
    assert by_line == {0: {"qualms"}, 1: {"gen"}}

    # out-of-range lines are ignored; empty report maps to nothing
    assert selfreport_by_line([{"line": 9, "word": "x"}], 3) == {}
    assert selfreport_by_line([], 2) == {}


def test_selfreport_flags_match_by_word_content() -> None:
    """The index-misalignment fix (2026-08-26): the self-report cites
    line numbers of the RAW VLM text, but out_lines' indices come from
    proportional matching — the numbers drift when the raw text has
    empty lines. The word is the reliable key: match each flagged word
    against the lines that actually contain it."""
    from tools.text import selfreport_words_by_line

    lines = ["No peace eh?", "Have the gen", "So much for your qualms"]
    by_line = selfreport_words_by_line(lines, [{"line": 1, "word": "Peace"}, {"line": 2, "word": "GEN"}])
    assert by_line == {0: {"peace"}, 1: {"gen"}}, by_line

    # a cited word that drifted to the wrong line number still lands on
    # the line that contains it
    shifted = selfreport_words_by_line(lines, [{"line": 3, "word": "peace"}])
    assert shifted == {0: {"peace"}}, shifted

    # a word nowhere in the text flags nothing
    assert selfreport_words_by_line(lines, [{"line": 1, "word": "nonexistent"}]) == {}


class TestRegionReadRescue:
    """The rotated-region rescue (model-trial-report §6): when the plain
    or multi-orientation build refuses (the detector misses boxes on
    rotated text), the ink's x-projection regions are each read by the
    VLM at their own orientation and the layout rebuilt from those
    reads (2026-08-30 — the postcard eval's boxless refusals)."""

    @staticmethod
    def _fake_read(lines_per_region: dict[int, list[dict]]):
        def fake(crop, image_path, tmp, index, model, base_url, api_key):
            lines = lines_per_region.get(index)
            if lines is None:
                return None
            return ([{**ln} for ln in lines], 100)

        return fake

    def test_stitches_region_lines_into_the_page_frame(self, tmp_path: Path) -> None:
        from tools.layout_detect import _region_read_rescue

        image = tmp_path / "back.jpg"
        # two ink columns so the x-projection finds two regions (the
        # message column and the address column, as on the postcard)
        with Image.new("L", (2000, 1500), 255) as im:
            from PIL import ImageDraw

            d = ImageDraw.Draw(im)
            d.rectangle([100, 200, 800, 1300], fill=0)
            d.rectangle([1200, 150, 1900, 600], fill=0)
            im.save(image)

        calls: list[tuple] = []

        def fake(crop, image_path, tmp, index, model, base_url, api_key):
            # the upright address column's crop read (the rotated regions
            # never reach read_crop). The line physically sits at region
            # y 300-520; each band read reports it in the BAND's local
            # frame — as a real read would — so the two bands' overlap
            # reads stitch back to the same page box.
            phys_y0, phys_y1 = 300.0, 520.0
            local_y0 = phys_y0 - (crop.y - 150.0)
            local_y1 = phys_y1 - (crop.y - 150.0)
            return (
                [
                    {
                        "text": "12 Kensington Gore",
                        "box": [8.0, local_y0, 250.0, local_y1],
                        "orientation": 0,
                    }
                ],
                90,
            )

        # the pipeline's orientation report locates the known text: the
        # message panel's lines at 90°, the address upright
        report_lines = [
            {"index": 0, "box": [50, 50, 950, 120], "degrees": 0},
            {"index": 1, "box": [50, 150, 600, 400], "degrees": 90},
        ]

        class _FakeRotEngine:
            """Serves the rotated panel's rec pass: three piece-boxes
            aligned with the panel-read's bands so the row-clustering
            measures the message's lines."""

            def predict(self, input, return_word_box=False):
                return [
                    {
                        "dt_polys": [
                            [[100, 1121], [300, 1121], [300, 1168], [100, 1168]],
                            [[100, 472], [300, 472], [300, 519], [100, 519]],
                            [[100, 118], [300, 118], [300, 165], [100, 165]],
                        ],
                        "rec_texts": ["noise", "noise", "noise"],
                        "rec_scores": [0.9, 0.9, 0.9],
                    }
                ]

        import json as _json

        def fake_transcribe(panel_path, *, model, system, base_url, api_key, max_tokens):
            # the model's read of the whole rotated panel: the JSON the
            # system prompt requests — clean lines + normalized boxes as
            # y-bands across the rotated panel
            return (
                _json.dumps(
                    {
                        "lines": [
                            {"text": "POST CARD.", "box": [10, 950, 990, 990]},
                            {"text": "the message line", "box": [10, 400, 990, 440]},
                            {"text": "With greetings", "box": [10, 100, 990, 140]},
                        ]
                    }
                ),
                {"total_tokens": 120},
            )

        layout = _region_read_rescue(
            image,
            tmp_path,
            _FakeRotEngine(),
            report_lines=report_lines,
            seams=(fake, fake_transcribe),
        )
        assert layout is not None
        # every contract line is present: the rotated panel's three lines
        # plus the upright address column's read
        # the reading order: the rotated columns' remapped x-positions
        # left-to-right, then the upright address column
        texts = [ln["text"] for ln in layout["lines"]]
        assert texts == [
            "POST CARD.",
            "the message line",
            "With greetings",
            "12 Kensington Gore",
        ], texts
        # the rotated column's lines carry the vertical orientation (the
        # ≥2-orientation contract); the upright region's stays 0
        by_text = {ln["text"]: ln for ln in layout["lines"]}
        assert by_text["the message line"]["orientation"] == 90, by_text["the message line"]
        assert by_text["With greetings"]["orientation"] == 90
        assert by_text["12 Kensington Gore"]["orientation"] == 0
        # every stitched box stays inside the page and carries words with
        # text (the review renders them)
        for ln in layout["lines"]:
            box = ln["box"]
            assert 0 <= box[0] < box[2] <= layout["width"] and 0 <= box[1] < box[3] <= layout["height"], box
            assert ln["words"] and all(w["word"] for w in ln["words"])
        # the model used is the image route
        assert all(c[4] == "dynamic/image" for c in calls)

    def test_dedupe_drops_slabs_shadowed_by_longer_lines(self) -> None:
        """§6 step 6: overlapping boxes claim the same region — keep the
        longer transcription."""
        from tools.layout_detect import _dedupe_region_lines

        lines = [
            {"text": "the message line", "box": [105, 250, 700, 290]},
            {"text": "the mess", "box": [104, 248, 300, 292]},
            {"text": "with greetings", "box": [110, 500, 400, 540]},
        ]
        kept = _dedupe_region_lines(lines)
        assert [ln["text"] for ln in kept] == ["the message line", "with greetings"]

    def test_returns_none_when_no_regions_or_no_reads(self, tmp_path: Path) -> None:
        from tools.layout_detect import _region_read_rescue

        blank = tmp_path / "blank.jpg"
        Image.new("L", (800, 600), 255).save(blank)  # no ink — no regions
        assert _region_read_rescue(blank, tmp_path, engine=None, seams=(self._fake_read({}), None)) is None

        inked = tmp_path / "inked.jpg"
        with Image.new("L", (2000, 1500), 255) as im:
            # ink exists but every read fails
            from PIL import ImageDraw

            ImageDraw.Draw(im).rectangle([100, 100, 1500, 1400], outline=0)
            im.save(inked)
        assert _region_read_rescue(inked, tmp_path, engine=None, seams=(lambda *a, **k: None, None)) is None
