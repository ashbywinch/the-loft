"""GEDCOM 7.0 export of the archive's genealogy (tools/export-gedcom).

The one-to-one mapping (ours -> GEDCOM 7.0), so every departure is a
decision, not an accident (alignment decision, 2026-08-05 — GEDCOM X as the
object-model reference, GEDCOM 7.0 as the interchange target):

| Ours                           | GEDCOM 7.0                          |
|--------------------------------|-------------------------------------|
| confirmed person               | INDI: NAME (canonical + aliases as  |
|                                |   extra NAME records)               |
| dob/dod (date + precision)     | BIRT/DEAT with DATE (ABT prefix for |
|                                |   approx precision)                 |
| occupations                    | OCCU                                |
| residence events               | RESI with DATE (FROM x TO y) + PLAC |
| confirmed spouse/parent edges  | FAM (HUSB/WIFE/CHIL); single-parent |
|                                |   FAM when the other spouse is      |
|                                |   unconfirmed                       |
| sibling / inlaw / teacher      | ASSO + RELA on the INDI             |
| catalogued story (the shoehorn)| NOTE on each confirmed person it    |
|                                |   references                        |
| place (used by residence)      | PLAC substructure (name payload)    |

Excluded by policy: proposed people and relationships (nothing unconfirmed
leaves the archive), draft items, organisations (no GEDCOM 7 home), and the
archive's non-genealogy items (memorabilia, testimonies-as-items, the
archive's own layout).

Stated departures: GEDCOM 7 xref ids are alphanumeric, so export ids are
assigned sequentially (P1.., F1..) in sorted order — the mapping to archive
ids is this module's order; FAM spouse roles are gendered (HUSB/WIFE) and
are assigned from attested pronouns when present, else positionally —
gender is never inferred; the proposed/confirmed seam, the archive's layout
and the non-genealogy content stay archive-only.

Verified by tests parsing the output with gedcom7 (a strict ABNF grammar —
a successful parse IS the standard validation).

Reached via `loft gedcom export|import` (tools/cli.py).
"""

from __future__ import annotations

import re
from typing import Any

import gedcom7

from tools.archive import Archive
from tools.projection import resolved_items

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# ISO-8601 fixed widths and dash positions, used to tell the date forms
# apart before the GEDCOM reorder: "YYYY-MM-DD" is 10 chars with dashes at
# 4 and 7; "YYYY-MM" is 7 chars with the dash at 4.
ISO_DATE_LEN = 10  # YYYY-MM-DD
ISO_YEAR_MONTH_LEN = 7  # YYYY-MM
YEAR_MONTH_DASH = 4  # the "-" between year and month in both forms
MONTH_DAY_DASH = 7  # the "-" between month and day in the full form
DAY_MONTH_YEAR_PARTS = 3  # "D MON YYYY" splits into day, month, year


def gedcom_date(value: str, precision: str, date2: str | None = None) -> str:
    """ISO date + our precision -> a GEDCOM 7 DATE payload.

    exact -> the date as written (24 MAR 1945); month -> MON YYYY;
    year -> YYYY; approx -> ABT; before -> BEF; after -> AFT;
    between -> BET <date> AND <date2>. Granularity is the date's form,
    never uncertainty; never a fake exact date."""
    out = value
    if len(value) == ISO_DATE_LEN and value[YEAR_MONTH_DASH] == "-" and value[MONTH_DAY_DASH] == "-":  # YYYY-MM-DD
        out = f"{int(value[8:10])} {MONTHS[int(value[5:7]) - 1]} {value[0:4]}"
    elif len(value) == ISO_YEAR_MONTH_LEN and value[YEAR_MONTH_DASH] == "-":  # YYYY-MM
        out = f"{MONTHS[int(value[5:7]) - 1]} {value[0:4]}"
    if precision == "approx":
        return f"ABT {out}"
    if precision == "before":
        return f"BEF {out}"
    if precision == "after":
        return f"AFT {out}"
    if precision == "between":
        return f"BET {out} AND {date2 or ''}"
    return out


