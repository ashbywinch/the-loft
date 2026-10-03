"""Tests for the GEDCOM 7.0 export (tools/gedcom_document.py): the one-to-one
mapping holds, the output parses under gedcom7's strict ABNF grammar (a
successful parse IS the standard validation), and the export policy holds —
nothing unconfirmed leaves the archive (the alignment decision)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gedcom7

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
    text = GedcomDocument.from_archive(make_archive()).to_text()
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
    assert (
        GedcomDocument.from_archive(make_archive()).to_text() == GedcomDocument.from_archive(make_archive()).to_text()
    )


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
    text = GedcomDocument.from_archive(archive).to_text()
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
    text = GedcomDocument.from_archive(archive).to_text()
    _parse(text)
    imported = GedcomDocument.from_text(text).wire_shapes()
    by_id = {p["id"]: p for p in imported["people"]}
    places_table = archive.get_identity("places")
    place_names = {p["id"]: p.get("name", p["id"]) for p in places_table["places"]} if places_table else {}
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
        # imported data is confirmed by construction), and the island's
        # imported residence carries the place NAME as given — the archive
        # residence's place id resolves to its name for the comparison
        def no_status(entries: list[dict[str, str]]) -> list[dict[str, str]]:
            return [{k: v for k, v in e.items() if k != "status"} for e in entries]

        def as_exported(entries: list[dict[str, str]]) -> list[dict[str, str]]:
            out = []
            for e in entries:
                entry = dict(e)
                if entry.get("place") in place_names:
                    entry["place"] = place_names[entry["place"]]
                out.append(entry)
            return out

        assert no_status(got.get("residence") or []) == as_exported(no_status(person.get("residence") or []))

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
    text = GedcomDocument.from_archive(archive).to_text()
    _parse(text)
    places_table = archive.get_identity("places")
    assert places_table is not None
    imported = GedcomDocument.from_text(text).wire_shapes()["people"][0]
    assert imported["dob"] == {"date": "1917", "precision": "after"}
    assert imported["dod"] == {"date": "1880", "date2": "1881", "precision": "between"}


def test_multi_married_parent_children_route_by_co_parent() -> None:
    """A person with several marriages: each child goes to the FAM of its
    attested co-parent — never the parent's last spouse."""
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
    text = GedcomDocument.from_archive(archive).to_text()
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
    the pair's position decides."""
    from tools.gedcom_document import _role

    assert _role({"pronouns": "she/her"}, 0) == "WIFE"
    assert _role({"pronouns": "he/him"}, 1) == "HUSB"
    assert _role({"pronouns": "they/them"}, 0) == "HUSB"  # positional, not inferred
    assert _role({"pronouns": "they/them"}, 1) == "WIFE"
    assert _role({}, 1) == "WIFE"


def test_dated_marriage_exports_as_marr() -> None:
    """A dated spouse edge's date is attested data — it exports as 1 MARR,
    never dropped."""
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
    text = GedcomDocument.from_archive(archive).to_text()
    assert "1 MARR" in text
    assert "2 DATE 20 JUN 1888" in text
    records = _parse(text)
    fam = [r for r in records if r.tag == "FAM"][0]
    assert any(c.tag == "MARR" for c in fam.children)


def test_dated_marriage_round_trips_onto_the_spouse_edge() -> None:
    """Export emits 1 MARR; import reads it back onto the spouse edge —
    a dated marriage survives the round trip."""
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
    text = GedcomDocument.from_archive(archive).to_text()
    places_table = archive.get_identity("places")
    assert places_table is not None
    imported = GedcomDocument.from_text(text).wire_shapes()
    assert imported["relationships"] == [
        {"a": "p-a", "b": "p-b", "kind": "spouse", "date": {"date": "1888-06-20", "precision": "exact"}}
    ]


