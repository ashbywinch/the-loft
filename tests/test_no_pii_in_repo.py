"""The no-family-PII guard (2026-08-08, user): the public repo (the-loft)
ships code and synthetic fixtures, never family content. Every identifying
name, alias, email and place from the live dataset must be absent from the
tracked files — the markers load from the gitignored archive at runtime, so
this file contains none of them.

Dataset-skipped like the other archive evals: CI's checkout has no archive,
so there is nothing to load and nothing to check; the local environment runs
it against the real dataset (docs/testing-standards.md).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tools.loft_paths import ARCHIVE_DIR
from tools.pii_markers import family_markers

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE_DIR / "people.json").exists(), reason="archive not bootstrapped yet")
def test_no_family_pii_in_tracked_files() -> None:
    markers = family_markers()
    assert markers, "no markers loaded — the dataset lookup must have found the family"
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    # fast path: one compiled alternation per file instead of one re.search
    # compilation per marker per file (the 30 s hotspot, 2026-08-13)
    emails = sorted(m for m in markers if "@" in m)
    words = sorted(m for m in markers if "@" not in m)
    any_marker = re.compile(r"\b(?:" + "|".join(re.escape(m) for m in words) + r")\b")

    offenders: list[str] = []
    for name in tracked:
        path = REPO / name
        if not path.exists():
            continue  # deleted in the working tree
        text = path.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        if not any_marker.search(text) and not any(e in lowered for e in emails):
            continue
        # an offending file: identify the markers (rare path, so per-marker is fine)
        for marker in markers:
            if "@" in marker:
                if marker.lower() in lowered:
                    offenders.append(f"{name}: {marker}")
            elif re.search(r"\b" + re.escape(marker) + r"\b", text):
                offenders.append(f"{name}: {marker}")
    assert not offenders, "family PII in tracked files (the public repo would ship it):\n" + "\n".join(offenders[:40])