def _lines(text: str, level: int = 1) -> list[str]:
    """Payload text split into GEDCOM lines with CONT continuations — the
    NOTE rides at `level` (1 under an INDI, 2 under an ASSO; 2026-08-11
    review: a level-1 note under an association attached itself to the
    person instead)."""
    lines = text.splitlines() or [""]
    out = [f"{level} NOTE {lines[0]}"]
    out += [f"{level + 1} CONT {line}" for line in lines[1:]]
    return out


def _role(person: dict[str, Any], position: int) -> str:
    """HUSB/WIFE from attested pronouns when present, else positionally
    (the first of a pair gets HUSB) — gender is never inferred: a
    they/them or unstated person is not forced into either role by
    default (2026-08-06)."""
    pronouns = str(person.get("pronouns") or "").lower()
    if pronouns.startswith("she"):
        return "WIFE"
    if pronouns.startswith("he"):
        return "HUSB"
    return "HUSB" if position == 0 else "WIFE"


def _estimate_basis(archive: Archive, person_id: str) -> dict[str, str] | None:
    """The recorded basis of an estimated link — the review session's
    decision carries the conversation's evidence (who said it, when, their
    own words). 2026-08-09 (user: estimated things export WITH the
    conversation that generated them, so the evidence for the estimate is
    visible)."""
    imports = archive.get_identity("imports") or {}
    for imp in imports.get("imports", []):
        for attempt in imp.get("attempts", []):
            for decision in attempt.get("decisions", []):
                if decision.get("person_id") == person_id and decision.get("decision") == "estimated":
                    basis = decision.get("basis")
                    if basis and basis.get("text"):
                        return basis
    return None


def _estimate_note(basis: dict[str, str] | None, level: int = 1) -> list[str]:
    """The estimate's evidence as a GEDCOM NOTE — the reviewer's own words,
    who said them, and when, so a reader of the export can weigh the guess
    (2026-08-09, user). The level places the note under its owner: the
    person (1) or the association it evidences (2)."""
    if basis and basis.get("text"):
        by = str(basis.get("by") or "the family")
        when = str(basis.get("when") or "")
        stamp = f" ({when})" if when else ""
        return _lines(f'Estimated — from {by}\'s recollection{stamp}: "{basis["text"]}"', level)
    return _lines("Estimated — the family's recollection; the basis is not recorded", level)


def export_gedcom(archive: Archive) -> str:
    """The GEDCOM 7.0 document for the archive's genealogy: confirmed
    people and edges export as facts; ESTIMATED people and edges export too
    — a human's guess is part of the family record — each annotated with a
    NOTE carrying the evidence that produced it (the review conversation's
    recorded basis). PROPOSED records — the import's machine guesses,
    awaiting review — stay out (2026-08-09, user)."""
    people = archive.get_identity("people")
    places = archive.get_identity("places")
    if people is None or places is None:
        raise RuntimeError("archive needs people and places identity tables")

    exported_ids, edges, place_names, by_id, xref = _export_set(people, places)

    families, fam_notes = _family_units(edges, archive)
    notes_by_person = _story_notes(archive, exported_ids)
    associations = _associations(edges, archive)

    # -- assemble the document
    lines: list[str] = [
        "0 HEAD",
        "1 SOUR the-loft-export",
        "2 VERS 0.1",
        "1 GEDC",
        "2 VERS 7.0",
        "2 FORM LINEAGE-LINKED",
        "1 CHAR UTF-8",
    ]
    for fam in families:
        lines += _family_lines(fam, by_id, xref, fam_notes)

    for pid in sorted(exported_ids):
        lines += _person_lines(
            person=by_id[pid],
            pid=pid,
            xref=xref,
            place_names=place_names,
            notes=notes_by_person.get(pid, []),
            associations=associations.get(pid, []),
            archive=archive,
        )

    lines.append("0 TRLR")
    return "\n".join(lines) + "\n"


