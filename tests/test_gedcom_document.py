"""Tests for the GEDCOM 7.0 export (tools/gedcom_document.py): the one-to-one
mapping holds, the output parses under gedcom7's strict ABNF grammar (a
successful parse IS the standard validation), and the export policy holds —
nothing unconfirmed leaves the archive (2026-08-05 alignment decision)."""

from __future__ import annotations

from typing import Any

import gedcom7
import pytest

from tools.archive import Archive
from tools.gedcom_document import GedcomDocument, gedcom_date
from tools.store import MemoryStore


def make_archive() -> Archive:
    archive = Archive(MemoryStore())
    archive.save_identity(
        "people",
        {
            "people": [
                {
                    "id": "p-mum",
                    "name": "Mum",
                    "pronouns": "she/her",
                    "hue": "amber",
                    "residence": [{"place": "pl-town", "from": "1973", "to": "1973", "status": "confirmed"}],
                },
                {"id": "p-dad", "name": "Dad", "pronouns": "he/him", "hue": "sky"},
                {"id": "p-kid", "name": "Kid", "hue": "rose"},
                {"id": "p-stranger", "name": "Stranger", "status": "proposed"},
            ],
            "relationships": [
                {"a": "p-mum", "b": "p-dad", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"},
                {"a": "p-mum", "b": "p-kid", "kind": "parent", "label_a": "child", "label_b": "parent"},
                {"a": "p-dad", "b": "p-kid", "kind": "parent", "label_a": "child", "label_b": "parent"},
                {"a": "p-mum", "b": "p-stranger", "kind": "parent", "label_a": "child", "label_b": "parent"},
            ],
        },
    )
    archive.save_identity("places", {"places": [{"id": "pl-town", "name": "Town"}]})
    archive.save_identity("themes", {"themes": []})
    archive.save_item(
        {
            "id": "story-x",
            "type": "story",
            "title": "X",
            "date": "2026-08-01",
            "date_precision": "exact",
            "story": "A family memory about Mum.",
            "told_by": "p-kid",
            "people": [{"id": "p-mum", "status": "confirmed"}],
            "places": [],
            "themes": [],
            "assets": [],
            "status": "catalogued",
            "created": "2026-08-05",
        }
    )
    return archive


def _parse(text: str) -> list[Any]:
    return gedcom7.loads(text)  # a strict ABNF parse — failure here is a standards violation


def test_export_parses_and_honours_the_policy() -> None:
    """Confirmed people/edges export; proposed people and edges do not;
    stories shoehorn onto the people they reference as NOTES."""
    text = GedcomDocument.to_text(make_archive())
    records = _parse(text)
    indis = [r for r in records if r.tag == "INDI"]
    assert [r.xref for r in indis] == ["@P1@", "@P2@", "@P3@"]  # p-stranger excluded
    names = " ".join(r.text or "" for r in indis)
    assert "Stranger" not in names
    fams = [r for r in records if r.tag == "FAM"]
    assert len(fams) == 1  # the proposed parent edge (mum -> stranger) is not exported
    mum = next(r for r in indis if any(c.tag == "NAME" and c.text == "Mum" for c in r.children))
    assert any(c.tag == "NOTE" and "family memory" in c.text for c in mum.children)


def test_export_is_deterministic() -> None:
    assert GedcomDocument.to_text(make_archive()) == GedcomDocument.to_text(make_archive())


def test_export_round_trips_dates_and_roles() -> None:
    archive = make_archive()
    archive.save_identity(
        "people",
        {
            "people": [
                {
                    "id": "p-mum",
                    "name": "Mum",
                    "pronouns": "she/her",
                    "dob": {"date": "1947-05-11", "precision": "exact"},
                },
                {"id": "p-dad", "name": "Dad", "dob": {"date": "1938", "precision": "approx"}},
            ],
            "relationships": [{"a": "p-mum", "b": "p-dad", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"}],
        },
    )
    text = GedcomDocument.to_text(archive)
    _parse(text)
    assert "2 DATE 11 MAY 1947" in text  # exact full date
    assert "2 DATE ABT 1938" in text  # approx -> ABT prefix
    assert "1 WIFE @P2@" in text and "1 HUSB @P1@" in text  # roles from attested pronouns, sorted ids


def test_gedcom_date_mapping() -> None:
    assert gedcom_date("1871-01-07", "exact") == "7 JAN 1871"
    assert gedcom_date("1901-01", "month") == "JAN 1901"
    assert gedcom_date("1938", "year") == "1938"
    assert gedcom_date("1917", "approx") == "ABT 1917"
    assert gedcom_date("1881", "before") == "BEF 1881"
    assert gedcom_date("1880", "between", "1881") == "BET 1880 AND 1881"


def test_round_trip_is_exact_for_what_the_export_carries() -> None:
    """export -> import recovers the confirmed genealogy exactly: ids via
    REFN, names/aliases, dob/dod with bound precisions, occupations,
    residence, and the confirmed edges — proposed data never appears."""
    archive = make_archive()
    people_table = archive.get_identity("people")
    places_table = archive.get_identity("places")
    assert people_table is not None and places_table is not None
    people = people_table["people"]
    confirmed = [p for p in people if p.get("status") != "proposed"]
    confirmed_edges = [
        r
        for r in people_table["relationships"]
        if r.get("a") in {p["id"] for p in confirmed} and r.get("b") in {p["id"] for p in confirmed}
    ]
    text = GedcomDocument.to_text(archive)
    _parse(text)
    imported = GedcomDocument.from_text(text, places_table["places"])

    by_id = {p["id"]: p for p in imported["people"]}
    assert set(by_id) == {p["id"] for p in confirmed}
    for person in confirmed:
        got = by_id[person["id"]]
        assert got["name"] == person["name"]
        assert (got.get("aliases") or []) == (person.get("aliases") or [])
        assert got.get("dob") == person.get("dob")
        assert got.get("dod") == person.get("dod")
        assert (got.get("occupations") or []) == (person.get("occupations") or [])

        # residence status is archive-internal (confirmed-only exports; the
        # imported data is confirmed by construction)
        def no_status(entries: list[dict[str, str]]) -> list[dict[str, str]]:
            return [{k: v for k, v in e.items() if k != "status"} for e in entries]

        assert no_status(got.get("residence") or []) == no_status(person.get("residence") or [])

    def _norm(edges: list[dict[str, str]]) -> list[dict[str, str]]:
        """Spouse edges are undirected — the FAM's positional roles cannot
        carry the authoring direction, so the round-trip compares them as
        unordered pairs."""
        out = []
        for e in edges:
            e = dict(e)
            if e["kind"] == "spouse" and e["a"] > e["b"]:
                e["a"], e["b"] = e["b"], e["a"]
            out.append(e)
        return sorted(out, key=lambda r: (r["a"], r["kind"], r["b"]))

    expected_edges = [
        {"a": r["a"], "b": r["b"], "kind": r["kind"]}
        for r in confirmed_edges
        if r.get("a") in {p["id"] for p in confirmed} and r.get("b") in {p["id"] for p in confirmed}
    ]
    assert _norm(imported["relationships"]) == _norm(expected_edges)


def test_round_trip_preserves_bound_precisions() -> None:
    """before / after / between survive the full cycle."""
    archive = make_archive()
    archive.save_identity(
        "people",
        {
            "people": [
                {
                    "id": "p-x",
                    "name": "X",
                    "dob": {"date": "1917", "precision": "after"},
                    "dod": {"date": "1880", "date2": "1881", "precision": "between"},
                }
            ],
            "relationships": [],
        },
    )
    text = GedcomDocument.to_text(archive)
    _parse(text)
    places_table = archive.get_identity("places")
    assert places_table is not None
    imported = GedcomDocument.from_text(text, places_table["places"])["people"][0]
    assert imported["dob"] == {"date": "1917", "precision": "after"}
    assert imported["dod"] == {"date": "1880", "date2": "1881", "precision": "between"}


def test_multi_married_parent_children_route_by_co_parent() -> None:
    """A person with several marriages: each child goes to the FAM of its
    attested co-parent — never the parent's last spouse (2026-08-06)."""
    archive = Archive(MemoryStore())
    archive.save_identity(
        "people",
        {
            "people": [
                {"id": "p-harper", "name": "Harper"},
                {"id": "p-h1", "name": "Husband One"},
                {"id": "p-h2", "name": "Husband Two"},
                {"id": "p-k1", "name": "Kid One"},
                {"id": "p-k2", "name": "Kid Two"},
            ],
            "relationships": [
                {"a": "p-harper", "b": "p-h1", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"},
                {"a": "p-harper", "b": "p-h2", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"},
                # kid one belongs to the first marriage, kid two to the second
                {"a": "p-harper", "b": "p-k1", "kind": "parent", "label_a": "child", "label_b": "parent"},
                {"a": "p-h1", "b": "p-k1", "kind": "parent", "label_a": "child", "label_b": "parent"},
                {"a": "p-harper", "b": "p-k2", "kind": "parent", "label_a": "child", "label_b": "parent"},
                {"a": "p-h2", "b": "p-k2", "kind": "parent", "label_a": "child", "label_b": "parent"},
            ],
        },
    )
    archive.save_identity("places", {"places": []})
    archive.save_identity("themes", {"themes": []})
    text = GedcomDocument.to_text(archive)
    records = _parse(text)
    fams = [r for r in records if r.tag == "FAM"]
    # two spouse Fams exist, each holding exactly one child — no silent
    # misattribution of kid one to the last spouse
    assert len(fams) == 2
    assert all(sum(1 for x in f.children if x.tag == "CHIL") == 1 for f in fams)
    # each child sits with its attested co-parent, not the last spouse
    parents_of = {
        c.pointer: {x.pointer for x in f.children if x.tag in ("HUSB", "WIFE")}
        for f in fams
        for c in f.children
        if c.tag == "CHIL"
    }
    # the xref map: sorted ids -> P1.. — p-h1=P1, p-h2=P2, p-harper=P3, p-k1=P4, p-k2=P5
    assert "@P1@" in parents_of["@P4@"] and "@P2@" not in parents_of["@P4@"]
    assert "@P2@" in parents_of["@P5@"] and "@P1@" not in parents_of["@P5@"]


def test_role_never_infers_gender() -> None:
    """A person without she/he pronouns is not forced into HUSB by default —
    the pair's position decides (2026-08-06)."""
    from tools.gedcom_document import _role

    assert _role({"pronouns": "she/her"}, 0) == "WIFE"
    assert _role({"pronouns": "he/him"}, 1) == "HUSB"
    assert _role({"pronouns": "they/them"}, 0) == "HUSB"  # positional, not inferred
    assert _role({"pronouns": "they/them"}, 1) == "WIFE"
    assert _role({}, 1) == "WIFE"


def test_dated_marriage_exports_as_marr() -> None:
    """A dated spouse edge's date is attested data — it exports as 1 MARR,
    never dropped (2026-08-06 review)."""
    archive = Archive(MemoryStore())
    archive.save_identity(
        "people",
        {
            "people": [{"id": "p-a", "name": "A"}, {"id": "p-b", "name": "B"}],
            "relationships": [
                {
                    "a": "p-a",
                    "b": "p-b",
                    "kind": "spouse",
                    "label_a": "spouse",
                    "label_b": "spouse",
                    "date": {"date": "1888-06-20", "precision": "exact"},
                },
            ],
        },
    )
    archive.save_identity("places", {"places": []})
    archive.save_identity("themes", {"themes": []})
    text = GedcomDocument.to_text(archive)
    assert "1 MARR" in text
    assert "2 DATE 20 JUN 1888" in text
    records = _parse(text)
    fam = [r for r in records if r.tag == "FAM"][0]
    assert any(c.tag == "MARR" for c in fam.children)


def test_dated_marriage_round_trips_onto_the_spouse_edge() -> None:
    """Export emits 1 MARR; import reads it back onto the spouse edge —
    a dated marriage survives the round trip (2026-08-06 review)."""
    archive = make_archive()
    archive.save_identity(
        "people",
        {
            "people": [{"id": "p-a", "name": "A"}, {"id": "p-b", "name": "B"}],
            "relationships": [
                {
                    "a": "p-a",
                    "b": "p-b",
                    "kind": "spouse",
                    "label_a": "spouse",
                    "label_b": "spouse",
                    "date": {"date": "1888-06-20", "precision": "exact"},
                },
            ],
        },
    )
    archive.save_identity("places", {"places": []})
    archive.save_identity("themes", {"themes": []})
    text = GedcomDocument.to_text(archive)
    places_table = archive.get_identity("places")
    assert places_table is not None
    imported = GedcomDocument.from_text(text, places_table["places"])
    spouse = [r for r in imported["relationships"] if r["kind"] == "spouse"]
    assert spouse == [{"a": "p-a", "b": "p-b", "kind": "spouse", "date": {"date": "1888-06-20", "precision": "exact"}}]


def test_residence_with_unknown_place_fails_loud() -> None:
    """A GEDCOM RESI naming a place outside the archive's place set is
    data loss if swallowed — the import raises, naming the place
    (2026-08-06 review, fail-loud)."""
    text = "\n".join(
        [
            "0 HEAD",
            "0 @I1@ INDI",
            "1 REFN p-a",
            "1 NAME Beatrice",
            "1 RESI",
            "2 PLAC Nowhere-in-Particular",
            "0 TRLR",
        ]
    )
    with pytest.raises(ValueError, match="Nowhere-in-Particular"):
        GedcomDocument.from_text(text, [])


def test_estimated_people_and_edges_export_with_their_evidence() -> None:
    """2026-08-09 (user: "Estimated things should be IN along with the
    conversation that generated the estimate, so we know what the evidence
    is for this estimate"): an estimated person and an estimated edge are
    part of the family record — they export, each annotated with a NOTE
    carrying the review conversation's recorded basis (who said it, when,
    their own words). Proposed records still stay out."""
    archive = make_archive()
    people = archive.get_identity("people")
    assert people is not None
    people["people"] = people["people"] + [
        {
            "id": "p-cousin",
            "name": "Cousin",
            "status": "estimated",
            "basis": {"text": "Mum always said she was a cousin.", "by": "Kid", "when": "2026-08-09"},
        }
    ]
    people["relationships"] = people["relationships"] + [
        {
            "a": "p-mum",
            "b": "p-cousin",
            "kind": "parent",
            "label_a": "child",
            "label_b": "parent",
            "status": "estimated",
        },
        {
            "a": "p-mum",
            "b": "p-stranger",
            "kind": "parent",
            "label_a": "child",
            "label_b": "parent",
            "status": "proposed",
        },
    ]
    archive.save_identity("people", people)
    archive.save_identity(
        "imports",
        {
            "imports": [
                {
                    "id": "import-documents",
                    "title": "The document import",
                    "status": "pending",
                    "attempts": [
                        {
                            "started": "2026-08-09",
                            "messages": [],
                            "decisions": [
                                {
                                    "person_id": "p-cousin",
                                    "decision": "estimated",
                                    "when": "2026-08-09",
                                    "basis": {
                                        "text": "Mum always said she was a cousin.",
                                        "by": "Kid",
                                        "when": "2026-08-09",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )
    text = GedcomDocument.to_text(archive)
    records = _parse(text)
    indis = [r for r in records if r.tag == "INDI"]
    cousin = next(r for r in indis if any(c.tag == "NAME" and c.text == "Cousin" for c in r.children))
    assert not any(any(c.tag == "NAME" and c.text == "Stranger" for c in r.children) for r in indis)
    note = next(c.text for c in cousin.children if c.tag == "NOTE")
    assert 'Estimated — from Kid\'s recollection (2026-08-09): "Mum always said she was a cousin."' in note
    fams = [r for r in records if r.tag == "FAM"]
    # the estimated parent edge exports a single-parent FAM with the evidence
    # note; the proposed edge creates nothing
    assert len(fams) == 2
    fam = next(f for f in fams if any(c.tag == "NOTE" and "Estimated" in (c.text or "") for c in f.children))
    assert "from Kid's recollection" in next(c.text for c in fam.children if c.tag == "NOTE")
