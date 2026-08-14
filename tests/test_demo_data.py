"""Tests for the demo-content generator: fictional content (the real family's
data is never involved), schema shape, and determinism."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tools import demo_data
from tools.loft_paths import ARCHIVE_DIR
from tools.pii_markers import family_markers

ARCHIVE = ARCHIVE_DIR / "people.json"


def _all_items() -> list[dict[str, Any]]:
    return list(demo_data.ALL_ITEMS)


def _all_text() -> str:
    chunks: list[str] = []
    for person in demo_data.PEOPLE:
        chunks += [person["name"], person.get("bio", "")]
        chunks += person.get("aliases", [])
    for place in demo_data.PLACES:
        chunks += [place["name"], place.get("note", "")]
    for theme in demo_data.THEMES:
        chunks += [theme["title"], theme.get("subtitle", "")]
    for item in _all_items():
        chunks += [item["title"], item.get("story", ""), item.get("description", "")]
        chunks += [item.get("transcription", "")]
    for rel in demo_data.RELATIONSHIPS:
        chunks += [rel["label_a"], rel["label_b"]]
    return " ".join(chunks)


@pytest.mark.archive
@pytest.mark.skipif(not ARCHIVE.exists(), reason="archive not bootstrapped yet")
def test_demo_content_is_fictional() -> None:
    """The demo never contains the real family's names, places or artifacts —
    a demo instance must never leak anyone's data (user, 2026-08-04)."""
    text = _all_text().lower()
    for marker in family_markers():
        assert not re.search(r"\b" + re.escape(marker) + r"\b", text, re.IGNORECASE), (
            f"real content leaked into the demo: {marker}"
        )


def test_generated_demo_assets_are_fictional(tmp_path: Path) -> None:
    """The guard scans what the demo actually ships — including the generated
    asset SVGs, where a placeholder could leak a real place name (the yard
    svg once hardcoded "Iron Wharf", 2026-08-04 review)."""
    from tools.archive import Archive
    from tools.store import DiskStore

    archive = Archive(DiskStore(tmp_path / "archive"))
    archive.create_demo()
    archive.publish(tmp_path / "data")  # the demo's own projection — the surface is Archive, not a shim
    haystack: list[str] = []
    for path in tmp_path.rglob("*"):
        if path.is_file():
            haystack.append(path.read_text(encoding="utf-8", errors="ignore"))
    joined = " ".join(haystack).lower()
    for marker in family_markers():
        assert not re.search(r"\b" + re.escape(marker) + r"\b", joined, re.IGNORECASE), (
            f"real content leaked into the demo output: {marker}"
        )


def test_item_schema_minimum() -> None:
    for item in _all_items():
        assert item["id"] and item["type"] and item["title"]
        assert item["date"] and item["date_precision"] in {"exact", "month", "year", "approx"}
        assert item["status"] == "catalogued"
        # stories and documents (described, not scanned) have no scans
        assert item["assets"] or item["type"] in ("story", "document"), "every item needs at least one asset"


def test_theme_references_resolve() -> None:
    item_ids = {it["id"] for it in _all_items()}
    for theme in demo_data.THEMES:
        assert theme["items"], f"{theme['id']} has no items"
        for entry in theme["items"]:
            assert entry["id"] in item_ids, f"{theme['id']} references unknown {entry['id']}"


def test_places_have_valid_coordinates() -> None:
    for place in demo_data.PLACES:
        assert -90 <= place["lat"] <= 90, f"{place['id']} lat out of range"
        assert -180 <= place["lng"] <= 180, f"{place['id']} lng out of range"
        assert 0 <= place["x"] <= 100 and 0 <= place["y"] <= 100, f"{place['id']} dot position off-canvas"


def test_people_have_canonical_names_and_aliases() -> None:
    for person in demo_data.PEOPLE:
        assert person["id"].startswith("p-")
        assert person["name"]
        assert isinstance(person.get("aliases", []), list)
        if "pronouns" in person:
            assert person["pronouns"].strip()  # never blank


def test_item_links_resolve() -> None:
    """Everything-to-everything integrity: every link points at a real entity."""
    people_ids = {p["id"] for p in demo_data.PEOPLE}
    place_ids = {p["id"] for p in demo_data.PLACES}
    theme_ids = {t["id"] for t in demo_data.THEMES}
    for item in _all_items():
        for link in item.get("people", []):
            assert link["id"] in people_ids
            assert link["status"] in {"confirmed", "proposed"}
        for link in item.get("places", []):
            assert link["id"] in place_ids
        for link in item.get("themes", []):
            assert link["id"] in theme_ids


def test_relationships_reference_known_people() -> None:
    people_ids = {p["id"] for p in demo_data.PEOPLE}
    kinds = {"spouse", "parent", "sibling", "inlaw", "teacher"}
    for rel in demo_data.RELATIONSHIPS:
        assert rel["a"] in people_ids and rel["b"] in people_ids, f"{rel} references unknown person"
        assert rel["kind"] in kinds, f"{rel} has unknown kind"
        assert rel["label_a"] and rel["label_b"], f"{rel} missing a direction label"


def test_stories_are_attributed() -> None:
    """Every story-type item carries told_by and source — dated, attributed,
    verbatim (the capture model, applied to the demo)."""
    for item in demo_data.STORIES:
        assert item["type"] == "story"
        assert item["told_by"], f"{item['id']} missing told_by"
        assert item["source"], f"{item['id']} missing source"
        assert item["date"], f"{item['id']} missing date"


def test_generated_copy_has_no_single_curator_voice() -> None:
    """Generated copy never speaks as one curator — the app arranges
    evidence, it never editorialises (PRD §10)."""
    joined = _all_text().lower()
    assert "the curator" not in joined and "curator:" not in joined


def test_create_demo_seeds_a_demo_archive(tmp_path: Path) -> None:
    """`Archive.create_demo()` seeds the archive it is given — the
    object-model surface, never a projection shim; the real archive and
    app/data are untouched by construction (2026-08-06)."""
    from tools.archive import Archive
    from tools.store import DiskStore

    archive = Archive(DiskStore(tmp_path))
    archive.create_demo()
    people = archive.get_identity("people")
    assert people is not None and people["people"]
    assert archive.get_identity("places") is not None
    assert archive.get_identity("themes") is not None
    assert archive.item_ids(), "demo items landed in the archive"
    # the demo never writes the real projection — create_demo is seeding only
    assert not (Path(__file__).resolve().parent.parent / "demo" / "data").exists()


def test_create_demo_publishes_to_its_own_data_dir(tmp_path: Path) -> None:
    """The demo's projection lands where the caller says — the CLI's
    create-demo seeds then publishes to its own --data, never app/data
    (2026-08-06; replaces the old projection-writer shim)."""
    from tools.archive import Archive
    from tools.store import DiskStore

    archive = Archive(DiskStore(tmp_path / "archive"))
    archive.create_demo()
    data = tmp_path / "data"
    archive.publish(data)
    index = json.loads((data / "index.json").read_text(encoding="utf-8"))
    assert len(index["items"]) == len(demo_data.ALL_ITEMS)
    people = json.loads((data / "people.json").read_text(encoding="utf-8"))
    assert len(people["people"]) == len(demo_data.PEOPLE)
    assert (data / "themes.json").exists()
    # placeholder assets + avatars exist (publish generates them)
    assert (data / "assets" / "object-the-dinghy" / "dinghy.svg").exists()
    assert (data / "assets" / "avatar-p-aria.svg").exists()