def _export_set(
    people: dict[str, Any], places: dict[str, Any]
) -> tuple[set[str], list[dict[str, Any]], dict[str, str], dict[str, dict[str, Any]], dict[str, str]]:
    """The confirmed/estimated people and edges that leave the archive —
    proposed records stay out (2026-08-09 review) — plus the lookup maps:
    exported ids, edges, place names, people by id, and the deterministic
    xref ids (sorted order, documented mapping)."""
    exported = [p for p in people["people"] if p.get("status") in (None, "confirmed", "estimated")]
    exported_ids = {p["id"] for p in exported}
    edges = [
        r
        for r in people.get("relationships") or []
        if r.get("a") in exported_ids
        and r.get("b") in exported_ids
        and r.get("status") in (None, "confirmed", "estimated")  # proposed edges stay out too (2026-08-09 review)
    ]
    place_names = {p["id"]: p.get("name", p["id"]) for p in places["places"]}
    by_id = {p["id"]: p for p in exported}
    xref = {pid: f"P{i}" for i, pid in enumerate(sorted(exported_ids), start=1)}
    return exported_ids, edges, place_names, by_id, xref


def _family_units(edges: list[dict[str, Any]], archive: Archive) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """The FAM records: spouse pairs + their children, then single-parent
    FAMS. Returns (families, fam_notes) — an estimated edge's evidence
    rides on the FAM it created."""
    pairs, marriage_dates, pair_notes = _spouse_pairs(edges, archive)
    families, fam_of_pair, fam_notes, counter = _pair_families(pairs, marriage_dates, pair_notes)
    parent_of, estimated_parent_edges = _parent_edges(edges)
    children_of, single_parent, fam_notes, counter = _route_children(
        parent_of, fam_of_pair, families, fam_notes, counter, estimated_parent_edges, archive
    )
    for fam in families:
        fam["children"] = sorted(set(children_of.get(fam["id"], [])))
    families, fam_notes, _ = _single_parent_families(
        single_parent, estimated_parent_edges, families, fam_notes, counter, archive
    )
    return families, fam_notes


def _spouse_pairs(
    edges: list[dict[str, Any]], archive: Archive
) -> tuple[set[tuple[str, str]], dict[tuple[str, str], dict[str, str]], dict[tuple[str, str], list[str]]]:
    """The spouse edges -> the sorted pairs, their marriage dates, and the
    estimate evidence notes (a dated marriage exports as 1 MARR, 2026-08-06;
    an estimated edge's evidence rides the FAM it created)."""
    pairs: set[tuple[str, str]] = set()
    marriage_dates: dict[tuple[str, str], dict[str, str]] = {}
    pair_notes: dict[tuple[str, str], list[str]] = {}
    for edge in edges:
        if edge["kind"] == "spouse":
            a, b = edge["a"], edge["b"]
            pair = (a, b) if a < b else (b, a)
            pairs.add(pair)
            if edge.get("date"):
                marriage_dates[pair] = edge["date"]  # a dated marriage exports as 1 MARR (2026-08-06)
            if edge.get("status") == "estimated":
                pair_notes[pair] = _estimate_note(_estimate_basis(archive, b) or _estimate_basis(archive, a))
    return pairs, marriage_dates, pair_notes


