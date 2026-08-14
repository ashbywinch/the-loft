"""The place-note eval — a place's note is what the reader sees as the
place's description; it must never carry the machine's process status
("verification pending (Rule O)", "TODO", …). The import flow tracks
verification in the data (coordinate precision, the stage-3 review), never
in the note text (2026-08-05: the first import wrote pending-markers into
8 notes and they rendered on the place pages).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools.archive import Archive
from tools.loft_paths import ARCHIVE_DIR
from tools.store import DiskStore

REPO = Path(__file__).resolve().parents[1]

# process jargon that must never reach a reader-facing description
JARGON = re.compile(
    r"pending|\(rule|verification|unverified|todo|tbd|needs review|review required",
    re.IGNORECASE,
)


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE_DIR / "people.json").exists(), reason="archive not bootstrapped yet")
def test_place_notes_never_carry_process_status() -> None:
    archive = Archive(DiskStore(ARCHIVE_DIR))
    table = archive.get_identity("places")
    if table is None:
        return  # a fresh archive predating the places seam has no notes to check
    offenders = []
    for place in table["places"]:
        note = str(place.get("note") or "")
        if JARGON.search(note):
            offenders.append((place["id"], note))
    assert not offenders, f"place notes carry process jargon: {offenders}"
