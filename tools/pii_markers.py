"""The family's identifying markers, loaded from the gitignored dataset at
runtime — names, aliases, emails and place names from the archive's identity
tables. Test files must never contain these markers; this module never writes
them (2026-08-08, user: the no-PII-in-the-repo guard and the demo-fictionality
guard both load from here, so the markers live in the dataset, not in code).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# aliases that are generic kin terms or initials, not identifiers — "Mum" in
# a fixture is not family PII; "Nora Voss" is
_GENERIC_ALIASES = {
    "mum",
    "mummy",
    "mom",
    "dad",
    "daddy",
    "auntie",
    "aunty",
    "uncle",
    "granny",
    "gran",
    "nana",
    "grandad",
    "grandma",
    "poppa",
    "bf",
    "pg",
    "p.g.",
}

# common English words that ride along in place names ("The Lark Inn",
# "68 Goldcrest Close") — not identifying on their own
_COMMON_WORDS = {
    "the",
    "and",
    "of",
    "for",
    "in",
    "on",
    "at",
    "a",
    "an",
    "to",
    "with",
    "mrs",
    "mr",
    "ms",
    "close",
    "court",
    "grand",
    "primary",
    "school",
    "inn",
    "wharf",
    "iron",
    "union",
    "isle",
    "old",
    "bridge",
    "house",
    "street",
    "road",
    "lane",
    "avenue",
    "drive",
    "park",
    "view",
    "hill",
    "green",
    "farm",
    "hall",
    "mill",
    "church",
    "station",
    "town",
    "city",
}


def _latest(paths: list[Path]) -> Path:
    best: tuple[int, Path] | None = None
    for p in paths:
        m = re.search(r"(\d+)\.json$", p.name)
        version = int(m.group(1)) if m else 1
        if best is None or version > best[0]:
            best = (version, p)
    assert best is not None
    return best[1]


def _table_tokens(table: list[dict[str, Any]]) -> set[str]:
    """Names and name-tokens from one identity table's records."""
    markers: set[str] = set()
    for record in table:
        record_id = str(record.get("id", "")).strip()
        if record_id:
            markers.add(record_id)
        name = str(record.get("name", "")).strip()
        if name:
            markers.add(name)
            markers.update(
                t for t in re.findall(r"[A-Z][A-Za-z]+", name) if len(t) > 2 and t.lower() not in _COMMON_WORDS
            )
        for alias in record.get("aliases", []):
            a = str(alias).strip()
            if a and a.lower() not in _GENERIC_ALIASES and len(a) > 2:
                markers.add(a)
        email = str(record.get("email", "")).strip().lower()
        if email:
            markers.add(email)
    return {m for m in markers if m}


def _date_markers(record: dict[str, Any]) -> set[str]:
    """A person's attested birth/death dates — exact dates are identifying.
    Bare years are story years, not identifiers, and are left out."""
    markers: set[str] = set()
    for field in ("dob", "dod"):
        value = record.get(field)
        if isinstance(value, dict) and value.get("date"):
            markers.add(str(value["date"]))
        elif isinstance(value, str):
            markers.add(value)
    return {m for m in markers if len(m) > 6}


def _geo_markers(record: dict[str, Any]) -> set[str]:
    """A place's coordinates — street-precision lat/lng are identifying.
    Coarse 1-2 decimal values are not (they collide with versions and CSS)."""
    markers: set[str] = set()
    for field in ("lat", "lng"):
        value = record.get(field)
        if isinstance(value, (int, float)):
            text = str(value)
            if "." in text and len(text) - text.index(".") - 1 >= 4:
                markers.add(text)
    return markers


def family_markers(repo: Path) -> set[str]:
    """Every identifying name, alias, email, place, id, date and coordinate
    from the live dataset."""
    markers: set[str] = set()
    people_paths = sorted((repo / "archive").glob("people*.json"))
    places_paths = sorted((repo / "archive").glob("places*.json"))
    if people_paths:
        people = json.loads(_latest(people_paths).read_text(encoding="utf-8"))
        for record in people.get("people", []):
            markers |= _table_tokens([record]) | _date_markers(record)
    if places_paths:
        places = json.loads(_latest(places_paths).read_text(encoding="utf-8"))
        for record in places.get("places", []):
            markers |= _table_tokens([record]) | _geo_markers(record)
    return markers