def _pair_families(
    pairs: set[tuple[str, str]],
    marriage_dates: dict[tuple[str, str], dict[str, str]],
    pair_notes: dict[tuple[str, str], list[str]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], str], dict[str, list[str]], int]:
    """The spouse-pair FAM records, in sorted-pair order: one FAM per pair,
    keyed by pair for the child routing. Returns (families, fam_of_pair,
    fam_notes, counter) — the FAM counter is shared with the later
    single-parent records so ids stay assignment-ordered."""
    fam_of_pair: dict[tuple[str, str], str] = {}
    fam_notes: dict[str, list[str]] = {}  # an estimated edge's evidence rides the FAM it created
    families: list[dict[str, Any]] = []  # {id, spouse_a, spouse_b, children, marriage?}
    counter = 0
    for pair in sorted(pairs):
        counter += 1
        fid = f"F{counter}"
        fam_of_pair[pair] = fid
        families.append({"id": fid, "a": pair[0], "b": pair[1], "children": [], "marriage": marriage_dates.get(pair)})
        if pair in pair_notes:
            fam_notes.setdefault(fid, []).extend(pair_notes[pair])
    return families, fam_of_pair, fam_notes, counter


def _parent_edges(
    edges: list[dict[str, Any]],
) -> tuple[dict[str, list[str]], set[tuple[str, str]]]:
    """The parent edges -> child -> parents, and the estimated
    (parent, child) pairs whose evidence rides the FAM."""
    parent_of: dict[str, list[str]] = {}
    estimated_parent_edges: set[tuple[str, str]] = set()  # (parent, child) — the evidence rides the FAM
    for edge in edges:
        if edge["kind"] == "parent":
            parent_of.setdefault(edge["b"], []).append(edge["a"])
            if edge.get("status") == "estimated":
                estimated_parent_edges.add((edge["a"], edge["b"]))
    return parent_of, estimated_parent_edges


# through; a state object would add a type for one use
# lucidlint: ignore long-param-list a single call site — the routing state (families/fam_notes/counter) is threaded
def _route_children(
    parent_of: dict[str, list[str]],
    fam_of_pair: dict[tuple[str, str], str],
    families: list[dict[str, Any]],
    fam_notes: dict[str, list[str]],
    counter: int,
    estimated_parent_edges: set[tuple[str, str]],
    archive: Archive,
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, list[str]], int]:
    """Route each child to its attested co-parents' FAM: children by their
    attested co-parent edge — never by a parent's current spouse: a
    multi-married parent's earlier marriage's children would be silently
    misattributed to the last spouse (2026-08-06 review). A child with two
    attested parents goes to their FAM (creating it when the parents have
    no spouse edge); one parent edge falls back to a single-parent FAM.
    Returns (children_of, single_parent, fam_notes, counter)."""
    children_of: dict[str, list[str]] = {}
    single_parent: dict[str, list[str]] = {}
    for child, parents in sorted(parent_of.items()):
        uniq = sorted(set(parents))
        if len(uniq) == 2:
            pair = (uniq[0], uniq[1])
            if pair in fam_of_pair:
                children_of.setdefault(fam_of_pair[pair], []).append(child)
            else:
                counter += 1
                fid = f"F{counter}"
                fam_of_pair[pair] = fid
                families.append({"id": fid, "a": pair[0], "b": pair[1], "children": [child]})
                # the child that created this FAM is also routed via
                # children_of — the final reset below must not clobber it
                # (2026-08-06 review: a child of an unmarried pair vanished)
                children_of.setdefault(fid, []).append(child)
                if any((parent, child) in estimated_parent_edges for parent in uniq):
                    # concatenate — a spouse estimate's evidence must not be
                    # overwritten by the parent edge's (R9; 2026-08-11 review)
                    fam_notes.setdefault(fid, []).extend(
                        _estimate_note(_estimate_basis(archive, child) or _estimate_basis(archive, uniq[0]))
                    )
        else:
            single_parent.setdefault(uniq[0], []).append(child)
    return children_of, single_parent, fam_notes, counter


