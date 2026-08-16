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

import os
import subprocess
import tempfile
from pathlib import Path
from typing import TypedDict

from tools.atomic import atomic_write

TESSERACT = "tesseract"
MAGICK = "magick"
ROTATIONS = (0, 90, 180, 270)
STRONG_CONFIDENCE = 60  # the arbiter's threshold — a word tesseract clearly recognizes
# The tesseract TSV layout (--psm 6 tsv output): word-level rows have 12
# columns; the per-word confidence is column 10 (0-based).
TSV_COLUMN_COUNT = 12
TSV_CONFIDENCE_COLUMN = 10


class OrientedPage(TypedDict):
    name: str
    text: str
    strong: int  # the winner's strong-word count
    degrees: int  # the winning rotation
    scores: dict[str, int]  # strong counts per rotation — the audit trail


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
        if len(fields) < TSV_COLUMN_COUNT or fields[0] != "5":  # word-level rows carry the confidence
            continue
        try:
            if float(fields[TSV_CONFIDENCE_COLUMN]) >= STRONG_CONFIDENCE:
                strong += 1
        except ValueError:
            continue
    return strong


def _rotate(image: Path, degrees: int) -> Path:
    """Rotate the page with ImageMagick into a temp file (90/180/270)."""
    fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)  # magick opens the path itself; the fd would leak (2026-08-11 review)
    tmp = Path(tmp_path)
    _rotate_to(image, degrees, tmp)
    return tmp


def _rotate_to(image: Path, degrees: int, out: Path) -> None:
    """Rotate ``image`` by ``degrees`` into ``out`` (ImageMagick), published
    write-then-rename — magick streams into a temp sibling, then rename."""
    fd, tmp_name = tempfile.mkstemp(dir=out.parent, suffix=".tmp")
    os.close(fd)  # magick opens the path itself; the fd would leak
    tmp = Path(tmp_name)
    try:
        result = subprocess.run(
            [MAGICK, str(image), "-rotate", str(degrees), str(tmp)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"magick rotation failed on {image}: {result.stderr[:200]}")
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)


def orient_pages(
    pages: list[Path],
    out_dir: Path,
    lang: str = "eng",
    root: Path | None = None,
) -> list[OrientedPage]:
    """Orient each page (Rule J's confidence arbiter), persist the winning
    rotation, and read it. LENIENT: a page with no strongly-recognized words
    (handwriting) still returns its best read — this is the raw stage, the
    model guess fixes it; the strict ``ocr_pages`` remains the eval's
    contract. One OrientedPage per page, in input order. The oriented file
    mirrors the input's path relative to ``root`` (nested piles keep their
    structure; without ``root`` the basename is used).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[OrientedPage] = []
    for page in pages:
        best_text: str = ""
        best_count = -1
        best_degrees = 0
        scores: dict[str, int] = {}
        temps: list[Path] = []
        try:
            for degrees in ROTATIONS:
                source = page if degrees == 0 else _rotate(page, degrees)
                if degrees:
                    temps.append(source)
                text = _read(source, lang)
                count = _strong_word_count(source, lang)
                scores[str(degrees)] = count
                if count > best_count:
                    best_text, best_count, best_degrees = text, count, degrees
        finally:
            for t in temps:
                t.unlink(missing_ok=True)
        oriented = out_dir / (page.relative_to(root) if root else page.name)
        oriented.parent.mkdir(parents=True, exist_ok=True)
        if best_degrees == 0:
            atomic_write(oriented, page.read_bytes())
        else:
            _rotate_to(page, best_degrees, oriented)
        results.append(
            {
                "name": str(oriented.relative_to(out_dir)),
                "text": best_text,
                "strong": best_count,
                "degrees": best_degrees,
                "scores": scores,
            }
        )
    return results


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
        if not best_text.strip() or best_count < 1:
            # a page whose best read yields no strongly-recognized words (a
            # blank page, an unsupported image type, a scan too poor to
            # trust) is a page-level failure — an empty or garbage-only
            # transcription must reach the import gate as an error, never
            # as a silently meaningless string (2026-08-11 review)
            raise RuntimeError(f"OCR read no reliable text from {page.name} — the page cannot be read")
        out.append(best_text)
    return out
