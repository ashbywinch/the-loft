"""Capture a scanned document into the archive — the document-capture
flow (the 2001 family-history email, doc-2001-02-07). People and
places enter the table as proposed; the item is the printed email.
Idempotent: each section skips what already exists.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tools.loft_paths import ARCHIVE_DIR

if TYPE_CHECKING:
    from tools.archive import Archive


_import_content: dict[str, Any] | None = None


def _import_data() -> dict[str, Any]:
    """The import's declared content. The real family data lives in the
    gitignored archive (archive/import-content.json), never in code — the
    public repo ships a data-free import (2026-08-08, user)."""
    global _import_content
    if _import_content is None:
        path = ARCHIVE_DIR / "import-content.json"
        _import_content = json.loads(path.read_text(encoding="utf-8"))
    assert _import_content is not None
    return _import_content


def _spouse(a: str, b: str) -> dict[str, str]:
    return {"a": a, "b": b, "kind": "spouse", "label_a": "spouse", "label_b": "spouse"}


def _parent(parent: str, child: str) -> dict[str, str]:
    return {"a": parent, "b": child, "kind": "parent", "label_a": "child", "label_b": "parent"}


def email_cast() -> list[dict[str, Any]]:
    """The letter's declared cast (people the import asserts). The real
    content lives in the gitignored archive, never in code (2026-08-08)."""
    return _import_data()["email"]["people"]


def email_edges() -> list[dict[str, Any]]:
    """The letter import's declared family edges — loaded from the dataset."""
    return _import_data()["email"]["edges"]


def capture_document(archive: Archive, scans: Path) -> None:

    # -- people: the email's cast, proposed, in the table ------------------
    people_table = archive.get_identity("people")
    assert people_table is not None, "archive has no people table"
    if any(p["id"] == _import_data()["email"]["first_person_id"] for p in people_table["people"]):
        print("note: email people already in the table — skipping")
    else:
        new_people = email_cast()
        for person in new_people:
            people_table["people"].append({**person, "status": "proposed", "years": "—"})

        # corrections the email brings to existing records
        by_id = {p["id"]: p for p in people_table["people"]}
        for person_id, fields in _import_data()["email"]["corrections"].items():
            by_id[person_id].update({k: v for k, v in fields.items() if not k.startswith("_")})

        # the family edges
        relations = email_edges()
        existing_edges = {(r.get("a"), r.get("b"), r.get("kind")) for r in people_table.get("relationships") or []}
        new_edges = [r for r in relations if (r["a"], r["b"], r["kind"]) not in existing_edges]
        people_table["relationships"] = list(people_table.get("relationships") or []) + new_edges
        archive.save_identity("people", people_table)
        print(f"people superseded: +{len(new_people)} proposed, +{len(new_edges)} edges")

    # -- places: proposed, coordinates marked for verification (Rule O) ----
    places_table = archive.get_identity("places")
    assert places_table is not None, "archive has no places table"
    if any(p["id"] == _import_data()["email"]["first_place_id"] for p in places_table["places"]):
        print("note: email places already present — skipping")
    else:
        new_places = _import_data()["email"]["places"]

        places_table["places"] = list(places_table["places"]) + new_places
        archive.save_identity("places", places_table)
        print(f"places superseded: +{len(new_places)} proposed")

    # -- the item ------------------------------------------------------------
    if archive.get_item("doc-2001-02-07") is not None:
        print("note: doc-2001-02-07 already exists — skipping")
        return
    people_table = archive.get_identity("people")
    assert people_table is not None
    email_item = _import_data()["email"]["item"]
    content = email_item.pop("_content", None)
    archive.save_item(email_item, content=content)

    for page, source in [
        ("page-01.jpg", "63f3d37082e0cc248dcf7e32f5c7ea51e4718cdf3459bfa1cd78137c1bdfa754.jpg"),
        ("page-02.jpg", "240b7ec3b4bd2267c754cb0be1c65578561ac6fd074a4cd5fa1d92c402340750.jpg"),
        ("page-03.jpg", "c4148f278ef4232d2ec5ef8448beec18b73be15efd5858dc5a39fc15c3d2a3cb.jpg"),
        ("page-04.jpg", "f267ebd061c668b94072b6f40d459be38ae10829616ff30d3bcf8dcceabf6df3.jpg"),
        ("page-05.jpg", "874d373b64c9bb669a885593d7dc61b873fa1521164f35e1cb6d0a57f06331d1.jpg"),
    ]:
        path = scans / source
        if path.exists():
            archive.save_file("doc-2001-02-07", page, path.read_bytes())
    print("item doc-2001-02-07 written (5 pages, corrected transcription)")