# a state object would add a type for one use
# lucidlint: ignore long-param-list a single call site — the FAM state (families/fam_notes/counter) is threaded through;
def _single_parent_families(
    single_parent: dict[str, list[str]],
    estimated_parent_edges: set[tuple[str, str]],
    families: list[dict[str, Any]],
    fam_notes: dict[str, list[str]],
    counter: int,
    archive: Archive,
) -> tuple[list[dict[str, Any]], dict[str, list[str]], int]:
    """The single-parent FAM records — the children whose other parent is
    unconfirmed — with the estimated edges' evidence notes appended
    (concatenate — never overwrite a spouse estimate's evidence, R9;
    2026-08-11 review)."""
    for parent in sorted(single_parent):
        counter += 1
        fid = f"F{counter}"
        families.append({"id": fid, "a": parent, "b": None, "children": sorted(set(single_parent[parent]))})
        if any((parent, child) in estimated_parent_edges for child in single_parent[parent]):
            fam_notes.setdefault(fid, []).extend(
                _estimate_note(_estimate_basis(archive, single_parent[parent][0]) or _estimate_basis(archive, parent))
            )
    return families, fam_notes, counter


def _family_lines(
    fam: dict[str, Any], by_id: dict[str, dict[str, Any]], xref: dict[str, str], fam_notes: dict[str, list[str]]
) -> list[str]:
    """The GEDCOM lines for one FAM record."""
    lines = [f"0 @{fam['id']}@ FAM"]
    lines.append(f"1 {_role(by_id[fam['a']], 0)} @{xref[fam['a']]}@")
    if fam["b"] is not None:
        lines.append(f"1 {_role(by_id[fam['b']], 1)} @{xref[fam['b']]}@")
    if fam.get("marriage"):
        # a dated spouse edge exports as a MARR event — the date is
        # attested data, never dropped on export (2026-08-06 review)
        marriage = fam["marriage"]
        lines.append("1 MARR")
        date_payload = gedcom_date(marriage["date"], marriage.get("precision", "exact"), marriage.get("date2"))
        lines.append(f"2 DATE {date_payload}")
    lines += [f"1 CHIL @{xref[c]}@" for c in fam["children"]]
    lines += fam_notes.get(fam["id"], [])  # an estimated edge's evidence (2026-08-09, user)
    return lines


def _story_notes(archive: Archive, exported_ids: set[str]) -> dict[str, list[str]]:
    """The catalogued stories' verbatim text as NOTES on each exported
    person they reference (the shoehorn)."""
    notes_by_person: dict[str, list[str]] = {}
    for story in resolved_items(archive):
        if story.get("type") != "story" or story.get("status") != "catalogued":
            continue
        text = str(story.get("story") or "").strip()
        if not text:
            continue
        for ref in story.get("people") or []:
            rid = ref.get("id")
            if rid in exported_ids:
                notes_by_person.setdefault(rid, []).append(text)
    return notes_by_person


def _associations(edges: list[dict[str, Any]], archive: Archive) -> dict[str, list[tuple[str, str, list[str]]]]:
    """The non-family edges (sibling/inlaw/teacher) as ASSO records keyed
    by the subject person; an estimated edge's evidence attaches to the
    association, not the person (2026-08-11 review)."""
    associations: dict[str, list[tuple[str, str, list[str]]]] = {}
    for edge in edges:
        if edge["kind"] in ("sibling", "inlaw", "teacher"):
            note = (
                # level 2: the evidence attaches to THIS association, not the
                # person (2026-08-11 review)
                _estimate_note(_estimate_basis(archive, edge["b"]) or _estimate_basis(archive, edge["a"]), level=2)
                if edge.get("status") == "estimated"
                else []
            )
            associations.setdefault(edge["a"], []).append((edge["b"], edge["kind"], note))
    return associations


