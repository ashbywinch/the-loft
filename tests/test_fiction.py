"""The house fiction: the Barlow cast's integrity, and its fictionality.

`tools/fiction.py` is the one set of fictional names for fixtures, prompts,
eval inputs, docs and fake instances. Two things must hold: the cast is
internally coherent (ids, relationships, places), and no real family marker
appears anywhere in the module.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.fiction import HouseFiction
from tools.loft_paths import LoftPaths
from tools.pii_markers import family_markers, file_offenders
from tools.records import RELATIONSHIP_KINDS, is_valid_record_id

ROOT = Path(__file__).resolve().parent.parent


def _marker_source() -> bool:
    return bool(os.environ.get("PII_MARKERS", "").strip()) or (LoftPaths.ARCHIVE_DIR / "people.json").exists()


@pytest.mark.archive
@pytest.mark.skipif(not _marker_source(), reason="no marker source: neither the archive nor PII_MARKERS is present")
def test_the_house_fiction_contains_no_family_markers() -> None:
    source = Path(HouseFiction.__module__.replace(".", "/") + ".py").read_text(encoding="utf-8")
    assert file_offenders(source, family_markers()) == []


def test_the_cast_is_coherent() -> None:
    ids = [person["id"] for person in HouseFiction.PEOPLE]
    assert len(ids) == len(set(ids))
    for person in HouseFiction.PEOPLE:
        assert is_valid_record_id(person["id"])
        assert person["name"].strip()
        assert isinstance(person.get("aliases", []), list)
        if "pronouns" in person:
            assert person["pronouns"].strip()
    known = set(ids)
    for edge in HouseFiction.RELATIONSHIPS:
        assert edge["a"] in known and edge["b"] in known, f"{edge} references an unknown person"
        assert edge["kind"] in RELATIONSHIP_KINDS
        assert edge["label_a"] and edge["label_b"]
    place_ids = [place["id"] for place in HouseFiction.PLACES]
    assert len(place_ids) == len(set(place_ids))
    for place in HouseFiction.PLACES:
        assert is_valid_record_id(place["id"])
        assert -90 <= place["lat"] <= 90 and -180 <= place["lng"] <= 180
        assert 0 <= place["x"] <= 100 and 0 <= place["y"] <= 100


def test_the_standards_name_the_fiction_source() -> None:
    standards = (ROOT / "docs/coding-standards.md").read_text(encoding="utf-8")
    writing = (ROOT / "docs/writing-documentation.md").read_text(encoding="utf-8")
    assert "tools/fiction.py" in standards
    assert "tools/fiction.py" in writing
