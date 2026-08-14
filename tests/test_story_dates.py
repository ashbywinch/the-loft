"""The story-date invariant — a story's date is the events' date, never the
day it was told (2026-08-05: the assessor fabricated telling-day dates and
four stories shipped with them; the moment card then served "0 years ago
this week"). The flow now asks for the events' date and refuses a fabricated
telling-day default. One legitimate exception: a diary-style story whose
narrator explicitly said the events happened that day — the guard requires
the transcript to show the narrator's words for it.

The check: a catalogued story whose date equals its recorded/created stamp
is a bug unless its own transcript carries an explicit date answer matching
the told day ("Today", the date itself) — the same discriminator the
assessor uses (a fabricated date has no such narrator words).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tools.archive import Archive
from tools.loft_paths import ARCHIVE_DIR
from tools.store import DiskStore

REPO = Path(__file__).resolve().parents[1]

TODAYISH = ("today", "tonight", "this morning", "this evening", "this week", "just now", "earlier today")


def _story_transcript(archive: Archive, item: dict[str, Any]) -> str:
    for asset in item.get("assets") or []:
        if asset.get("kind") == "story":
            raw = archive.read_file_bytes(item["id"], str(asset.get("file", "")))
            return (raw or b"").decode(errors="replace")
    return ""


def _narrator_stated_it(transcript: str, told_day: str) -> bool:
    if not transcript:
        return False
    lowered = transcript.lower()
    # an explicit date exchange: a question asking when, answered with the
    # told day or a today-ish phrase
    if "when did" not in lowered and "what date" not in lowered and "what year" not in lowered:
        return False
    return told_day in lowered or any(w in lowered for w in TODAYISH)


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE_DIR / "people.json").exists(), reason="archive not bootstrapped yet")
def test_no_catalogued_story_is_dated_by_its_told_day() -> None:
    archive = Archive(DiskStore(ARCHIVE_DIR))
    offenders = []
    for item_id in archive.item_ids():
        item = archive.get_item(item_id)
        if item is None or item.get("type") != "story" or item.get("status") != "catalogued":
            continue
        date = str(item.get("date", ""))
        told = str(item.get("recorded") or item.get("created") or "").strip()
        if item.get("reflection") or item.get("clarification"):
            continue  # a fragment's time IS the telling day — no events' date exists
        if not (told and told[:10] == date[:10]):
            continue
        if not _narrator_stated_it(_story_transcript(archive, item), told[:10]):
            offenders.append((item_id, date, told, item.get("title")))
    assert not offenders, f"stories dated by their told day without the narrator's words: {offenders}"