# a type for one use
# lucidlint: ignore long-param-list a single call site (export_gedcom's per-person loop) — a parameter object would add
def _person_lines(
    person: dict[str, Any],
    pid: str,
    xref: dict[str, str],
    place_names: dict[str, str],
    notes: list[str],
    associations: list[tuple[str, str, list[str]]],
    archive: Archive,
) -> list[str]:
    """The GEDCOM lines for one INDI record."""
    lines = [f"0 @{xref[pid]}@ INDI"]
    lines.append(f"1 REFN {pid}")  # the archive id — the round-trip seam for the importer
    lines.append(f"1 NAME {person['name']}")
    lines += [f"1 NAME {alias}" for alias in person.get("aliases") or []]
    if person.get("dob"):
        dob = person["dob"]
        lines += ["1 BIRT", f"2 DATE {gedcom_date(dob['date'], dob.get('precision', 'exact'), dob.get('date2'))}"]
    if person.get("dod"):
        dod = person["dod"]
        lines += ["1 DEAT", f"2 DATE {gedcom_date(dod['date'], dod.get('precision', 'exact'), dod.get('date2'))}"]
    lines += [f"1 OCCU {occupation}" for occupation in person.get("occupations") or []]
    lines += _residence_lines(person, place_names)
    for note in sorted(set(notes)):
        lines += _lines(note)
    if person.get("status") == "estimated":
        # the estimate's evidence rides on the person — their own words,
        # who said them, and when (2026-08-09, user)
        lines += _estimate_note(person.get("basis") or _estimate_basis(archive, pid))
    lines += _association_lines(associations, xref)
    return lines


def _residence_lines(person: dict[str, Any], place_names: dict[str, str]) -> list[str]:
    """The person's RESI event lines — a proposed residence never leaves
    the archive; the place name resolves from the export's place set."""
    lines: list[str] = []
    for residence in person.get("residence") or []:
        if residence.get("status") == "proposed":
            continue  # nothing unconfirmed leaves the archive
        lines += ["1 RESI", f"2 DATE FROM {residence.get('from', '')} TO {residence.get('to', '')}"]
        place = residence.get("place")
        if place in place_names:
            lines.append(f"2 PLAC {place_names[place]}")
    return lines


def _association_lines(associations: list[tuple[str, str, list[str]]], xref: dict[str, str]) -> list[str]:
    """The ASSO record lines for one person's non-family edges (sibling /
    in-law / teacher) — an estimated edge's evidence rides the association
    (2026-08-11 review)."""
    lines: list[str] = []
    for other, kind, note in sorted(associations):
        label = "in-law" if kind == "inlaw" else kind
        lines += [f"1 ASSO @{xref[other]}@", f"2 RELA {label}"] + note
    return lines


MONTH_NUMBERS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

_QUALIFIER = re.compile(r"^(ABT|EST|CAL|BEF|AFT)\s+(.+)$")
_BETWEEN = re.compile(r"^BET\s+(.+)\s+AND\s+(.+)$")
_PERIOD = re.compile(r"^FROM\s+(.+)\s+TO\s+(.+)$")
_INTERPRETED = re.compile(r"^INT\s+(.+?)\s*\((.+)\)$")


def parse_gedcom_date(payload: str) -> dict[str, str]:
    """A GEDCOM 7 DATE payload -> our {date, date2?, precision} shape."""
    payload = payload.strip()
    m = _QUALIFIER.match(payload)
    if m:
        qualifier, rest = m.group(1), m.group(2)
        precision = {"ABT": "approx", "EST": "approx", "CAL": "approx", "BEF": "before", "AFT": "after"}[qualifier]
        return {"date": _iso(rest), "precision": precision}
    m = _BETWEEN.match(payload)
    if m:
        return {"date": _iso(m.group(1)), "date2": _iso(m.group(2)), "precision": "between"}
    m = _PERIOD.match(payload)
    if m:
        return {"date": _iso(m.group(1)), "date2": _iso(m.group(2)), "precision": "between"}
    m = _INTERPRETED.match(payload)
    if m:
        return {"date": _iso(m.group(1)), "precision": "approx"}
    if payload.startswith("(") and payload.endswith(")"):
        return {"date": "", "precision": "approx"}
    return {"date": _iso(payload), "precision": "exact"}


