"""The description eval — every catalogued letter/document must carry a
description specific enough to tell it apart from the rest of the same
correspondence, even when a suitcase of letters between the same two people
turns up (2026-08-05).

The checks:
1. A description exists and is not just the title.
2. It carries at least two *content signals*: numbers, quoted phrases, or
   capitalised words beyond the correspondents' names and common words — a
   purely generic "A letter from Owen to Nora" has none.
3. Within a correspondence (letters sharing the same people+org signature),
   every description has at least one signal no other letter in the group
   has — so two letters between the same people can be told apart at a
   glance.

The import flow writes descriptions; this eval is its drift guard.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tools.archive import Archive
from tools.store import DiskStore

REPO = Path(__file__).resolve().parents[1]

NUMBER = re.compile(r"\d+")
CAPITAL = re.compile(r"[A-Z][a-z]+")
QUOTE = re.compile(r"[\"“„][^”\"\n]{6,}[\"”]")

# sentence-initial articles/titles and the like — not content
COMMON = {"A", "An", "The", "Mr", "Mrs", "Ms", "Dr", "St", "No", "Dear", "Found", "This", "It", "I"}


def _names(item: dict[str, Any]) -> set[str]:
    """Every person/org ref in the item — the correspondents, not content."""
    out = set()
    for ref in item.get("people") or []:
        out.add(str(ref.get("id", "")))
    for ref in item.get("orgs") or []:
        out.add(str(ref.get("id", "")))
    return out


def signals(description: str, names: set[str]) -> set[str]:
    """The content signals of a description: numbers, quoted phrases, and
    capitalised words that are not the correspondents or common words."""
    found: set[str] = set()
    found.update(NUMBER.findall(description))
    found.update(QUOTE.findall(description))
    for word in CAPITAL.findall(description):
        if word in COMMON:
            continue
        if any(word in name or name in word for name in names):
            continue
        found.add(word)
    return found


def catalogued_letters(archive: Archive) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item_id in archive.item_ids():
        item = archive.get_item(item_id)
        if item is None or item.get("status") != "catalogued":
            continue
        if item.get("type") in ("letter", "document"):
            items.append(item)
    return items


@pytest.mark.skipif(not (REPO / "archive" / "people.json").exists(), reason="archive not bootstrapped yet")
def test_every_catalogued_letter_has_two_content_signals() -> None:
    archive = Archive(DiskStore(REPO / "archive"))
    for item in catalogued_letters(archive):
        description = (item.get("description") or "").strip()
        assert description, f"{item['id']} needs a description"
        assert description != item.get("title"), f"{item['id']} description is just the title"
        sigs = signals(description, _names(item))
        assert len(sigs) >= 2, f"{item['id']} description is not specific: {description!r} (signals: {sigs})"


@pytest.mark.skipif(not (REPO / "archive" / "people.json").exists(), reason="archive not bootstrapped yet")
def test_letters_within_a_correspondence_are_distinguishable() -> None:
    archive = Archive(DiskStore(REPO / "archive"))
    groups: dict[frozenset[str], list[dict[str, Any]]] = {}
    for item in catalogued_letters(archive):
        key = frozenset(_names(item))
        groups.setdefault(key, []).append(item)
    for key, items in groups.items():
        if len(items) < 2:
            continue
        sig_sets = {item["id"]: signals((item.get("description") or ""), set(key)) for item in items}
        for item in items:
            mine = sig_sets[item["id"]]
            others = [s for other, s in sig_sets.items() if other != item["id"]]
            shared = set().union(*others) if others else set()
            unique = mine - shared
            assert unique, (
                f"{item['id']} is indistinguishable from its correspondence: "
                f"{item.get('description')!r} shares every signal ({mine})"
            )
