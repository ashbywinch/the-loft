"""The no-family-PII guard (user): the public repo (the-loft)
ships code and synthetic fixtures, never family content. Every identifying
name, alias, email and place from the live dataset must be absent from the
tracked files — the markers load from the gitignored archive at runtime, or
from the `PII_MARKERS` CI secret where the archive is absent, so this file
contains none of them.

The guard runs locally (the archive is in the working tree) and in CI (the
secret supplies the markers); it scans TEXT files only — a binary's bytes are
not a text leak, and scanning images as text produced false positives. The
images themselves are a content decision, not this check's.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tools.loft_paths import LoftPaths
from tools.pii_markers import family_markers, file_offenders

REPO = Path(__file__).resolve().parent.parent


def _marker_source() -> bool:
    """The guard runs where the markers are: the local archive, or the
    `PII_MARKERS` secret CI supplies (the archive is never in the checkout)."""
    return bool(os.environ.get("PII_MARKERS", "").strip()) or (LoftPaths.ARCHIVE_DIR / "people.json").exists()


@pytest.mark.archive
@pytest.mark.skipif(not _marker_source(), reason="no marker source: neither the archive nor PII_MARKERS is present")
def test_no_family_pii_in_tracked_files() -> None:
    markers = family_markers()
    assert markers, "no markers loaded — the dataset lookup must have found the family"
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    # fast path: one compiled alternation per file instead of one re.search
    # compilation per marker per file (the 30 s hotspot). Emails
    # compared lowercased — the same case the authoritative scan normalises.
    emails = sorted(m for m in markers if "@" in m)
    words = sorted(m for m in markers if "@" not in m)
    any_marker = re.compile(r"\b(?:" + "|".join(re.escape(m) for m in words) + r")\b")

    offenders: list[str] = []
    for name in tracked:
        if name in ("tools/pii_markers.py", "tests/test_pii_markers.py"):
            continue  # the guard and its own contract: they name marker literals by design
        path = REPO / name
        if not path.exists():
            continue  # deleted in the working tree
        data = path.read_bytes()
        if b"\x00" in data[:8192]:
            continue  # a binary (image, font, archive): the guard is a text check
        text = data.decode("utf-8", errors="replace")
        lowered = text.lower()
        if not any_marker.search(text) and not any(e.lower() in lowered for e in emails):
            continue
        # an offending file: identify the markers (rare path, so per-marker is fine)
        for marker in file_offenders(text, markers, name):
            offenders.append(f"{name}: {marker}")
    assert not offenders, "family PII in tracked files (the public repo would ship it):\n" + "\n".join(offenders[:40])
