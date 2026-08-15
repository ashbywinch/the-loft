"""Tests for the OCR seam: the orientation arbiter's auditable output shape
and its verdict on a generated text card — upright, so 0 degrees must win.

No committed fixture: the transcription-fidelity eval's printed-document
fixture was deliberately removed with its eval (the transcription backend
is the vision model, not the local tesseract path — user, 2026-08-15).
Orientation still runs in production — the pipeline orients every text page
before the vision model reads it — so the arbiter keeps its real-tool tests,
on a card the test renders itself (Pillow's bundled font, no system font
dependency).
"""

from __future__ import annotations

from pathlib import Path

from tools.ocr import orient_pages


def _text_card(path: Path) -> None:
    """Render a text-bearing card for the orientation tests."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1600, 700), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=72)
    lines = ["The family history album", "letters photographs documents", "and the stories they carry"]
    y = 60
    for line in lines:
        width = draw.textlength(line, font=font)
        draw.text(((1600 - width) / 2, y), line, fill="black", font=font)
        y += 110
    img.save(path)


def test_orient_pages_records_the_audit_trail(tmp_path: Path) -> None:
    card = tmp_path / "card.png"
    _text_card(card)
    results = orient_pages([card], tmp_path / "oriented")
    assert len(results) == 1
    page = results[0]
    assert page["name"] == card.name
    assert page["degrees"] == 0  # the card is upright; the arbiter must keep it
    assert page["strong"] > 0
    assert set(page["scores"]) == {"0", "90", "180", "270"}
    assert page["scores"]["0"] == page["strong"]
    assert (tmp_path / "oriented" / card.name).exists()


def test_orient_pages_rotated_input_is_fixed(tmp_path: Path) -> None:
    import subprocess

    card = tmp_path / "card.png"
    _text_card(card)
    rotated = tmp_path / "rotated.png"
    subprocess.run(["magick", str(card), "-rotate", "180", str(rotated)], check=True, capture_output=True)

    results = orient_pages([rotated], tmp_path / "oriented")
    page = results[0]
    assert page["degrees"] == 180  # the arbiter must turn it back
    assert page["scores"]["180"] > page["scores"]["0"]
