"""Tests for the publish pipeline: archive -> projection.

The projection is derived — these tests pin that the derivation is faithful
(content embedded from files, tombstones gone, versions resolved, drafts
kept, relationships flowing through the identity tables) and deterministic.
The last test is the drift guard: the committed projection must equal what
publish produces from the committed archive, so a hand-edit of app/data (or
a lost identity table) fails CI instead of silently diverging.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools.archive import Archive
from tools.loft_paths import ARCHIVE_DIR
from tools.projection import DeriveError, Projection, projection_json, resolved_items
from tools.store import DiskStore


def make_archive(root: Path) -> Archive:
    return Archive(DiskStore(root / "archive"))


def sample_identity(root: Path) -> Archive:
    archive = make_archive(root)
    archive.save_identity("people", {"people": [{"id": "p-mum", "name": "Mum", "hue": "amber"}], "relationships": []})
    archive.save_identity("places", {"places": [{"id": "pl-town", "name": "Town"}]})
    archive.save_identity("themes", {"themes": [{"id": "t-boat", "title": "The boats"}]})
    return archive


def test_publish_writes_every_derived_file(tmp_path: Path) -> None:
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "letter-a",
            "type": "letter",
            "title": "A",
            "date": "1962-01-01",
            "date_precision": "exact",
            "status": "catalogued",
            "assets": [],
        }
    )
    out = tmp_path / "out"
    Projection(archive, out).build()
    for name in ("index.json", "people.json", "places.json", "themes.json", "transcripts.json"):
        assert (out / name).exists(), name


def test_publish_embeds_story_from_content_file_and_strips_the_entry(tmp_path: Path) -> None:
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "story-x",
            "type": "story",
            "title": "X",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "catalogued",
            "assets": [],
        },
        content={"story": "We took the dinghy out."},
    )
    items = resolved_items(archive)
    assert items[0]["story"] == "We took the dinghy out."
    assert all(a.get("kind") != "story" for a in items[0]["assets"])  # never rendered as an image


def test_publish_embeds_transcription_and_builds_transcripts(tmp_path: Path) -> None:
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "letter-a",
            "type": "letter",
            "title": "A",
            "date": "1962-01-01",
            "date_precision": "exact",
            "status": "catalogued",
            "assets": [],
        },
        content={"transcription": "Dear Mum, …"},
    )
    items = resolved_items(archive)
    assert items[0]["transcription"] == "Dear Mum, …"
    assert json.loads(projection_json(archive)["transcripts.json"]) == {"letter-a": "Dear Mum, …"}


def test_publish_skips_tombstoned_and_resolves_versions(tmp_path: Path) -> None:
    archive = sample_identity(tmp_path)
    _ = archive.save_item(
        {
            "id": "story-x",
            "type": "story",
            "title": "One",
            "date": "2026-01-01",
            "date_precision": "exact",
            "status": "catalogued",
            "assets": [],
        }
    )
    archive.delete_item("story-x", "test")
    _ = archive.save_item(
        {
            "id": "story-y",
            "type": "story",
            "title": "First",
            "date": "2026-02-01",
            "date_precision": "exact",
            "status": "catalogued",
            "assets": [],
        }
    )
    _ = archive.save_item(
        {
            "id": "story-y",
            "type": "story",
            "title": "Second",
            "date": "2026-02-01",
            "date_precision": "exact",
            "status": "catalogued",
            "assets": [],
        },
        content={"story": "latest"},
    )
    items = {it["id"]: it for it in resolved_items(archive)}
    assert "story-x" not in items  # tombstoned — gone
    assert items["story-y"]["title"] == "Second"  # highest version wins
    assert items["story-y"]["story"] == "latest"


def test_publish_keeps_drafts_for_the_owner(tmp_path: Path) -> None:
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "story-d",
            "type": "story",
            "title": "Draft",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "draft",
            "assets": [],
        }
    )
    items = resolved_items(archive)
    assert items[0]["status"] == "draft"


def test_publish_carries_relationships_from_the_identity_table(tmp_path: Path) -> None:
    archive = make_archive(tmp_path)
    archive.save_identity(
        "people",
        {
            "people": [{"id": "p-a", "name": "A", "hue": "rose"}, {"id": "p-b", "name": "B", "hue": "sky"}],
            "relationships": [{"a": "p-a", "b": "p-b", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"}],
        },
    )
    archive.save_identity("places", {"places": []})
    archive.save_identity("themes", {"themes": []})
    people = json.loads(projection_json(archive)["people.json"])
    assert people["relationships"] == [
        {"a": "p-a", "b": "p-b", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"}
    ]


def test_publish_copies_real_assets_and_generates_placeholders(tmp_path: Path) -> None:
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "photo-x",
            "type": "photo",
            "title": "Beach",
            "date": "1975",
            "date_precision": "approx",
            "status": "catalogued",
            "assets": [{"kind": "photo", "file": "real.svg", "caption": "Real"}],
        },
    )
    archive.save_item(
        {
            "id": "letter-x",
            "type": "letter",
            "title": "L",
            "date": "1963-01-01",
            "date_precision": "exact",
            "status": "catalogued",
            "assets": [{"kind": "page", "file": "page-1.svg", "caption": "Page 1"}],
        },
    )
    # the photo's scan exists in the archive; the letter's page is missing
    archive.store.write_new("assets/photo-x/real.svg", "<svg>real scan</svg>")
    out = tmp_path / "out"
    Projection(archive, out).build()
    assert (out / "assets" / "photo-x" / "real.svg").read_text() == "<svg>real scan</svg>"
    placeholder = out / "assets" / "letter-x" / "page-1.svg"
    assert placeholder.exists() and "svg" in placeholder.read_text()


def test_publish_leaves_no_staging_residue(tmp_path: Path) -> None:
    """Publish stages the assets beside the projection and swaps — a failed
    or interrupted copy must never leave assets.tmp behind or a fresh index
    pointing at a deleted assets/ (2026-08-05 bot review)."""
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "object-x",
            "type": "object",
            "title": "X",
            "date": "1980",
            "date_precision": "year",
            "status": "catalogued",
            "assets": [{"kind": "photo", "file": "pic.jpg", "caption": "X"}],
        }
    )
    out = tmp_path / "out"
    Projection(archive, out).build()
    assert not (out / "assets.tmp").exists()
    assert (out / "assets" / "object-x" / "pic.jpg").exists()
    # re-publishing over an existing projection is equally clean
    Projection(archive, out).build()
    assert not (out / "assets.tmp").exists()
    assert (out / "assets" / "object-x" / "pic.jpg").exists()


def test_publish_copies_binary_scans_byte_identical(tmp_path: Path) -> None:
    """Real scans are binary — publish must copy them byte-for-byte, never
    decode them as text (2026-08-04 review finding)."""
    archive = sample_identity(tmp_path)
    blob = b"\xff\xd8\xff\xe0" + bytes(range(256))
    archive.save_item(
        {
            "id": "photo-b",
            "type": "photo",
            "title": "B",
            "date": "1975",
            "date_precision": "approx",
            "status": "catalogued",
            "assets": [{"kind": "photo", "file": "scan.jpg", "caption": "Scan"}],
        },
    )
    archive.save_file("photo-b", "scan.jpg", blob)
    out = tmp_path / "out"
    Projection(archive, out).build()
    assert (out / "assets" / "photo-b" / "scan.jpg").read_bytes() == blob


def test_publish_writes_avatars_from_people(tmp_path: Path) -> None:
    archive = sample_identity(tmp_path)
    out = tmp_path / "out"
    Projection(archive, out).build()
    assert (out / "assets" / "avatar-p-mum.svg").exists()


def test_publish_writes_an_avatar_for_every_person_even_without_a_hue(tmp_path: Path) -> None:
    # A person without a hue still needs an avatar — a missing file is a
    # broken image link on every card (cast/tree render the img
    # unconditionally). The hue defaults deterministically from the id:
    # same person, same colour, every publish (2026-08-05).
    archive = make_archive(tmp_path)
    archive.save_identity("places", {"places": [{"id": "pl-town", "name": "Town"}]})
    archive.save_identity("themes", {"themes": [{"id": "t-boat", "title": "The boats"}]})
    archive.save_identity(
        "people",
        {
            "people": [
                {"id": "p-mum", "name": "Mum", "hue": "amber"},
                {"id": "p-no-hue", "name": "No Hue"},
            ],
            "relationships": [],
        },
    )
    out = tmp_path / "out"
    Projection(archive, out).build()
    assert (out / "assets" / "avatar-p-no-hue.svg").exists()
    # the hand-picked hue is not clobbered by the default
    first = (out / "assets" / "avatar-p-no-hue.svg").read_text(encoding="utf-8")
    Projection(archive, out).build()
    second = (out / "assets" / "avatar-p-no-hue.svg").read_text(encoding="utf-8")
    assert first == second
    # the hand-picked hue's colour is in the file — the default never clobbers it
    assert "#e8c39a" in (out / "assets" / "avatar-p-mum.svg").read_text(encoding="utf-8")


def test_publish_is_deterministic(tmp_path: Path) -> None:
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "story-x",
            "type": "story",
            "title": "X",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "catalogued",
            "assets": [],
        },
        content={"story": "hi"},
    )
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    Projection(archive, out1).build()
    Projection(archive, out2).build()
    for name in ("index.json", "people.json", "places.json", "themes.json", "transcripts.json"):
        a = json.loads((out1 / name).read_text())
        b = json.loads((out2 / name).read_text())
        a.pop("generated", None)
        b.pop("generated", None)
        assert a == b, name


def test_archive_without_identity_table_fails_fast(tmp_path: Path) -> None:
    archive = make_archive(tmp_path)
    with pytest.raises(DeriveError):
        _ = projection_json(archive)


def _catalogued_story_linking(archive: Archive, target_id: str, target_status: str) -> None:
    archive.save_item(
        {
            "id": "story-a",
            "type": "story",
            "title": "A",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "catalogued",
            "items": [{"id": target_id, "status": "confirmed"}],
            "assets": [],
        }
    )
    archive.save_item(
        {
            "id": target_id,
            "type": "object",
            "title": "Target",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": target_status,
            "assets": [],
        }
    )


def test_publish_fails_on_missing_content_file(tmp_path: Path) -> None:
    """A sidecar referencing a content file the archive doesn't have is
    silent data loss — publish fails loudly instead of shipping a blank
    story/transcription (2026-08-04 review, raised 3x; partial Drive sync
    is the realistic trigger, PRD §7)."""
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "story-x",
            "type": "story",
            "title": "X",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "catalogued",
            "assets": [{"kind": "story", "file": "story.txt", "caption": "The story, verbatim"}],
        }
    )
    assert not (tmp_path / "archive" / "assets" / "story-x" / "story.txt").exists()
    with pytest.raises(DeriveError, match="story.txt"):
        _ = projection_json(archive)


def test_publish_fails_on_confirmed_link_to_draft_artifact(tmp_path: Path) -> None:
    """A catalogued item confirming a link to a draft artifact is dangling
    — publish fails loudly instead of shipping an invisible target
    (2026-08-05: story-2026-08-03-05 confirmed a draft object-sb-mirosa)."""
    archive = sample_identity(tmp_path)
    _catalogued_story_linking(archive, "object-x", "draft")
    with pytest.raises(DeriveError, match="object-x"):
        _ = projection_json(archive)


def test_publish_passes_when_confirmed_link_target_is_catalogued(tmp_path: Path) -> None:
    archive = sample_identity(tmp_path)
    _catalogued_story_linking(archive, "object-x", "catalogued")
    projection_json(archive)  # no raise


def test_publish_merges_proposed_records_with_status(tmp_path: Path) -> None:
    """Proposed people/places are part of the projection — the propose/confirm
    seam means a catalogued story's ref to a proposed record must resolve
    (2026-08-05: derive dropped proposed/ entirely, so a fresh publish would
    dangle those refs)."""
    archive = sample_identity(tmp_path)
    archive.propose_person({"id": "p-nova", "name": "Nova", "relation": "added from a story"})
    archive.propose_place({"id": "pl-new", "name": "New place", "note": "Added from a story."})
    out = projection_json(archive)
    people = json.loads(out["people.json"])["people"]
    assert any(p["id"] == "p-nova" and p.get("status") == "proposed" for p in people)
    places = json.loads(out["places.json"])["places"]
    assert any(pl["id"] == "pl-new" and pl.get("status") == "proposed" for pl in places)


def test_publish_dedupes_proposed_against_the_table(tmp_path: Path) -> None:
    """A proposed record whose id is already confirmed is a promoted one —
    the table wins, the stale proposed file is skipped."""
    archive = sample_identity(tmp_path)  # p-mum in the table
    archive.propose_person({"id": "p-mum", "name": "Mum", "hue": "amber"})
    people = json.loads(projection_json(archive)["people.json"])["people"]
    assert sum(1 for p in people if p["id"] == "p-mum") == 1
    assert people[0].get("status") is None  # the table copy stays confirmed


def test_publish_strips_supersedes_from_identity_tables(tmp_path: Path) -> None:
    """The supersession chain is archive-internal — never projection content
    (2026-08-04 review finding: people.json shipped 'supersedes')."""
    archive = sample_identity(tmp_path)
    archive.save_identity("people", {"people": [{"id": "p-mum", "name": "Mum", "hue": "amber"}], "relationships": []})
    people = json.loads(projection_json(archive)["people.json"])
    assert "supersedes" not in people


def test_publish_fails_on_theme_record_referencing_missing_item(tmp_path: Path) -> None:
    """A theme record's curated items list must resolve in the projection —
    a tombstoned or missing letter left in a theme is a dangling card
    (2026-08-05: the fake-letter tombstone batch cleaned 7 theme entries;
    this guard keeps it that way)."""
    archive = sample_identity(tmp_path)
    archive.save_identity(
        "themes",
        {"themes": [{"id": "t-x", "title": "X", "items": [{"id": "letter-ghost", "note": "gone"}]}]},
    )
    with pytest.raises(DeriveError, match="letter-ghost"):
        _ = projection_json(archive)


def test_publish_fails_on_theme_referencing_draft_item(tmp_path: Path) -> None:
    """A theme's curated card is public; a draft target is invisible to
    everyone but its owner — the same dangling-card class as confirmed item
    refs and comment_on (2026-08-05 review)."""
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "object-x",
            "type": "object",
            "title": "X",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "draft",
            "assets": [],
        }
    )
    archive.save_identity("themes", {"themes": [{"id": "t-full", "title": "Full", "items": [{"id": "object-x"}]}]})
    with pytest.raises(DeriveError, match="object-x"):
        _ = projection_json(archive)


def test_publish_accepts_empty_and_resolving_theme_items(tmp_path: Path) -> None:
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "object-ok",
            "type": "object",
            "title": "OK",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "catalogued",
            "assets": [],
        }
    )
    archive.save_identity(
        "themes",
        {
            "themes": [
                {"id": "t-full", "title": "Full", "items": [{"id": "object-ok", "note": "fine"}]},
                {"id": "t-empty", "title": "Empty", "items": []},
            ]
        },
    )
    projection_json(archive)  # no raise


def test_publish_dedupes_proposed_places_by_name(tmp_path: Path) -> None:
    """The propose/confirm seam never multiplies a place entity: a proposed
    record whose NAME already exists in the table (a story mention minted a
    fresh id) is skipped — the moored-barges ×3 came from exactly this
    (2026-08-05)."""
    archive = sample_identity(tmp_path)
    archive.save_identity("places", {"places": [{"id": "pl-x", "name": "The dock", "note": "curated"}]})
    archive.propose_place({"id": "pl-x-2", "name": "The dock", "note": "Added from a story."})
    places = json.loads(projection_json(archive)["places.json"])["places"]
    assert [p["id"] for p in places] == ["pl-x"]  # the proposed duplicate is not published


def test_publish_fails_on_catalogued_story_commenting_on_draft(tmp_path: Path) -> None:
    """comment_on is a link too: a catalogued story whose anchor item is a
    draft (or missing) ships with an invisible target (2026-08-05 bot
    review, importance 7)."""
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "object-x",
            "type": "object",
            "title": "X",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "draft",
            "assets": [],
        }
    )
    archive.save_item(
        {
            "id": "story-c",
            "type": "story",
            "title": "C",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "catalogued",
            "comment_on": "object-x",
            "assets": [],
        }
    )
    with pytest.raises(DeriveError, match="object-x"):
        _ = projection_json(archive)


def test_publish_fails_on_extraction_match_that_does_not_resolve(tmp_path: Path) -> None:
    """chat.extractions carry the same promise as the four link kinds: a
    catalogued story whose extraction match names an entity the projection
    cannot see is dangling — the p-dad/p-mum class (2026-08-05 bot review;
    the data was fixed, the class needs a guard)."""
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "story-x",
            "type": "story",
            "title": "X",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "catalogued",
            "chat": {"extractions": [{"kind": "person", "name": "Dad", "match": "p-dad"}]},
            "assets": [],
        }
    )
    with pytest.raises(DeriveError, match="p-dad"):
        _ = projection_json(archive)


def test_publish_fails_on_extraction_match_to_draft_item(tmp_path: Path) -> None:
    """An extraction match is a link too: a catalogued story matching a
    draft artifact publishes a pointer invisible to every reader but its
    owner (2026-08-05 review)."""
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "object-x",
            "type": "object",
            "title": "X",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "draft",
            "assets": [],
        }
    )
    archive.save_item(
        {
            "id": "story-x",
            "type": "story",
            "title": "X",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "catalogued",
            "chat": {"extractions": [{"kind": "item", "name": "X", "match": "object-x"}]},
            "assets": [],
        }
    )
    with pytest.raises(DeriveError, match="object-x"):
        _ = projection_json(archive)


def test_publish_ignores_excluded_extraction_matches(tmp_path: Path) -> None:
    """An extraction the reviewer unticked (on: false) is excluded content —
    its match is not a link the projection must carry, so a dangling match
    on it must not fail publish (2026-08-05 bot review)."""
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "story-x",
            "type": "story",
            "title": "X",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "catalogued",
            "chat": {
                "extractions": [
                    {"kind": "person", "name": "Dad", "match": "p-dad", "bucket": "proposed", "on": False},
                    {"kind": "person", "name": "Ghost", "match": "p-ghost", "bucket": "proposed", "on": True},
                ]
            },
            "assets": [],
        }
    )
    with pytest.raises(DeriveError, match="p-ghost"):  # the included one still resolves
        _ = projection_json(archive)


def test_publish_passes_when_extraction_matches_resolve_or_are_null(tmp_path: Path) -> None:
    """An unresolved extraction (match null) is the kinship filter's honest
    output — not an error. Only a non-null match that the projection cannot
    see is a dangling link."""
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "story-x",
            "type": "story",
            "title": "X",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "catalogued",
            "chat": {
                "extractions": [
                    {"kind": "person", "name": "Mum", "match": "p-mum"},
                    {"kind": "person", "name": "Grandma", "match": None},
                ]
            },
            "assets": [],
        }
    )
    projection_json(archive)  # no raise


def test_publish_passes_when_comment_on_target_is_catalogued(tmp_path: Path) -> None:
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "object-x",
            "type": "object",
            "title": "X",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "catalogued",
            "assets": [],
        }
    )
    archive.save_item(
        {
            "id": "story-c",
            "type": "story",
            "title": "C",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "catalogued",
            "comment_on": "object-x",
            "assets": [],
        }
    )
    projection_json(archive)  # no raise


def test_publish_dedupes_proposed_people_by_name(tmp_path: Path) -> None:
    """The cast never fragments: a proposed person whose NAME already exists
    in the table (or in another proposal) is skipped (2026-08-05 bot review —
    the person analog of the moored-barges place dedup)."""
    archive = sample_identity(tmp_path)
    archive.save_identity("people", {"people": [{"id": "p-mum", "name": "Mum", "hue": "amber"}], "relationships": []})
    archive.propose_person({"id": "p-nora", "name": "Nora Smith", "relation": "added from a story"})
    archive.propose_person({"id": "p-nora-2", "name": "Nora Smith", "relation": "added from a story"})
    archive.propose_person({"id": "p-mum-2", "name": "Mum", "relation": "added from a story"})
    people = json.loads(projection_json(archive)["people.json"])["people"]
    nora = [p for p in people if "Nora" in p["name"]]
    assert len(nora) == 1  # proposed-vs-proposed deduped
    assert sum(1 for p in people if p["name"] == "Mum") == 1  # proposed-vs-table deduped


def test_publish_keeps_same_named_people_with_distinct_dobs(tmp_path: Path) -> None:
    """The dedup is dob-aware: two proposed records with the same name but
    different birth dates are two people (the record book has three
    Walters, two Claras, two Theos) — never collapsed into one."""
    archive = sample_identity(tmp_path)
    archive.propose_person(
        {"id": "p-richard-sr", "name": "Walter Kendall", "dob": {"date": "1830-09-02", "precision": "exact"}}
    )
    archive.propose_person(
        {"id": "p-richard-jr", "name": "Walter Kendall", "dob": {"date": "1895-08-27", "precision": "exact"}}
    )
    people = json.loads(projection_json(archive)["people.json"])["people"]
    richards = [p for p in people if p["name"] == "Walter Kendall"]
    assert len(richards) == 2


def test_publish_table_resolves_relationships_regardless_of_status(tmp_path: Path) -> None:
    """The people table is fully resolvable irrespective of status: a
    proposed-status person in the table is a first-class relationship
    endpoint (2026-08-05 — the import flow's people enter the table with
    status proposed; the proposed/ queue is story staging, not their home)."""
    archive = sample_identity(tmp_path)
    archive.save_identity(
        "people",
        {
            "people": [
                {"id": "p-richard-sr", "name": "Walter Kendall", "status": "proposed"},
                {"id": "p-eleanor", "name": "Clara Kendall", "status": "proposed"},
            ],
            "relationships": [
                {"a": "p-richard-sr", "b": "p-eleanor", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"}
            ],
        },
    )
    people = json.loads(projection_json(archive)["people.json"])
    statuses = {p["id"]: p.get("status") for p in people["people"]}
    assert statuses == {"p-richard-sr": "proposed", "p-eleanor": "proposed"}
    assert people["relationships"] == [
        {"a": "p-richard-sr", "b": "p-eleanor", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"}
    ]


def test_publish_dedupes_proposed_places_against_each_other(tmp_path: Path) -> None:
    """Two story mentions minting two proposed records with the same name
    publish one — the moored-barges ×3 must never recur (2026-08-05 bot
    review)."""
    archive = sample_identity(tmp_path)
    archive.propose_place({"id": "pl-new-1", "name": "The dock", "note": "Added from a story."})
    archive.propose_place({"id": "pl-new-2", "name": "The dock", "note": "Added from a story."})
    places = json.loads(projection_json(archive)["places.json"])["places"]
    docks = [p for p in places if "dock" in p["name"].lower()]
    assert len(docks) == 1


def test_publish_fails_on_confirmed_ref_to_missing_person(tmp_path: Path) -> None:
    """The ref guard covers every link kind, not just items: a catalogued
    item confirming a person who is not in the published projection is
    dangling."""
    archive = sample_identity(tmp_path)
    archive.save_item(
        {
            "id": "story-b",
            "type": "story",
            "title": "B",
            "date": "2026-08-03",
            "date_precision": "exact",
            "status": "catalogued",
            "people": [{"id": "p-ghost", "status": "confirmed"}],
            "assets": [],
        }
    )
    with pytest.raises(DeriveError, match="p-ghost"):
        _ = projection_json(archive)


def test_publish_emits_orgs_and_validates_org_refs(tmp_path: Path) -> None:
    """The orgs identity table publishes; a catalogued item's org ref must
    resolve in the projection, and a dangling one fails loudly (2026-08-05
    import interview)."""
    archive = sample_identity(tmp_path)
    archive.save_identity(
        "orgs",
        {"orgs": [{"id": "org-ministry", "name": "Ministry of Supply", "address": "Ivybridge House, Adam Street"}]},
    )
    archive.save_item(
        {
            "id": "letter-x",
            "type": "letter",
            "title": "X",
            "date": "1949-02-04",
            "date_precision": "exact",
            "status": "catalogued",
            "people": [],
            "places": [],
            "themes": [],
            "orgs": [{"id": "org-ministry", "status": "confirmed"}],
            "assets": [],
        }
    )
    orgs = json.loads(projection_json(archive)["orgs.json"])["orgs"]
    assert [o["id"] for o in orgs] == ["org-ministry"]
    archive.save_item(
        {
            "id": "letter-y",
            "type": "letter",
            "title": "Y",
            "date": "1949-02-05",
            "date_precision": "exact",
            "status": "catalogued",
            "people": [],
            "places": [],
            "themes": [],
            "orgs": [{"id": "org-ghost", "status": "confirmed"}],
            "assets": [],
        }
    )
    with pytest.raises(DeriveError, match="org-ghost"):
        _ = projection_json(archive)


def test_publish_tolerates_archive_without_orgs_table(tmp_path: Path) -> None:
    """The orgs seam is additive — an archive that predates it publishes
    an empty orgs list, never a failure."""
    archive = sample_identity(tmp_path)
    orgs = json.loads(projection_json(archive)["orgs.json"])
    assert orgs == {"orgs": []}


# -- the drift guard: the committed projection must be publishable ---------

REPO = Path(__file__).resolve().parent.parent


def _latest_sidecar(folder: Path) -> Path | None:
    """The highest-version sidecar — item.json is version 1, item-2.json
    version 2, … (tools/archive.py's resolution). A lexical sort picks the
    wrong file once item-10.json exists — "item-10" < "item-2" < "item.json"
    (2026-08-06 review: the gate validated a stale sidecar)."""
    best: tuple[int, Path] | None = None
    for p in folder.glob("item*.json"):
        m = re.search(r"item(?:-(\d+))?\.json$", p.name)
        version = int(m.group(1)) if m and m.group(1) else 1
        if best is None or version > best[0]:
            best = (version, p)
    return best[1] if best else None


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE_DIR / "people.json").exists(), reason="archive not bootstrapped yet")
def test_committed_sidecars_all_validate() -> None:
    """Every committed sidecar satisfies the Item record — the write seam
    refuses anything that doesn't, so the archive and the model can never
    drift (2026-08-05)."""
    from tools.records import Item  # local import — records is not this module's subject

    scanned = 0
    for folder in sorted((ARCHIVE_DIR / "assets").iterdir()):
        item_path = _latest_sidecar(folder)
        if item_path is None:
            continue
        item = json.loads(item_path.read_text(encoding="utf-8"))
        Item.from_dict(item)
        scanned += 1
    assert scanned > 0


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE_DIR / "people.json").exists(), reason="archive not bootstrapped yet")
def test_committed_projection_equals_publish_of_committed_archive(tmp_path: Path) -> None:
    """The committed app/data must be exactly what publish produces from the
    committed archive (modulo the regeneration stamp) — a hand-edit of the
    projection, a formatting drift, or a lost identity table (the
    relationships bug) fails here. Compares the whole tree, including the
    derived assets (placeholder pages, avatars), which the five-JSON
    compare used to miss (2026-08-05 bot review). Edit the archive, then
    re-publish."""
    archive = Archive(DiskStore(ARCHIVE_DIR))
    out = REPO / "app" / "data"
    fresh = tmp_path / "fresh"
    Projection(archive, fresh).build()

    committed = {p.relative_to(out) for p in out.rglob("*") if p.is_file()}
    generated = {p.relative_to(fresh) for p in fresh.rglob("*") if p.is_file()}
    assert committed == generated, (
        f"file set drifted: only in app/data={sorted(committed - generated)}, "
        f"only in publish={sorted(generated - committed)}"
    )

    for rel in sorted(committed):
        expected = (out / rel).read_bytes()
        actual = (fresh / rel).read_bytes()
        if rel.as_posix() == "index.json":  # the regeneration stamp is not content
            expected = re.sub(rb'"generated": "[^"]+"', b'"generated": "X"', expected)
            actual = re.sub(rb'"generated": "[^"]+"', b'"generated": "X"', actual)
        assert actual == expected, f"{rel} drifted from publish — edit the archive, not the projection"


UNATTRIBUTED_COMMENTARY = (
    "being a bum",
    "such as it was",
    "baffled",
    "her voice",
    "without her",
    "seen with paul",
    "terrible",
    "unsuccessful",
    "the curator",
    "curator:",
)

_ATTRIBUTION = re.compile(r"^[A-Za-z][A-Za-z ]+:")


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE_DIR / "people.json").exists(), reason="archive not bootstrapped yet")
def test_projection_has_no_unattributed_commentary() -> None:
    """PRD §10 / docs/coding-standards.md: generated copy is factual — a
    personal observation is attributed testimony, never app prose. Story
    items are the narrator's own words (exempt); every other description,
    bio and note must carry no commentary phrase, or attribute it
    ("Alex: …"). Restored after the 2026-08-04 review flagged editorial
    phrases in object/photo descriptions."""
    index = json.loads((REPO / "app" / "data" / "index.json").read_text(encoding="utf-8"))
    people = json.loads((REPO / "app" / "data" / "people.json").read_text(encoding="utf-8"))
    places = json.loads((REPO / "app" / "data" / "places.json").read_text(encoding="utf-8"))
    themes = json.loads((REPO / "app" / "data" / "themes.json").read_text(encoding="utf-8"))

    for item in index["items"]:
        if item["type"] == "story":
            continue  # verbatim, attributed testimony — exempt
        for field in ("story", "description", "title"):
            text = item.get(field) or ""
            hits = [p for p in UNATTRIBUTED_COMMENTARY if p in text.lower()]
            assert not hits or _ATTRIBUTION.match(text), f"{item['id']}.{field} has commentary: {hits}"

    for person in people["people"]:
        for phrase in UNATTRIBUTED_COMMENTARY:
            assert phrase not in (person.get("bio") or "").lower(), f"{person['id']} bio has commentary: {phrase}"
    for place in places["places"]:
        for phrase in UNATTRIBUTED_COMMENTARY:
            assert phrase not in (place.get("note") or "").lower(), f"{place['id']} note has commentary: {phrase}"
    for theme in themes["themes"]:
        theme_text = ((theme.get("subtitle") or "") + (theme.get("note") or "")).lower()
        for phrase in UNATTRIBUTED_COMMENTARY:
            assert phrase not in theme_text, f"{theme['id']} has commentary: {phrase}"
        for entry in theme.get("items") or []:
            note = entry.get("note") or ""
            for phrase in UNATTRIBUTED_COMMENTARY:
                assert phrase not in note.lower(), f"{theme['id']} item {entry.get('id')} note has commentary: {phrase}"


def test_latest_sidecar_picks_the_highest_version(tmp_path: Path) -> None:
    """item-10.json beats item-2.json beats item.json — a lexical sort would
    pick item-9 for item1..item10 (2026-08-06 review)."""
    folder = tmp_path / "x"
    folder.mkdir()
    for name in ("item.json", "item-2.json", "item-10.json", "item-3.json"):
        (folder / name).write_text("{}", encoding="utf-8")
    latest = _latest_sidecar(folder)
    assert latest is not None and latest.name == "item-10.json"
    assert _latest_sidecar(tmp_path / "empty") is None
