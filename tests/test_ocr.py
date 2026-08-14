"""Tests for the OCR seam: the orientation arbiter's auditable output shape
and its verdict on the public-domain printed fixture (the same fixture the
transcription-fidelity eval uses — upright, so 0 degrees must win)."""

from __future__ import annotations

from pathlib import Path

from tools.ocr import orient_pages

FIXTURE = Path("tests/fixtures/declaration-broadside.jpg")


def test_orient_pages_records_the_audit_trail(tmp_path: Path) -> None:
    results = orient_pages([FIXTURE], tmp_path / "oriented")
    assert len(results) == 1
    page = results[0]
    assert page["name"] == FIXTURE.name
    assert page["degrees"] == 0  # the fixture is upright; the arbiter must keep it
    assert page["strong"] > 0
    assert set(page["scores"]) == {"0", "90", "180", "270"}
    assert page["scores"]["0"] == page["strong"]
    assert (tmp_path / "oriented" / FIXTURE.name).exists()


def test_orient_pages_rotated_input_is_fixed(tmp_path: Path) -> None:
    import subprocess

    rotated = tmp_path / "rotated.jpg"
    subprocess.run(["magick", str(FIXTURE), "-rotate", "180", str(rotated)], check=True, capture_output=True)

    results = orient_pages([rotated], tmp_path / "oriented")
    page = results[0]
    assert page["degrees"] == 180  # the arbiter must turn it back
    assert page["scores"]["180"] > page["scores"]["0"]