# -- the interview demo's documents (the first captures) --------------------


def _refs(people: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Item refs to the record's people — one per record id."""
    return [{"id": str(p["id"]), "status": "proposed"} for p in people]


def _parent_edge(parent: str, child: str) -> dict[str, str]:
    return {"a": parent, "b": child, "kind": "parent", "label_a": "child", "label_b": "parent"}


def _spouse_edge(a: str, b: str) -> dict[str, str]:
    return {"a": a, "b": b, "kind": "spouse", "label_a": "spouse", "label_b": "spouse"}


def record_proposed() -> list[dict[str, Any]]:
    """The record book's proposed people — loaded from the dataset."""
    return _import_data()["record"]["proposed"]


def record_cast() -> list[dict[str, Any]]:
    """The record book's declared people — proposed plus the confirmed cast."""
    return record_proposed() + _import_data()["record"]["cast"]


def record_edges() -> list[dict[str, Any]]:
    """The record book's declared family edges — loaded from the dataset."""
    return _import_data()["record"]["edges"]


def record_confirmed_family() -> list[str]:
    """The people the user confirmed as family (2026-08-06) — data, not code."""
    return list(_import_data()["record"]["confirmed_family"])


def capture_demo_documents(archive: Archive, scans: Path) -> None:

    # the record book's people — used by the people supersede and the items
    proposed = record_proposed()

    # -- the orgs identity table (confirmed at import review) ---------------
    if archive.get_identity("orgs") is None:
        archive.save_identity("orgs", {"orgs": _import_data()["record"]["orgs"]})
    else:
        print("note: orgs table already present — skipping")

    # -- people: confirmed cast additions + the record's proposed people and
    #    relationships, one supersede. Proposed people are table people with
    #    status proposed; the table resolves regardless of status -----------
    table = archive.get_identity("people")
    assert table is not None, "archive has no people table"
    by_id = {p["id"]: p for p in table["people"]}
    changed = False

    def add_fields(person_id: str, **fields: object) -> None:
        by_id[person_id].update(fields)

    for person_id, patch in _import_data()["record"]["patches"].items():
        add_fields(person_id, **patch.get("fields", {}))
        extra = patch.get("aliases", [])
        if extra:
            by_id[person_id]["aliases"] = sorted(set(by_id[person_id]["aliases"]) | set(extra))
    if _import_data()["record"]["stacey"]["id"] not in by_id:
        table["people"].append(_import_data()["record"]["stacey"])
        changed = True

    # the record book's people — status proposed, in the table
    for person in proposed:
        if person["id"] not in by_id:
            table["people"].append({**person, "status": "proposed", "years": "—"})
            changed = True

    # the record's family structure — table edges; endpoints may be
    # proposed (the table resolves regardless of status)
    relationships = record_edges()
    existing_edges = {(r.get("a"), r.get("b"), r.get("kind")) for r in table.get("relationships") or []}
    new_edges = [r for r in relationships if (r["a"], r["b"], r["kind"]) not in existing_edges]
    if new_edges:
        table["relationships"] = list(table.get("relationships") or []) + new_edges
        changed = True
    if changed:
        archive.save_identity("people", table)
    else:
        print("note: people table already up to date — skipping")

    # -- places: address on the family houses -------------------------------
    # (household moved to Person.residence — the GEDCOM-aligned seam; a
    # `household` key on a place is silently dropped by the Place model,
    # 2026-08-06 review)
    places = archive.get_identity("places")
    assert places is not None, "archive has no places table"
    pl_by_id = {p["id"]: p for p in places["places"]}
    if _import_data()["record"]["first_place_id"] in pl_by_id:
        print(f"note: {_import_data()['record']['first_place_id']} already present — skipping places")
    else:
        place_patch = _import_data()["record"]["place_patch"]
        pl_by_id[place_patch["id"]]["address"] = place_patch["address"]
        places["places"].append(_import_data()["record"]["bushey"])
        archive.save_identity("places", places)

    # -- the items -----------------------------------------------------------
    targets = {
        "letter-1949-02-04",
        "letter-1949-01-27",
        "object-paul-design-1949",
        "doc-halifax-1973-01-31",
        "doc-family-record-1868-03-20",
        "object-pilgrims-progress",
    }
    present = sorted(targets & set(archive.item_ids()))
    if present:
        print(f"note: items already imported ({', '.join(present)}) — skipping the item section")
    else:
        for item in _import_data()["record"]["items"]:
            content = item.pop("_content", None)
            archive.save_item(item, content=content)
        print(f"record items imported ({len(_import_data()['record']['items'])})")
