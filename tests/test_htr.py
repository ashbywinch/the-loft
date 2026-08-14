"""Tests for the HTR stage's pure geometry: per-line crop boxes from orli
baselines. The model calls (kraken segment, TrOCR) run on the real pages."""

from __future__ import annotations

from pathlib import Path

from tools.htr import line_boxes


def test_line_boxes_uses_the_per_line_gap() -> None:
    lines = [
        {"baseline": [[10, 100], [200, 100]]},  # cursive line, big gap to the next
        {"baseline": [[10, 180], [200, 180]]},  # dense line, small gap
        {"baseline": [[10, 240], [200, 240]]},
    ]
    boxes = line_boxes(lines)
    first_height = boxes[0][3] - boxes[0][1]
    dense_height = boxes[1][3] - boxes[1][1]
    assert first_height > dense_height  # per-line gaps, not a global median
    assert boxes[0][1] < 100 < boxes[0][3]  # the baseline sits inside its crop
    assert boxes[1][3] <= boxes[2][1]  # crops do not overlap


def test_line_boxes_orders_by_reading_order() -> None:
    lines = [
        {"baseline": [[10, 300], [200, 300]]},
        {"baseline": [[10, 100], [200, 100]]},
    ]
    boxes = line_boxes(lines)
    assert boxes[0][1] < boxes[1][1]  # top-to-bottom, not detection order


def test_htr_pages_vlm_writes_text_and_marker_then_skips(tmp_path: Path) -> None:
    from tools.htr import htr_pages_vlm

    page = tmp_path / "p1.jpg"
    page.write_bytes(b"image")
    raw = tmp_path / "ocr-raw"
    calls = {"n": 0}

    def fake_transcribe(image: Path) -> tuple[str, dict[str, int]]:
        calls["n"] += 1
        assert image == page
        return "Chère Maman.", {"total_tokens": 11000}

    htr_pages_vlm([("p1.jpg", page)], raw, transcribe=fake_transcribe)
    assert (raw / "p1.txt").read_text(encoding="utf-8") == "Chère Maman."
    assert (raw / "p1.vlm.json").exists()

    htr_pages_vlm([("p1.jpg", page)], raw, transcribe=fake_transcribe)  # re-run
    assert calls["n"] == 1  # the marker skipped the second call — resumable and cheap