def test_residence_place_is_the_name_as_given() -> None:
    """A GEDCOM RESI naming a place outside any place set is only text —
    the island has no destination coupling: the place NAME is written as
    given (a place entity is created for it), never a link, never an
    error (the invented unknown-place ValueError is gone)."""
    text = "\n".join(
        [
            "0 HEAD",
            "0 @I1@ INDI",
            "1 REFN p-a",
            "1 NAME Beatrice",
            "1 RESI",
            "2 DATE FROM 1960 TO 1970",
            "2 PLAC Nowhere-in-Particular",
            "2 NOTE Lived in the village.",
            "0 TRLR",
        ]
    )
    shapes = GedcomDocument.from_text(text).wire_shapes()
    (residence,) = shapes["people"][0]["residence"]
    assert residence["place"] == "Nowhere-in-Particular"  # the name as given
    assert residence["note"] == "Lived in the village."
    assert [p["name"] for p in shapes["places"]] == ["Nowhere-in-Particular"]  # all entries at import, places included
    # the round trip re-emits both the PLAC and the NOTE
    out = GedcomDocument.from_text(text).to_text()
    assert "2 PLAC Nowhere-in-Particular" in out

    assert "2 NOTE Lived in the village." in out
    assert GedcomDocument.from_text(out).wire_shapes() == shapes


def test_one_sided_residence_dates_export_cleanly() -> None:
    """A residence with only one date side emits that side — never a
    dangling 'TO ' (review-bot finding on PR #61: hand-authored
    residences can carry a single side)."""
    doc = GedcomDocument.from_shapes(
        {
            "people": [
                {
                    "id": "p-a",
                    "name": "Beatrice",
                    "residence": [{"from": "1900", "to": ""}, {"from": "", "to": "1910"}],
                }
            ],
            "relationships": [],
            "places": [],
        }
    )
    out = doc.to_text()
    assert "2 DATE FROM 1900" in out
    assert "2 DATE TO 1910" in out
    assert "FROM 1900 TO " not in out  # no dangling side
    _parse(out)  # the one-sided dates still parse under the strict grammar