def _iso(value: str) -> str:
    """'7 JAN 1871' -> '1871-01-07'; 'JAN 1871' -> '1871-01'; '1871' stays."""
    value = value.strip()
    parts = value.split()
    if len(parts) == DAY_MONTH_YEAR_PARTS and parts[1].upper() in MONTH_NUMBERS:
        return f"{parts[2]}-{MONTH_NUMBERS[parts[1].upper()]:02d}-{int(parts[0]):02d}"
    if len(parts) == 2 and parts[0].upper() in MONTH_NUMBERS:
        return f"{parts[1]}-{MONTH_NUMBERS[parts[0].upper()]:02d}"
    return value


def import_gedcom(text: str, places: list[dict[str, Any]]) -> dict[str, Any]:
    """GEDCOM 7.0 text -> archive wire shapes: people (id from REFN),
    relationships (FAM -> spouse/parent, ASSO -> sibling/inlaw/teacher),
    residence place ids matched by name. Deterministic: sorted output."""
    records = gedcom7.loads(text)
    place_ids = {str(p.get("name", "")).strip(): p["id"] for p in places}

    people, associations, xref_to_refn = _parse_people(records, place_ids)
    families = _parse_families(records)
    edges = _build_edges(families, associations)

    def refn(xref: str) -> str:
        return xref_to_refn.get(xref, xref)

    relationships = sorted(
        (
            {"a": refn(e["a"]), "b": refn(e["b"]), "kind": e["kind"]} | ({"date": e["date"]} if e.get("date") else {})
            for e in edges
            if refn(e["a"]) in people and refn(e["b"]) in people
        ),
        key=lambda e: (e["a"], e["kind"], e["b"]),
    )
    return {"people": sorted(people.values(), key=lambda p: p["id"]), "relationships": relationships}


def _parse_people(
    records: list[Any], place_ids: dict[str, str]
) -> tuple[dict[str, dict[str, Any]], dict[str, list[tuple[str, str]]], dict[str, str]]:
    """The INDI records -> (people, associations, xref_to_refn): each
    person's REFN is its archive id (the round-trip seam for the exporter),
    with NAME aliases beyond the first, BIRT/DEAT dates, occupations,
    residence events and ASSO edges keyed by the record's xref."""
    people: dict[str, dict[str, Any]] = {}
    associations: dict[str, list[tuple[str, str]]] = {}
    xref_to_refn: dict[str, str] = {}
    for record in records:
        if record.tag != "INDI":
            continue
        person, assoc_edges = _parse_person(record, place_ids)
        # per-xref bucket append — a setdefault group-by; a comprehension would
        # need a side-effecting expression or an O(n²) rescan
        # lucidlint: ignore loop-pipeline setdefault group-by, not a pure collection build
        for other, kind in assoc_edges:
            associations.setdefault(record.xref, []).append((other, kind))
        if person["id"]:
            xref_to_refn[record.xref] = person["id"]
            people[person["id"]] = person
    return people, associations, xref_to_refn


def _parse_person(record: Any, place_ids: dict[str, str]) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """One INDI record -> the person's wire shape (id from REFN, aliases
    beyond the first, BIRT/DEAT dates, occupations, residence events with
    place ids matched by name) plus its ASSO edges (other-xref, kind)."""
    person: dict[str, Any] = {"id": "", "name": "", "aliases": [], "status": "confirmed"}
    assoc_edges: list[tuple[str, str]] = []
    for child in record.children:
        if child.tag == "REFN":
            person["id"] = child.text.strip()
        elif child.tag == "NAME":
            text_value = child.text.strip()
            if not person["name"]:
                person["name"] = text_value
            elif text_value and text_value not in person["aliases"]:
                person["aliases"].append(text_value)
        elif child.tag == "BIRT":
            person["dob"] = _fact_date(child)
        elif child.tag == "DEAT":
            person["dod"] = _fact_date(child)
        elif child.tag == "OCCU" and child.text.strip():
            person.setdefault("occupations", []).append(child.text.strip())
        elif child.tag == "RESI":
            person.setdefault("residence", []).append(_residence(child, place_ids))
        elif child.tag == "ASSO":
            assoc_edges.append((child.pointer, _rela_kind(child)))
    return person, assoc_edges


