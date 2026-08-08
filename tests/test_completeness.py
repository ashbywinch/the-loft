"""The completeness eval — everything in the archive is visible somewhere on
the site (2026-08-06). The deterministic proxies for visibility:

1. Every catalogued item that renders on the timeline (published: not a
   clarification or reflection) must have a parseable date — the timeline
   skips malformed dates silently, which would make the item invisible.
2. Every clarification fragment must name a target that exists — it renders
   only on the page of what it attests.
3. Every reflection must name who or where it is about — it renders only on
   the pages it mentions.

Drafts are visible to their owner on the drafts surface; tombstoned items are
gone by design. The drift guard (test_publish) ensures the projection matches
the archive, so these archive-side checks are what the site actually shows.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tools.archive import Archive
from tools.store import DiskStore

REPO = Path(__file__).resolve().parents[1]

DATE_START = re.compile(r"^\d{4}")


def _refs(item: dict[str, Any], key: str) -> list[str]:
    return [str(r.get("id", "")) for r in item.get(key) or []]


def _visible_via(archive: Archive) -> tuple[set[str], set[str], set[str]]:
    """The ids a catalogued item can reference and still be reachable:
    people, places, and other catalogued items."""
    people: set[str] = set()
    places: set[str] = set()
    items: set[str] = set()
    table = archive.get_identity("people")
    if table is not None:
        people = {p["id"] for p in table["people"]}
    places_table = archive.get_identity("places")
    if places_table is not None:
        places = {p["id"] for p in places_table["places"]}
    for item_id in archive.item_ids():
        item = archive.get_item(item_id)
        if item is not None and item.get("status") != "deleted":
            items.add(item_id)
    return people, places, items


@pytest.mark.skipif(not (REPO / "archive" / "people.json").exists(), reason="archive not bootstrapped yet")
def test_every_timeline_item_has_a_parseable_date() -> None:
    archive = Archive(DiskStore(REPO / "archive"))
    broken = []
    for item_id in archive.item_ids():
        item = archive.get_item(item_id)
        if item is None or item.get("status") != "catalogued":
            continue
        if item.get("clarification") or item.get("reflection") or item.get("evidence"):
            continue  # fragments and evidence render on their pages, never on the timeline
        if not DATE_START.match(str(item.get("date", ""))):
            broken.append((item_id, item.get("date")))
    assert not broken, f"timeline items with unparseable dates are invisible: {broken}"


@pytest.mark.skipif(not (REPO / "archive" / "people.json").exists(), reason="archive not bootstrapped yet")
def test_every_object_and_photo_is_attested() -> None:
    # An object or photo is a specific physical thing — its existence must
    # be attested by an artifact that names it (a letter, a story), or (for
    # a photo) by its own real scan. A generated placeholder SVG is not an
    # artifact: the giraffes, the Greenhaven house, the shared flat, the
    # beach and "you on Sunlight" photos were all invented with placeholder
    # images and removed — the attic's real photos arrive as their own
    # scanned items (2026-08-06).
    archive = Archive(DiskStore(REPO / "archive"))
    refs: dict[str, list[str]] = {}
    for item_id in archive.item_ids():
        item = archive.get_item(item_id)
        if item is None or item.get("status") != "catalogued":
            continue
        for r in item.get("items") or []:
            refs.setdefault(str(r.get("id", "")), []).append(item_id)
    unattested = []
    for item_id in archive.item_ids():
        item = archive.get_item(item_id)
        if item is None or item.get("type") not in ("object", "photo") or item.get("status") != "catalogued":
            continue
        if item_id in refs:
            continue  # an artifact names it
        if item.get("type") == "photo" and any(
            not str(a.get("file", "")).endswith(".svg") for a in item.get("assets") or []
        ):
            continue  # a real scan is the artifact itself
        unattested.append((item_id, item.get("title")))
    assert not unattested, f"objects/photos no artifact attests: {unattested}"


@pytest.mark.skipif(not (REPO / "archive" / "people.json").exists(), reason="archive not bootstrapped yet")
def test_every_items_link_is_bidirectional() -> None:
    # All links are bidirectional (2026-08-06): the back link ("Referenced
    # by") is derived from the forward items refs at render, so a one-way
    # link is structurally unrepresentable — the only way to break it is a
    # forward ref that cannot resolve (a missing or draft target, so no back
    # link can render). The publish's dangling check enforces this; this
    # eval states the contract over the committed archive.
    archive = Archive(DiskStore(REPO / "archive"))
    catalogued_ids = set()
    for item_id in archive.item_ids():
        item = archive.get_item(item_id)
        if item is not None and item.get("status") == "catalogued":
            catalogued_ids.add(item_id)
    dangling = []
    for item_id in archive.item_ids():
        item = archive.get_item(item_id)
        if item is None or item.get("status") != "catalogued":
            continue
        for r in item.get("items") or []:
            target = str(r.get("id", ""))
            if target not in catalogued_ids:
                dangling.append((item_id, target))
    assert not dangling, f"items refs whose back link cannot render: {dangling}"


@pytest.mark.skipif(not (REPO / "archive" / "people.json").exists(), reason="archive not bootstrapped yet")
def test_every_fragment_names_a_target_that_exists() -> None:
    archive = Archive(DiskStore(REPO / "archive"))
    people, places, items = _visible_via(archive)
    dangling = []
    for item_id in archive.item_ids():
        item = archive.get_item(item_id)
        if item is None or item.get("status") != "catalogued":
            continue
        if item.get("clarification"):
            targets = _refs(item, "people") + _refs(item, "items")
            missing = [t for t in targets if t not in people and t not in items]
            if missing:
                dangling.append((item_id, missing))
        if item.get("reflection"):
            targets = _refs(item, "people") + _refs(item, "places")
            missing = [t for t in targets if t not in people and t not in places]
            if missing:
                dangling.append((item_id, missing))
        if item.get("evidence"):
            targets = _refs(item, "people") + _refs(item, "places") + _refs(item, "items")
            missing = [t for t in targets if t not in people and t not in places and t not in items]
            if missing:
                dangling.append((item_id, missing))
    assert not dangling, f"fragments whose target does not exist render nowhere: {dangling}"
