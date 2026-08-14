"""The archive's user-facing text stays in family language — never the
import/elicitation process's shorthand. The import session leaked "(open
pile)", "Interview 1 · Q3", and "verbatim from the session transcript"
into relation/note/description/source fields (2026-08-06, user sign-off:
superseded the instances and fixed the generator). This test is the guard
that keeps the recurrence out — scanned at the live-archive level, so a
future import that re-introduces process jargon fails the build."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tools.loft_paths import ARCHIVE_DIR

REPO = Path(__file__).resolve().parent.parent

# The process vocabulary that must never reach a visitor. Deliberately
# tight: "attested" and "provenance" are the archive's evidence language
# (PRD §10), not session shorthand.
PROCESS_JARGON = (
    "open pile",
    "session transcript",
    "interview 1",
    "verbatim",
    "seeded —",
)

USER_FACING_FIELDS = ("title", "subtitle", "relation", "note", "bio", "description", "source")

FILES = [
    *sorted((ARCHIVE_DIR).glob("people*.json")),
    *sorted((ARCHIVE_DIR).glob("places*.json")),
    *sorted((ARCHIVE_DIR).glob("themes*.json")),
    *sorted((ARCHIVE_DIR / "assets").glob("*/item*.json")),
]


def _latest(paths: list[Path]) -> Path:
    """The highest-version file — item.json is version 1, item-2.json version
    2, … (mirrors tools/archive.py's resolution)."""
    best: tuple[int, Path] | None = None
    for p in paths:
        m = re.search(r"(\d+)\.json$", p.name)
        version = int(m.group(1)) if m else 1
        if best is None or version > best[0]:
            best = (version, p)
    assert best is not None
    return best[1]


def _live_tables() -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for name in ("people", "places", "themes"):
        paths = sorted((ARCHIVE_DIR).glob(f"{name}*.json"))
        if paths:
            tables.append(json.loads(_latest(paths).read_text(encoding="utf-8")))
    return tables


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE_DIR / "people.json").exists(), reason="archive not bootstrapped yet")
def test_no_process_jargon_in_user_facing_archive_text() -> None:
    offenders: list[str] = []
    for table in _live_tables():
        rows = table.get("people") or table.get("places") or table.get("themes") or []
        for row in rows:
            text = " ".join(str(row.get(k, "")) for k in USER_FACING_FIELDS).lower()
            for token in PROCESS_JARGON:
                if token in text:
                    offenders.append(f"{table.get('_name', row.get('id'))}: {token}")
    # item sidecars (assets/*/item*.json) — scan only the latest per item
    for folder in sorted((ARCHIVE_DIR / "assets").iterdir()):
        paths = sorted(folder.glob("item*.json"))
        if not paths:
            continue
        item = json.loads(_latest(paths).read_text(encoding="utf-8"))
        text = " ".join(str(item.get(k, "")) for k in USER_FACING_FIELDS).lower()
        for token in PROCESS_JARGON:
            if token in text:
                offenders.append(f"{item.get('id')}: {token}")
    assert not offenders, f"process jargon reached user-facing text: {offenders}"