def test_estimated_people_and_edges_export_with_their_evidence() -> None:
    """(user: "Estimated things should be IN along with the
    conversation that generated the estimate, so we know what the evidence
    is for this estimate") — an estimated person and an estimated edge are
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
    text = GedcomDocument.from_archive(archive).to_text()
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


MAXIMAL70 = Path(__file__).parent / "fixtures" / "maximal70.ged"


def _maximal_shapes() -> dict[str, Any]:
    return GedcomDocument.from_text(MAXIMAL70.read_text(encoding="utf-8")).wire_shapes()


def test_maximal70_round_trip_both_directions() -> None:
    """The fixture pins the closed record set: a construct the fixture
    exercises and the export re-emits must have its record; nothing is
    dropped as a parse-time convenience. import -> export -> import is
    identical on the confirmed subset, both directions (export -> import
    -> export is stable too)."""
    shapes = _maximal_shapes()
    # the old importer dropped every record without a REFN (I2/I3/I4) and
    # their edges — the fixture's flag of that error: ids fall back to the
    # record's xref
    assert [p["id"] for p in shapes["people"]] == ["1", "I2", "I3", "I4"]
    person = shapes["people"][0]
    assert person["name"].startswith("Lt. Cmndr. Joseph")
    assert person["aliases"] == ["John /Doe/", "Aka", "Immigrant Name"]
    assert person["dob"] == {"date": "2000-01-01", "precision": "exact"}
    assert person["dod"] == {"date": "2022-03-28", "precision": "exact"}
    assert person["occupations"] == ["occu"]
    assert person["residence"] == [{"from": "", "to": "", "place": ""}]
    # the F1 family rides the round trip: spouse + parents. The F1-level
    # ASSO (the record's ROLE OTHER association with @I3@) is outside the
    # closed set: the export re-emits only person-level ASSOs, so it has
    # no record (nothing the export re-emits may be dropped — nothing it
    # does not re-emit needs one)
    assert sorted((r["a"], r["kind"], r["b"]) for r in shapes["relationships"]) == [
        ("1", "parent", "I4"),
        ("1", "spouse", "I2"),
        ("I2", "parent", "I4"),
    ]
    spouse = next(r for r in shapes["relationships"] if r["kind"] == "spouse")
    assert spouse["date"] == {"date": "2022-03-27", "precision": "exact"}
    # places: every distinct PLAC payload name becomes a Place — including
    # the nested SOUR DATA payload (the recursive walk)
    assert [p["id"] for p in shapes["places"]] == [
        "place",
        "some-city-some-county-some-state-some-country",
        "somewhere",
    ]

    out = GedcomDocument.from_text(MAXIMAL70.read_text(encoding="utf-8")).to_text()
    _parse(out)  # the strict ABNF parse is the standards validation
    assert "0 @PL1@ PLAC" in out and "1 REFN place" in out and "1 NAME Place" in out

    # both directions of the round trip
    assert GedcomDocument.from_text(out).wire_shapes() == shapes
    assert GedcomDocument.from_text(out).to_text() == out


def test_import_writes_the_folder_and_refuses_double_import(tmp_path) -> None:
    """The island is the folder: an import writes the record files into
    the named folder; a target that exists and is non-empty is refused;
    a fresh folder gets an identical structure."""
    import json

    from tools.cli import main

    f1 = tmp_path / "island-1"
    f2 = tmp_path / "island-2"
    assert main(["gedcom", "import", str(MAXIMAL70), str(f1)]) == 0
    assert (f1 / "people.json").is_file() and (f1 / "places.json").is_file()
    assert json.loads((f1 / "places.json").read_text(encoding="utf-8")) == {
        "places": [
            {"id": "place", "name": "Place"},
            {
                "id": "some-city-some-county-some-state-some-country",
                "name": "Some City, Some County, Some State, Some Country",
            },
            {"id": "somewhere", "name": "Somewhere"},
        ]
    }
    # the same file into the SAME folder again is refused (exists, non-empty)
    assert main(["gedcom", "import", str(MAXIMAL70), str(f1)]) == 1
    # ... and a fresh folder gets an identical structure
    assert main(["gedcom", "import", str(MAXIMAL70), str(f2)]) == 0
    assert (f2 / "people.json").read_bytes() == (f1 / "people.json").read_bytes()
    assert (f2 / "places.json").read_bytes() == (f1 / "places.json").read_bytes()


def test_status_faithfulness(tmp_path) -> None:
    """``1 _LOFT_STATUS pending`` marks the record pending; unmarked
    records are not. Pending people, edges and places stay out of the
    export, and re-import of the confirmed subset is identical."""
    text = "\n".join(
        [
            "0 HEAD",
            "0 @I1@ INDI",
            "1 REFN p-a",
            "1 NAME Beatrice",
            "1 _LOFT_STATUS pending",
            "0 @I2@ INDI",
            "1 REFN p-b",
            "1 NAME Edward",
            "0 @F1@ FAM",
            "1 _LOFT_STATUS pending",
            "1 HUSB @I1@",
            "1 WIFE @I2@",
            "0 @PL1@ PLAC",
            "1 NAME Seascale",
            "1 _LOFT_STATUS pending",
            "0 @PL2@ PLAC",
            "1 NAME Dunmail",
            "0 TRLR",
        ]
    )
    shapes = GedcomDocument.from_text(text).wire_shapes()
    assert {p["id"]: p.get("status") for p in shapes["people"]} == {"p-a": "pending", "p-b": None}
    assert shapes["relationships"] == [{"a": "p-a", "b": "p-b", "kind": "spouse", "status": "pending"}]
    assert [{"id": pl["id"], "name": pl["name"], "status": pl.get("status")} for pl in shapes["places"]] == [
        {"id": "dunmail", "name": "Dunmail", "status": None},
        {"id": "seascale", "name": "Seascale", "status": "pending"},
    ]
    # nothing pending leaves — people, edges, places; the confirmed
    # subset round-trips exactly
    out = GedcomDocument.from_text(text).to_text()
    assert "Beatrice" not in out and "_LOFT_STATUS" not in out
    assert "Seascale" not in out and "Dunmail" in out  # the pending PLAC record stays out
    reimported = GedcomDocument.from_text(out).wire_shapes()
    assert reimported["people"] == [p for p in shapes["people"] if p.get("status") != "pending"]
    assert reimported["places"] == [p for p in shapes["places"] if p.get("status") != "pending"]


def test_export_four_refusals(tmp_path) -> None:
    """Swapped parameters cannot make a mess: the export refuses before
    writing when the first argument is not an import folder, the
    destination is the import folder or inside it, the destination is an
    existing directory, or an existing file."""
    from tools.cli import main

    island = tmp_path / "island"
    main(["gedcom", "import", str(MAXIMAL70), str(island)])

    # 1. a bare file path, or a folder without the imported structure
    assert main(["gedcom", "export", str(MAXIMAL70), str(tmp_path / "out.ged")]) == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["gedcom", "export", str(empty), str(tmp_path / "out.ged")]) == 1
    # 2. the destination is the import folder or any path inside it
    assert main(["gedcom", "export", str(island), str(island)]) == 1
    assert main(["gedcom", "export", str(island), str(island / "inside.ged")]) == 1
    # 3. an existing directory, 4. an existing file
    dest_dir = tmp_path / "dest-dir"
    dest_dir.mkdir()
    assert main(["gedcom", "export", str(island), str(dest_dir)]) == 1
    existing = tmp_path / "existing.ged"
    existing.write_text("already here", encoding="utf-8")
    assert main(["gedcom", "export", str(island), str(existing)]) == 1
    assert existing.read_text(encoding="utf-8") == "already here"

    # a clean destination exports the confirmed subset
    out = tmp_path / "out.ged"
    assert main(["gedcom", "export", str(island), str(out)]) == 0
    assert out.exists()


def test_export_reads_the_folder() -> None:
    """Export re-emits the confirmed subset from the folder's record
    files — the round trip through the folder is the same document."""
    doc = GedcomDocument.from_text(MAXIMAL70.read_text(encoding="utf-8"))
    assert doc.to_text() == GedcomDocument.from_shapes(doc.wire_shapes()).to_text()


def test_person_association_role_round_trips() -> None:
    """A person-level ASSO (GEDCOM 7's ROLE, the earlier RELA) becomes an
    edge of its label — and re-emits as an ASSO, so the closed set holds
    for associations too."""
    text = "\n".join(
        [
            "0 HEAD",
            "0 @I1@ INDI",
            "1 REFN p-a",
            "1 NAME Beatrice",
            "1 ASSO @I2@",
            "2 ROLE OTHER",
            "0 @I2@ INDI",
            "1 REFN p-b",
            "1 NAME Edward",
            "0 TRLR",
        ]
    )
    shapes = GedcomDocument.from_text(text).wire_shapes()
    assert shapes["relationships"] == [{"a": "p-a", "b": "p-b", "kind": "other"}]
    out = GedcomDocument.from_text(text).to_text()
    assert "1 ASSO @P2@" in out and "2 RELA other" in out
    assert GedcomDocument.from_text(out).wire_shapes() == shapes


def test_import_refuses_a_regular_file_target(tmp_path) -> None:
    """A swapped import argument (a bare file as the folder) refuses
    cleanly — never a NotADirectoryError traceback (review-bot finding
    on PR #61)."""
    from tools.cli import main

    file_target = tmp_path / "existing.txt"
    file_target.write_text("not a folder", encoding="utf-8")
    assert main(["gedcom", "import", str(MAXIMAL70), str(file_target)]) == 1
    assert file_target.read_text(encoding="utf-8") == "not a folder"  # untouched


def test_export_refuses_a_missing_parent_directory(tmp_path) -> None:
    """A destination whose parent directory does not exist is refused
    cleanly — never a FileNotFoundError traceback (the swapped/mistyped
    path case the refusals guard against; review-bot finding)."""
    from tools.cli import main

    island = tmp_path / "island"
    main(["gedcom", "import", str(MAXIMAL70), str(island)])
    missing = tmp_path / "no-such-dir" / "out.ged"
    assert main(["gedcom", "export", str(island), str(missing)]) == 1
    assert not missing.exists()


def test_places_sort_by_id_not_name() -> None:
    """The island's places file is id-ordered like every other record
    file — a PLAC record whose REFN does not sort like its name must not
    reorder the table (review-bot finding on PR #61)."""
    text = "\n".join(
        [
            "0 HEAD",
            "0 @PL1@ PLAC",
            "1 REFN zzz",
            "1 NAME Alpha",
            "0 @PL2@ PLAC",
            "1 REFN aaa",
            "1 NAME Zebra",
            "0 TRLR",
        ]
    )
    places = GedcomDocument.from_text(text).wire_shapes()["places"]
    assert [p["id"] for p in places] == ["aaa", "zzz"]
    assert [p["name"] for p in places] == ["Zebra", "Alpha"]


def test_existing_folder_target_any_content_is_refused(tmp_path) -> None:
    """The import refusal is 'exists and is non-empty' — an EMPTY existing
    folder is a legal target (the double-import test covers the refusal);
    a folder with any content, even unrelated, is refused."""
    from tools.cli import main

    cluttered = tmp_path / "cluttered"
    cluttered.mkdir()
    (cluttered / "notes.txt").write_text("unrelated", encoding="utf-8")
    assert main(["gedcom", "import", str(MAXIMAL70), str(cluttered)]) == 1
    empty = tmp_path / "empty-target"
    empty.mkdir()
    assert main(["gedcom", "import", str(MAXIMAL70), str(empty)]) == 0
