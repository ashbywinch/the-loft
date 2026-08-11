"""The transcription-fidelity flow (2026-08-10).

Pins the literal-transcription requirement (IMPORT-PRD Rule L, amended:
"a transcription is the document's text, verbatim — nothing added, nothing
removed") against the real OCR pipeline: ``ocr_pages`` must reproduce the
document's text, and the orientation pass (Rule J) must handle a rotated
page before reading it. The session fixture runs the flow ONCE; the
condition tests verify the single output against the ground truth.

The fixture is a PUBLIC-DOMAIN printed document — the Dunlap broadside of
the United States Declaration of Independence (NARA image, US government
work) — deliberately unrelated to the family, so this flow can run in the
public repo without carrying any family content (2026-08-10, user: "we
should be careful to get a copyright free small image to OCR that is not
related to my family"). The ground truth is the document's own 1776 text,
in its 1776 spelling (the long-s renders as f: "Courfe").
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from tools.ocr import ocr_pages


class TranscriptionFlow:
    """The literal-transcription pipeline — OCR the public-domain fixture
    as-scanned and rotated 90 degrees; the document's own words must
    survive both. One run, many conditions (2026-08-10, user)."""

    name: str = "transcription fidelity"
    fixture: Path = Path("tests/fixtures/declaration-broadside.jpg")

    # The broadside's own words — the ground truth of the printed page. The
    # 18th-century type defeats tesseract on some words (the long-s renders
    # as f; "Liberty"/"Happiness" garble at every resolution we tried), so
    # the phrases are the ones the typeface reliably recognizes — and they
    # are the document's actual text, never a paraphrase.
    ground_truth: list[str] = [
        "united states of america",
        "representatives",
        "human events",
    ]
    orientations: tuple[str, ...] = ("as-scanned", "rotated-90")


def run_flow() -> dict[str, str]:
    """Run the OCR pipeline ONCE — the fixture as-scanned and rotated 90
    degrees. The condition tests verify the single output against the
    ground truth (one run, many conditions)."""
    outputs: dict[str, str] = {}
    tmp: Path | None = None
    try:
        rotated = Path(tempfile.mkstemp(suffix=".jpg")[1])
        tmp = rotated  # assigned before the run so cleanup always happens (2026-08-11 review)
        result = subprocess.run(
            ["magick", str(TranscriptionFlow.fixture), "-rotate", "90", str(rotated)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"magick rotation failed on {TranscriptionFlow.fixture}: {result.stderr[:200]}")
        outputs["as-scanned"] = ocr_pages([TranscriptionFlow.fixture])[0]
        outputs["rotated-90"] = ocr_pages([rotated])[0]
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return outputs


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def condition_ground_truth(outputs: dict[str, str], phrase: str, orientation: str) -> str | None:
    """The document's word ``phrase`` must survive the ``orientation``
    read — a transcription that loses the document's words is not a
    transcription."""
    if phrase not in _norm(outputs[orientation]):
        return f"{orientation}: the transcription lost the document's words: {phrase!r}"
    return None