def _parse_families(records: list[Any]) -> list[dict[str, Any]]:
    """The FAM records -> wire families: spouse members, children, and a
    dated marriage survives the round-trip (2026-08-06)."""
    families: list[dict[str, Any]] = []
    for record in records:
        if record.tag != "FAM":
            continue
        members = {c.tag: c.pointer for c in record.children if c.tag in ("HUSB", "WIFE")}
        children = [c.pointer for c in record.children if c.tag == "CHIL"]
        marriage = None
        for child in record.children:
            if child.tag == "MARR":
                marriage = _fact_date(child)
        families.append({**members, "children": children, "marriage": marriage})
    return families


def _build_edges(
    families: list[dict[str, Any]], associations: dict[str, list[tuple[str, str]]]
) -> list[dict[str, str]]:
    """The FAM and ASSO records -> archive relationship edges: a two-parent
    FAM is a spouse edge (a dated marriage rides it, 2026-08-06), each
    child gets a parent edge per member, and every ASSO becomes a
    sibling/inlaw/teacher edge."""
    edges: list[dict[str, str]] = []
    for fam in families:
        if "HUSB" in fam and "WIFE" in fam:
            edge: dict[str, str] = {"a": fam["HUSB"], "b": fam["WIFE"], "kind": "spouse"}
            if fam.get("marriage"):
                edge["date"] = fam["marriage"]
            edges.append(edge)
        parents = [fam.get("HUSB"), fam.get("WIFE")]
        parents = [p for p in parents if p]
        edges.extend({"a": parent, "b": child, "kind": "parent"} for child in fam["children"] for parent in parents)
    edges.extend({"a": xref, "b": other, "kind": kind} for xref, rels in associations.items() for other, kind in rels)
    return edges


def _fact_date(record: Any) -> dict[str, str] | None:
    for child in record.children:
        if child.tag == "DATE" and child.text.strip():
            return parse_gedcom_date(child.text)
    return None


def _residence(record: Any, place_ids: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {"from": "", "to": ""}
    for child in record.children:
        if child.tag == "DATE" and child.text.strip():
            m = _PERIOD.match(child.text.strip())
            if m:
                out["from"], out["to"] = m.group(1).strip(), m.group(2).strip()
            else:
                out["from"] = out["to"] = child.text.strip()
        elif child.tag == "PLAC" and child.text.strip():
            # an unknown place is data loss, silently swallowed — surface it
            # (fail loud, 2026-08-06 review: Rule S, unlocatable places get
            # research, never a silent fallback)
            if child.text.strip() not in place_ids:
                raise ValueError(f"GEDCOM RESI names a place not in the archive's place set: {child.text.strip()!r}")
            out["place"] = place_ids[child.text.strip()]
    return out


def _rela_kind(record: Any) -> str:
    for child in record.children:
        if child.tag == "RELA":
            label = child.text.strip().lower()
            return "inlaw" if label == "in-law" else label
    return ""


class GedcomDocument:
    """The GEDCOM 7 interchange format — the archive's portable genealogy.

    The noun for both directions: ``GedcomDocument.from_text`` reads a GEDCOM
    file's people/relationships into archive wire shapes, ``to_text`` writes
    the confirmed genealogy out as GEDCOM 7.0. (``import`` is a Python
    keyword, so the methods are from_text/to_text — the object-model naming
    rule, 2026-08-06.)
    """

    @staticmethod
    def from_text(text: str, places: list[dict[str, Any]]) -> dict[str, Any]:
        """GEDCOM 7.0 text -> archive wire shapes (people, relationships)."""
        return import_gedcom(text, places)

    @staticmethod
    def to_text(archive: Archive) -> str:
        """The confirmed genealogy -> GEDCOM 7.0 text (never proposed data)."""
        return export_gedcom(archive)
