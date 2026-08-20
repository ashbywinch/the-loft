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
    seen_systems: list[str] = []

    def fake_transcribe(image: Path, *, system: str) -> tuple[str, dict[str, int]]:
        calls["n"] += 1
        assert image == page
        seen_systems.append(system)
        return "Chère Maman.", {"total_tokens": 11000}

    htr_pages_vlm(
        [("p1.jpg", page)],
        raw,
        transcribe=fake_transcribe,
        people=["Alex Hale"],
        places=["Kensington Gore"],
        label="First test pile",
    )
    assert (raw / "p1.txt").read_text(encoding="utf-8") == "Chère Maman."
    assert (raw / "p1.vlm.json").exists()
    # the context the model reads with rides the system prompt
    assert "Alex Hale" in seen_systems[0]
    assert "Kensington Gore" in seen_systems[0]
    assert "First test pile" in seen_systems[0]

    htr_pages_vlm([("p1.jpg", page)], raw, transcribe=fake_transcribe)  # re-run
    assert calls["n"] == 1  # the marker skipped the second call — resumable and cheap


def test_htr_pages_vlm_re_transcribes_when_marker_has_no_text(tmp_path: Path) -> None:
    """A completion marker with a missing or empty .txt is a stale/partial
    write (2026-08-20: a bad layout_detect run left page-02's marker while
    clearing its text). The stage must re-transcribe, never silently
    "reuse" the corrupt guess."""
    from tools.htr import htr_pages_vlm

    page = tmp_path / "p1.jpg"
    page.write_bytes(b"image")
    raw = tmp_path / "ocr-raw"
    raw.mkdir(parents=True)
    calls = {"n": 0}

    def fake_transcribe(image: Path, *, system: str) -> tuple[str, dict[str, int]]:
        calls["n"] += 1
        return "Chère Maman.", {"total_tokens": 11000}

    # A stale marker with NO text file — the corrupt-state shape.
    (raw / "p1.vlm.json").write_text("{}", encoding="utf-8")
    htr_pages_vlm([("p1.jpg", page)], raw, transcribe=fake_transcribe)
    assert calls["n"] == 1, "the stale marker must not suppress the re-transcription"
    assert (raw / "p1.txt").read_text(encoding="utf-8") == "Chère Maman."

    # A marker with an EMPTY text file — also stale.
    (raw / "p1.txt").write_text("", encoding="utf-8")
    htr_pages_vlm([("p1.jpg", page)], raw, transcribe=fake_transcribe)
    assert calls["n"] == 2, "an empty .txt must not count as completed"
    assert (raw / "p1.txt").read_text(encoding="utf-8") == "Chère Maman."

    # Now complete: marker + non-empty text — the stage skips.
    htr_pages_vlm([("p1.jpg", page)], raw, transcribe=fake_transcribe)
    assert calls["n"] == 2, "complete artifacts must skip the call"


def test_htr_pages_vlm_writes_geometry_when_the_model_complies(tmp_path: Path) -> None:
    """The VLM's JSON response (lines + normalized boxes) lands as the .txt
    (the plain transcription — the downstream reads the same shape) and the
    .vlm.json's ``lines`` (the geometry the layout pass anchors with). A
    plain-text response writes no geometry — the old fallback stands."""
    import json

    from tools.htr import htr_pages_vlm

    page = tmp_path / "p1.jpg"
    page.write_bytes(b"image")
    raw = tmp_path / "ocr-raw"

    def fake_json(image: Path, *, system: str) -> tuple[str, dict[str, int]]:
        return (
            '{"lines": [{"text": "piano-practising facilities. At the", "box": [219, 496, 760, 526]}, '
            '{"text": "moment it looks awfully complicated,", "box": [234, 513, 733, 543]}]}',
            {"total_tokens": 11000},
        )

    htr_pages_vlm([("p1.jpg", page)], raw, transcribe=fake_json)
    assert (raw / "p1.txt").read_text(encoding="utf-8") == (
        "piano-practising facilities. At the\nmoment it looks awfully complicated,"
    )
    marker = json.loads((raw / "p1.vlm.json").read_text(encoding="utf-8"))
    assert marker["lines"] == [
        {"text": "piano-practising facilities. At the", "box": [219.0, 496.0, 760.0, 526.0]},
        {"text": "moment it looks awfully complicated,", "box": [234.0, 513.0, 733.0, 543.0]},
    ]
    assert marker["total_tokens"] == 11000  # the usage still rides along

    # a second page whose model returns plain text — no geometry, no crash
    page2 = tmp_path / "p2.jpg"
    page2.write_bytes(b"image2")

    def fake_plain(image: Path, *, system: str) -> tuple[str, dict[str, int]]:
        return "Chère Maman.", {"total_tokens": 3000}

    htr_pages_vlm([("p2.jpg", page2)], raw, transcribe=fake_plain)
    assert (raw / "p2.txt").read_text(encoding="utf-8") == "Chère Maman."
    marker2 = json.loads((raw / "p2.vlm.json").read_text(encoding="utf-8"))
    assert "lines" not in marker2
