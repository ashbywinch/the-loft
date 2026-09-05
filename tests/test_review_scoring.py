"""The calibration regression gate (2026-08-26): the served archive's
transcription coverage against the reference set — the first measured
numbers for the pipeline (aggregate 0.68 on serving pages when written;
page-03 0.62, page-10 0.77). A change that drops serving coverage
below the floor fails here. The references are real family text and
live OUTSIDE the repo (work/eval-htr/reference-lines.json) — skip when
absent."""

from __future__ import annotations

import json

import pytest

from tools.eval_scoring import score_page
from tools.loft_paths import WORK_DIR

REFS = WORK_DIR / "eval-htr" / "reference-lines.json"
FLOOR = 0.55  # under the measured 0.68 — headroom for honest refusals


@pytest.mark.archive
@pytest.mark.skipif(not REFS.is_file(), reason="the reference set is not on the work disk")
def test_serving_coverage_stays_above_the_floor() -> None:
    refs = json.loads(REFS.read_text(encoding="utf-8"))
    pages = [
        ("adopt-20260813-201004", "page-03", "page-03"),
        ("adopt-20260813-201004", "page-10", "page-10"),
        ("adopt-20260813-201024", "1697568038221-787c9ba9-6924-48e3-a703-9ea9135998fd", "1697568038221-787c9ba9"),
        ("adopt-20260813-201024", "1781706279582-ff480f6a-5ae8-41fc-b606-b42ccc49cbfd", "1781706279582-ff480f6a"),
        ("adopt-20260813-201024", "1698767885327-9371821c-1681-4893-89f7-76bff11b3151", "1698767885327-9371821c"),
    ]
    scores = []
    refused = 0
    for batch, page, refkey in pages:
        lp = WORK_DIR / batch / "ocr-guess" / f"{page}.layout.json"
        layout = json.loads(lp.read_text(encoding="utf-8")) if lp.is_file() else None
        s = score_page(" ".join(refs[refkey]), layout)
        refused += s["refused"]
        if not s["refused"]:
            scores.append(s)
    serving = [s for s in scores if not s["refused"]]
    assert serving, "no serving pages in the reference set to score"
    matched = sum(s["matched"] for s in serving)
    total = sum(s["total"] for s in serving)
    coverage = matched / total
    assert coverage >= FLOOR, (
        f"serving coverage dropped to {coverage:.2f} (floor {FLOOR}); {refused} pages refused (captured, not failed)"
    )
