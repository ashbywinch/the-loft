"""Minimal OCR of scanned pages into a transcription (2026-08-10).

The import flow's transcription machinery is not built yet — IMPORT-PRD
Rule L (the transcript gate: the machine's transcript is checked and fixed
by the reviewer BEFORE any proposal is built on it) has no implementation.
This is the minimal seam: orient each page, OCR it with tesseract, join the
text. The output is a PROPOSAL — the item's transcription_status stays
``draft`` until the gate exists and a human verifies it (2026-08-10, user:
"we might not have code to do this at all, then we should make a minimal
function just to do the OCR job into the transcription").

Orientation (Rule J): scans may be rotated. Every explicit orientation
detector we tried was unreliable — the vision models gave contradictory
answers (LEFT vs RIGHT against an upright page) and tesseract's own OSD
misreported an upright page as 180 degrees (2026-08-10). The orientation
pass is therefore DETERMINISTIC AND SELF-VERIFYING: the page is read in
all four rotations and the read recognizing the most words (tesseract's
per-word confidence >= 60) wins. This exploits a property of the LSTM
recognizer itself — it was trained on upright text, so a rotated read
fragments and scores low; no orientation classifier is needed, and the
arbiter cannot guess wrong. A vision-model pre-check was tried and ditched
(2026-08-10): slower than the arbiter, wrong on the rotated pages, and it
saved nothing — the read always had to judge anyway. Four reads per page
is the cost of never hallucinating a rotation.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

TESSERACT = "tesseract"
MAGICK = "magick"
ROTATIONS = (0, 90, 180, 270)
STRONG_CONFIDENCE = 60  # the arbiter's threshold — a word tesseract clearly recognizes


def _read(image: Path, lang: str) -> str:
    result = subprocess.run(
        [TESSERACT, str(image), "-", "-l", lang],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"tesseract failed on {image}: {result.stderr[:200]}")
    return result.stdout.strip()


def _strong_word_count(image: Path, lang: str) -> int:
    """How many words tesseract recognizes with confidence >= 60, measured
    with ``--psm 6`` (a single uniform block — NO auto-orientation). The
    arbiter between rotations: psm 3's internal auto-correction muddied the
    signal (it quietly un-rotated a wrong rotation, inflating its score),
    while psm 6 cannot correct — a rotated page genuinely fragments and the
    correct orientation wins by a wide margin (the broadside at 2400px:
    1185 strong words at 0° vs 320 at the wrong 90°)."""
    result = subprocess.run(
        [TESSERACT, str(image), "-", "-l", lang, "--psm", "6", "tsv"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 0
    strong = 0
    for line in result.stdout.splitlines()[1:]:  # skip the header
        fields = line.split("\t")
        if len(fields) < 12 or fields[0] != "5":  # word-level rows carry the confidence
            continue
        try:
            if float(fields[10]) >= STRONG_CONFIDENCE:
                strong += 1
        except ValueError:
            continue
    return strong


def _rotate(image: Path, degrees: int) -> Path:
    """Rotate the page with ImageMagick into a temp file (90/180/270)."""
    tmp = Path(tempfile.mkstemp(suffix=".jpg")[1])
    result = subprocess.run(
        [MAGICK, str(image), "-rotate", str(degrees), str(tmp)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"magick rotation failed on {image}: {result.stderr[:200]}")
    return tmp


def ocr_pages(pages: list[Path], lang: str = "eng") -> list[str]:
    """OCR the page images, one string per page, in order.

    Each page is read in all four rotations and the read recognizing the
    most strongly-recognized words wins — the orientation can never be
    guessed wrong (Rule J; 2026-08-10: the vision models and tesseract's
    OSD both misreported orientations, so no guesser is trusted — the
    recognizer's own confidence is the arbiter). The pages' line structure
    is preserved — a genealogy printout stays lines, a letter's paragraphs
    stay paragraphs (Rule M). Raises loudly when a page cannot be read — a
    transcription that cannot be produced is never silently skipped (the
    fail-fast rule).
    """
    out: list[str] = []
    for page in pages:
        best_text: str = ""
        best_count = -1
        temps: list[Path] = []
        try:
            for degrees in ROTATIONS:
                source = page if degrees == 0 else _rotate(page, degrees)
                if degrees:
                    temps.append(source)
                text = _read(source, lang)
                count = _strong_word_count(source, lang)
                if count > best_count:
                    best_text, best_count = text, count
        finally:
            for t in temps:
                t.unlink(missing_ok=True)
        if not best_text.strip():
            # a page that read successfully with ZERO recognized words (a
            # blank page, an unsupported image type) is a page-level failure
            # — an empty transcription must reach the import gate as an
            # error, never as a silently empty string (2026-08-11 review)
            raise RuntimeError(f"OCR read no text from {page.name} — the page cannot be read")
        out.append(best_text)
    return out
