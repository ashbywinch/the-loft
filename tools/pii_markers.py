"""The family's identifying markers, loaded from the gitignored dataset at
runtime — names, aliases, emails and place names from the archive's identity
tables. Test files must never contain these markers; this module never writes
them (user: the no-PII-in-the-repo guard and the demo-fictionality
guard both load from here, so the markers live in the dataset, not in code).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from tools.loft_paths import LoftPaths
from tools.records import Person, Place


# aliases that are generic kin terms or initials, not identifiers — "Mum" in
# a fixture is not family PII; "Nora Voss" is
class PiiMarkers:
    """The PII marker vocabulary: the generic aliases, the common words, and
    the two precision measures the name and place markers read."""

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

    # Date markers are identifying only as full dates — bare years ("2026") are
    # story years and are left out; the shortest kept form is YYYY-MM (7 chars).
    _DATE_MARKER_MIN_LEN = 6
    # 4+ decimal places in a coordinate is street precision — identifying;
    # coarse 1-2 decimals collide with versions and CSS and are not.
    _STREET_PRECISION_DECIMALS = 4


def _latest(paths: list[Path]) -> Path:
    best: tuple[int, Path] | None = None
    for p in paths:
        m = re.search(r"(\d+)\.json$", p.name)
        version = int(m.group(1)) if m else 1
        if best is None or version > best[0]:
            best = (version, p)
    assert best is not None
    return best[1]


def _name_tokens(record_id: str, name: str, aliases: tuple[str, ...]) -> set[str]:
    """A record's identifying names: its id, its name and the name's own
    tokens, and its aliases — generic kin terms and initials are not
    identifiers."""
    markers: set[str] = set()
    if record_id:
        markers.add(record_id)
    if name:
        markers.add(name)
        markers.update(
            t for t in re.findall(r"[A-Z][A-Za-z]+", name) if len(t) > 2 and t.lower() not in PiiMarkers._COMMON_WORDS
        )
    for alias in aliases:
        a = alias.strip()
        if a and a.lower() not in PiiMarkers._GENERIC_ALIASES and len(a) > 2:
            markers.add(a)
    return {m for m in markers if m}


def _person_markers(person: Person) -> set[str]:
    """A person's identifying markers: their names and aliases, their email,
    and the attested birth/death dates. Exact dates are identifying; bare
    years are story years and are left out."""
    markers = _name_tokens(person.id, person.name, person.aliases)
    if person.email:
        markers.add(person.email)
    dates = {fact.date for fact in (person.dob, person.dod) if fact is not None}
    return markers | {d for d in dates if len(d) > PiiMarkers._DATE_MARKER_MIN_LEN}


def _place_markers(place: Place) -> set[str]:
    """A place's identifying markers: its names and aliases, and its
    street-precision coordinates. Coarse 1-2 decimal values are not
    identifying (they collide with versions and CSS)."""
    markers = _name_tokens(place.id, place.name, place.aliases)
    for value in (place.lat, place.lng):
        if not isinstance(value, (int, float)):
            continue
        text = str(value)
        if "." in text and len(text) - text.index(".") - 1 >= PiiMarkers._STREET_PRECISION_DECIMALS:
            markers.add(text)
    return markers


def _table_markers(paths: list[Path], key: str, parse: Callable[[dict[str, Any]], Person | Place]) -> set[str]:
    """One identity table's markers: every record parsed into its own class
    and asked for its identifying markers (names and aliases, plus the
    record's own extras — dates for people, coordinates for places)."""
    if not paths:
        return set()
    table = json.loads(_latest(paths).read_text(encoding="utf-8"))
    markers: set[str] = set()
    for raw in table.get(key, []):
        record = parse(raw)
        markers |= _person_markers(record) if isinstance(record, Person) else _place_markers(record)
    return markers


def _configured_markers() -> set[str] | None:
    """The markers the environment supplies — the CI secret, so the guard can
    run where the archive cannot (a JSON array or one marker per line)."""
    configured = os.environ.get("PII_MARKERS", "").strip()
    if not configured:
        return None
    # a JSON array (the recommended secret form) or one marker per line; a
    # malformed JSON secret must fail loudly, not silently fall back to lines
    parsed = json.loads(configured) if configured.startswith("[") else configured.splitlines()
    markers = {str(marker).strip() for marker in parsed if str(marker).strip()}
    return markers or None


def family_markers() -> set[str]:
    """Every identifying name, alias, email, place, id, date and coordinate
    from the live dataset — or from `PII_MARKERS` where the archive is
    absent (the CI secret)."""
    configured = _configured_markers()
    if configured is not None:
        return configured
    people = _table_markers(sorted(LoftPaths.ARCHIVE_DIR.glob("people*.json")), "people", Person.from_dict)
    places = _table_markers(sorted(LoftPaths.ARCHIVE_DIR.glob("places*.json")), "places", Place.from_dict)
    return people | places


class NonFamily:
    """Markers that are NOT the family, with the file that legitimately
    carries them: the GEDCOM 7 standard sample's names and the GEDCOM
    library's copyright holder. The guard stays strict everywhere else — a
    new entry here is a review finding, not a convenience."""

    ALLOWED: ClassVar[dict[str, frozenset[str]]] = {
        "docs/object-model.md": frozenset({"David"}),  # © David Straub, python-gedcom7
        "tests/fixtures/maximal70.ged": frozenset({"David", "John"}),  # the GEDCOM 7 maximal sample
        "tests/test_gedcom_document.py": frozenset({"Edward", "John"}),  # the sample and a synthetic name
    }


def file_offenders(text: str, markers: set[str], path: str | None = None) -> list[str]:
    """The markers present in *text* — the identity data that must not ship.

    One shared matcher (the guard and its fast path must agree).
    Emails compare case-insensitively against the lowercased text; names and
    places match at word boundaries in the original case. `path` names the
    file for the documented non-family collisions only.
    """
    allowed = NonFamily.ALLOWED.get(path or "", frozenset())
    lowered = text.lower()
    found: list[str] = []
    for marker in markers:
        if marker in allowed:
            continue
        if "@" in marker:
            if marker.lower() in lowered:
                found.append(marker)
        elif re.search(r"\b" + re.escape(marker) + r"\b", text):
            found.append(marker)
    return found
