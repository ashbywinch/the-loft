"""GEDCOM 7.0 interchange (tools/gedcom_document.py): the archive's
genealogy and the GEDCOM island.

The one-to-one mapping (ours -> GEDCOM 7.0), so every departure is a
decision, not an accident (GEDCOM X as the object-model reference,
GEDCOM 7.0 as the interchange target):

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

Excluded by policy: pending people, families, relationships and places
(nothing unconfirmed leaves the archive; the island's `1 _LOFT_STATUS
pending` is the pending marker, unmarked records are not pending),
draft items, organisations (no GEDCOM 7 home), and the archive's
non-genealogy items (memorabilia, testimonies-as-items, the archive's
own layout).

Stated departures: GEDCOM 7 xref ids are alphanumeric, so export ids are
assigned sequentially (P1.., F1.., PL1..) in sorted order — the mapping
to archive ids is this module's order (each exported record carries its
archive id in `1 REFN`, the round-trip seam for the importer); FAM
spouse roles are gendered (HUSB/WIFE) and are assigned from attested
pronouns when present, else positionally — gender is never inferred;
the proposed/confirmed seam, the archive's layout and the non-genealogy
content stay archive-only.

The GEDCOM island (`loft gedcom import|export`, tools/cli.py): an import
parses a file into a self-contained folder of record files (people.json
+ places.json — the same file names as the archive's records, unrelated to the live
archive — no resolution, no linking, all entries created at import,
places included); an export reads such a folder and re-emits the
attested / estimated / pending / delete — with pending as the only
GEDCOM-carried marker; residences hold the place NAME as given, never a
link to a Place.

Verified by tests parsing the output with gedcom7 (a strict ABNF grammar —
a successful parse IS the standard validation) and by the
tests/fixtures/maximal70.ged round-trip (import -> export -> import
identical on the confirmed subset, both directions).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, final

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
    NOTE rides at `level` (1 under an INDI, 2 under an ASSO; a level-1
    note under an association attaches itself to the person instead)."""
    lines = text.splitlines() or [""]
    out = [f"{level} NOTE {lines[0]}"]
    out += [f"{level + 1} CONT {line}" for line in lines[1:]]
    return out


def _role(person: dict[str, Any], position: int) -> str:
    """HUSB/WIFE from attested pronouns when present, else positionally
    (the first of a pair gets HUSB) — gender is never inferred: a
    they/them or unstated person is not forced into either role by
    default."""
    pronouns = str(person.get("pronouns") or "").lower()
    if pronouns.startswith("she"):
        return "WIFE"
    if pronouns.startswith("he"):
        return "HUSB"
    return "HUSB" if position == 0 else "WIFE"


def _estimate_basis(archive: Archive | None, person_id: str) -> dict[str, str] | None:
    """The recorded basis of an estimated link — the review session's
    decision carries the conversation's evidence (who said it, when, their
    own words). Estimated things export WITH the conversation that
    generated them, so the evidence for the estimate is visible (user).
    None for the island (a folder's records carry no review history)."""
    if archive is None:
        return None
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
    (user). The level places the note under its owner: the
    person (1) or the association it evidences (2)."""
    if basis and basis.get("text"):
        by = str(basis.get("by") or "the family")
        when = str(basis.get("when") or "")
        stamp = f" ({when})" if when else ""
        return _lines(f'Estimated — from {by}\'s recollection{stamp}: "{basis["text"]}"', level)
    return _lines("Estimated — the family's recollection; the basis is not recorded", level)


@dataclass(frozen=True)
class _ExportSet:
    """What leaves the archive — the confirmed/estimated people and edges,
    plus the lookup maps the export renders them with: exported ids, edges,
    place names, people by id, and the deterministic xref ids (sorted order,
    documented mapping). Named fields instead of the positional 5-tuple the
    call site could not read."""

    exported_ids: set[str]
    edges: list[dict[str, Any]]
    place_names: dict[str, str]
    by_id: dict[str, dict[str, Any]]
    xref: dict[str, str]


def _export_set(people: dict[str, Any], places: dict[str, Any]) -> _ExportSet:
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
    return _ExportSet(exported_ids, edges, place_names, by_id, xref)


class _FamilyUnits:
    """The FAM record builder — the routing state the spouse-pair and
    single-parent passes thread through (families, fam_notes, the id
    counter, the pair lookup) is one object's state, the passes are its
    methods. The five module functions that used to thread 12 structures
    through 'archive' are this class's machinery."""

    def __init__(self, edges: list[dict[str, Any]], archive: Archive | None) -> None:
        self._edges = edges
        self._archive = archive
        self._pairs: set[tuple[str, str]] = set()
        self._marriage_dates: dict[tuple[str, str], dict[str, str]] = {}
        self._pair_notes: dict[tuple[str, str], list[str]] = {}
        self.families: list[dict[str, Any]] = []
        self.fam_notes: dict[str, list[str]] = {}
        self._fam_of_pair: dict[tuple[str, str], str] = {}
        self._parent_of: dict[str, list[str]] = {}
        self._estimated_parent_edges: set[tuple[str, str]] = set()
        self._children_of: dict[str, list[str]] = {}
        self._single_parent: dict[str, list[str]] = {}
        self._counter = 0

    def build(self) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
        """The FAM records: spouse pairs + their children, then single-parent
        FAMS. Returns (families, fam_notes) — an estimated edge's evidence
        rides on the FAM it created."""
        self._spouse_pairs()
        self._pair_families()
        self._parent_edges()
        self._route_children()
        for fam in self.families:
            fam["children"] = sorted(set(self._children_of.get(fam["id"], [])))
        self._single_parent_families()
        return self.families, self.fam_notes

    def _spouse_pairs(self) -> None:
        """The spouse edges -> the sorted pairs, their marriage dates, and
        the evidence notes for estimated pairs."""
        for edge in self._edges:
            if edge["kind"] == "spouse":
                a, b = edge["a"], edge["b"]
                pair = (a, b) if a < b else (b, a)
                self._pairs.add(pair)
                if edge.get("date"):
                    self._marriage_dates[pair] = edge["date"]  # a dated marriage exports as 1 MARR (2026-08-06)
                if edge.get("status") == "estimated":
                    self._pair_notes[pair] = _estimate_note(
                        _estimate_basis(self._archive, b) or _estimate_basis(self._archive, a)
                    )

    def _pair_families(self) -> None:
        """The spouse-pair FAM records, in sorted-pair order: one FAM per
        pair, keyed by pair for the child routing. The FAM counter is shared
        with the later single-parent records so ids stay assignment-ordered."""
        for pair in sorted(self._pairs):
            self._counter += 1
            fid = f"F{self._counter}"
            self._fam_of_pair[pair] = fid
            self.families.append(
                {"id": fid, "a": pair[0], "b": pair[1], "children": [], "marriage": self._marriage_dates.get(pair)}
            )
            if pair in self._pair_notes:
                self.fam_notes.setdefault(fid, []).extend(self._pair_notes[pair])

    def _parent_edges(self) -> None:
        """The parent edges -> child -> parents, and the estimated
        (parent, child) pairs whose evidence rides the FAM."""
        for edge in self._edges:
            if edge["kind"] == "parent":
                self._parent_of.setdefault(edge["b"], []).append(edge["a"])
                if edge.get("status") == "estimated":
                    # (parent, child) — the evidence rides the FAM
                    self._estimated_parent_edges.add((edge["a"], edge["b"]))

    def _route_children(self) -> None:
        """Route each child to its attested co-parents' FAM: children by
        their attested co-parent edge — never by a parent's current spouse:
        a multi-married parent's earlier marriage's children would be
        silently misattributed to the last spouse (2026-08-06 review). A
        child with two attested parents goes to their FAM (creating it when
        the parents have no spouse edge); one parent edge falls back to a
        single-parent FAM."""
        for child, parents in sorted(self._parent_of.items()):
            uniq = sorted(set(parents))
            if len(uniq) == 2:
                pair = (uniq[0], uniq[1])
                if pair in self._fam_of_pair:
                    self._children_of.setdefault(self._fam_of_pair[pair], []).append(child)
                else:
                    self._counter += 1
                    fid = f"F{self._counter}"
                    self._fam_of_pair[pair] = fid
                    self.families.append({"id": fid, "a": pair[0], "b": pair[1], "children": [child]})
                    # the child that created this FAM is also routed via
                    # children_of — the final reset below must not clobber it
                    # (2026-08-06 review: a child of an unmarried pair vanished)
                    self._children_of.setdefault(fid, []).append(child)
                    if any((parent, child) in self._estimated_parent_edges for parent in uniq):
                        # concatenate — a spouse estimate's evidence must not be
                        # overwritten by the parent edge's (R9; 2026-08-11 review)
                        self.fam_notes.setdefault(fid, []).extend(
                            _estimate_note(
                                _estimate_basis(self._archive, child) or _estimate_basis(self._archive, uniq[0])
                            )
                        )
            else:
                self._single_parent.setdefault(uniq[0], []).append(child)

    def _single_parent_families(self) -> None:
        """The single-parent FAM records — the children whose other parent
        is unconfirmed — with the estimated edges' evidence notes appended
        (concatenate — never overwrite a spouse estimate's evidence, R9;
        2026-08-11 review)."""
        for parent in sorted(self._single_parent):
            self._counter += 1
            fid = f"F{self._counter}"
            self.families.append(
                {"id": fid, "a": parent, "b": None, "children": sorted(set(self._single_parent[parent]))}
            )
            if any((parent, child) in self._estimated_parent_edges for child in self._single_parent[parent]):
                self.fam_notes.setdefault(fid, []).extend(
                    _estimate_note(
                        _estimate_basis(self._archive, self._single_parent[parent][0])
                        or _estimate_basis(self._archive, parent)
                    )
                )


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
        # attested data, never dropped on export
        marriage = fam["marriage"]
        lines.append("1 MARR")
        date_payload = gedcom_date(marriage["date"], marriage.get("precision", "exact"), marriage.get("date2"))
        lines.append(f"2 DATE {date_payload}")
    lines += [f"1 CHIL @{xref[c]}@" for c in fam["children"]]
    lines += fam_notes.get(fam["id"], [])  # an estimated edge's evidence (user)
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


def _associations(edges: list[dict[str, Any]], archive: Archive | None) -> dict[str, list[tuple[str, str, list[str]]]]:
    """The non-family edges (sibling/inlaw/teacher) as ASSO records keyed
    by the subject person; an estimated edge's evidence attaches to the
    association, not the person."""
    associations: dict[str, list[tuple[str, str, list[str]]]] = {}
    for edge in edges:
        if edge["kind"] not in ("spouse", "parent"):
            note = (
                # level 2: the evidence attaches to THIS association, not the
                # person
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
    archive: Archive | None,
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
        # who said them, and when (user)
        lines += _estimate_note(person.get("basis") or _estimate_basis(archive, pid))
    lines += _association_lines(associations, xref)
    return lines


def _residence_lines(person: dict[str, Any], place_names: dict[str, str]) -> list[str]:
    """The person's RESI event lines — a pending/proposed residence never
    leaves; the DATE line only when the residence has dates (a bare RESI
    is legal); the place is the NAME as given (an archive residence's id
    resolves through the export's place set); any note rides along."""
    lines: list[str] = []
    for residence in person.get("residence") or []:
        if residence.get("status") in ("pending", "proposed"):
            continue  # nothing unconfirmed leaves the archive
        lines.append("1 RESI")
        frm, to = residence.get("from", ""), residence.get("to", "")
        if frm and to:
            lines.append(f"2 DATE FROM {frm} TO {to}")
        elif frm:
            # a one-sided residence: emit the side that exists — never a
            # dangling 'TO ' (review-bot finding on PR #61)
            lines.append(f"2 DATE FROM {frm}")
        elif to:
            lines.append(f"2 DATE TO {to}")
        place = residence.get("place")
        if place:
            lines.append(f"2 PLAC {place_names.get(place, place)}")
        note = residence.get("note")
        if note:
            lines += _lines(note, level=2)
    return lines


def _association_lines(associations: list[tuple[str, str, list[str]]], xref: dict[str, str]) -> list[str]:
    """The ASSO record lines for one person's non-family edges (sibling /
    in-law / teacher) — an estimated edge's evidence rides the
    association."""
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


@dataclass(frozen=True)
class _People:
    """The parsed people state — named fields instead of a positional
    tuple (the call site reads every name)."""

    by_id: dict[str, dict[str, Any]]
    associations: dict[str, list[tuple[str, str]]]
    xref_to_refn: dict[str, str]
    pending_fams: set[str]


def _is_pending(record: Any) -> bool:
    """The record carries the pending marker (``1 _LOFT_STATUS pending`` —
    user tags start with _; unmarked records are everything-else)."""
    return any(c.tag == "_LOFT_STATUS" and c.text.strip().lower() == "pending" for c in record.children)


def _collect_place_payloads(node: Any, names: set[str]) -> None:
    """Every PLAC payload below ``node`` lands in ``names`` — a payload
    can sit under RESI, DEAT, MARR, SLGS, SOUR DATA, nested past the
    record's own children."""
    for child in node.children:
        if child.tag == "PLAC" and child.text.strip():
            names.add(child.text.strip())
        _collect_place_payloads(child, names)


def _fact_date(record: Any) -> dict[str, str] | None:
    for child in record.children:
        if child.tag == "DATE" and child.text.strip():
            return parse_gedcom_date(child.text)
    return None


def _residence(record: Any) -> dict[str, str]:
    """One RESI record -> the residence wire shape: the place NAME as
    given — never a link to a Place — the dates, and any NOTE text. An
    unlocatable place is only text now; the invented unknown-place
    ValueError is gone."""
    out: dict[str, str] = {"from": "", "to": "", "place": ""}
    for child in record.children:
        if child.tag == "DATE" and child.text.strip():
            m = _PERIOD.match(child.text.strip())
            if m:
                out["from"], out["to"] = m.group(1).strip(), m.group(2).strip()
            else:
                out["from"] = out["to"] = child.text.strip()
        elif child.tag == "PLAC" and child.text.strip():
            out["place"] = child.text.strip()
        elif child.tag == "NOTE" and child.text and not out.get("note"):
            out["note"] = child.text.strip()
    return out


def _rela_kind(record: Any) -> str:
    """The ASSO's kind: GEDCOM 7 uses ROLE, the earlier form RELA — read
    both, map 'in-law' to the archive's 'inlaw'."""
    for child in record.children:
        if child.tag in ("ROLE", "RELA") and child.text.strip():
            label = child.text.strip().lower()
            return "inlaw" if label == "in-law" else label
    return ""


def _place_id(name: str, taken: set[str]) -> str:
    """A deterministic Place id for a PLAC payload name: the slug, with a
    numeric suffix on collision (ids must be unique within the document)."""
    base = re.sub(r"[^0-9a-z]+", "-", name.lower()).strip("-") or "place"
    pid, n = base, 2
    while pid in taken:
        pid = f"{base}-{n}"
        n += 1
    return pid


@final
class GedcomDocument:
    """The GEDCOM 7 interchange format — a document object holding the
    records.

    ``from_text`` parses a GEDCOM 7 file into this document — the read
    produces archive wire shapes from the document's OWN state
    (``wire_shapes``) — and ``to_text`` re-emits the confirmed subset as
    GEDCOM 7.0; nothing pending leaves. ``from_archive`` builds the
    document from the live archive's identity tables (the archive's
    story notes and estimate evidence ride the records); ``from_shapes``
    from a folder's record files (the GEDCOM island). ``import`` is a
    Python keyword, so the methods are from_text/from_archive — the
    object-model naming rule.
    """

    def __init__(self, shapes: dict[str, Any], *, archive: Archive | None = None) -> None:
        self._records: list[Any] = []  # the parsed GEDCOM state (shape-built documents carry none)
        self._people = sorted(shapes.get("people") or [], key=lambda p: p["id"])
        self._relationships = sorted(
            shapes.get("relationships") or [], key=lambda r: (r["a"], r.get("kind", ""), r["b"])
        )
        self._places = sorted(shapes.get("places") or [], key=lambda p: p["id"])
        self._archive = archive  # the archive-only note sources (stories, estimate evidence)

    @classmethod
    def from_text(cls, text: str) -> GedcomDocument:
        """GEDCOM 7.0 text -> a document. The file alone is the whole
        state: the document parses INTO ITSELF — the records are its
        state and the wire shapes derive from them; places come from the
        file's own PLAC records and payloads, never from an external
        place set."""
        doc = cls({})
        doc._records = gedcom7.loads(text)
        shapes = doc._shapes_from_records()
        doc._people, doc._relationships, doc._places = shapes["people"], shapes["relationships"], shapes["places"]
        return doc

    def _shapes_from_records(self) -> dict[str, Any]:
        """The document's OWN records -> archive wire shapes: people (id
        from the first REFN, else the record's xref — a person without a
        REFN is not dropped, maximal70's I2/I3/I4 have none),
        relationships (FAM -> spouse/parent, ASSO -> the role/rela
        label), places (every distinct PLAC payload name in the file plus
        the PLAC records -> Place entities), residences carrying the
        place NAME as given (no link to a Place). ``1 _LOFT_STATUS
        pending`` marks a person/family/place record pending; unmarked
        records are not pending. Deterministic: sorted output."""
        people = self._parse_people()
        edges = self._build_edges(self._parse_families(), people.associations, people.pending_fams)

        def refn(xref: str) -> str:
            return people.xref_to_refn.get(xref, xref)

        relationships = sorted(
            (
                {"a": refn(e["a"]), "b": refn(e["b"]), "kind": e["kind"]}
                | ({"date": e["date"]} if e.get("date") else {})
                | ({"status": "pending"} if e.get("pending") else {})
                for e in edges
                if refn(e["a"]) in people.by_id and refn(e["b"]) in people.by_id
            ),
            key=lambda e: (e["a"], e["kind"], e["b"]),
        )
        return {
            "people": sorted(people.by_id.values(), key=lambda p: p["id"]),
            "relationships": relationships,
            "places": self._parse_places(),
        }

    def _parse_people(self) -> _People:
        """The INDI + FAM records from the document's own state ->
        _People: each person's first REFN (else the record's xref) is
        its archive id (the round-trip seam for the exporter), with NAME
        aliases beyond the first, BIRT/DEAT dates, occupations,
        residence events and ASSO edges keyed by the record's xref;
        pending FAM xrefs go to the edge-builder."""
        people: dict[str, dict[str, Any]] = {}
        associations: dict[str, list[tuple[str, str]]] = {}
        xref_to_refn: dict[str, str] = {}
        pending_fams: set[str] = set()
        for record in self._records:
            if record.tag == "INDI":
                person, assoc_edges = self._parse_person(record)
                # per-xref bucket append — a setdefault group-by; a comprehension would
                # need a side-effecting expression or an O(n²) rescan
                # lucidlint: ignore loop-pipeline setdefault group-by, not a pure collection build
                for other, kind in assoc_edges:
                    associations.setdefault(record.xref, []).append((other, kind))
                xref_to_refn[record.xref] = person["id"]
                people[person["id"]] = person
            elif record.tag == "FAM" and _is_pending(record):
                pending_fams.add(record.xref)
        return _People(people, associations, xref_to_refn, pending_fams)

    def _parse_person(self, record: Any) -> tuple[dict[str, Any], list[tuple[str, str]]]:
        """One INDI record -> the person's wire shape (id from the first
        REFN, else the xref; aliases beyond the first NAME; BIRT/DEAT
        dates; occupations; residence events with the place NAME as
        given) plus its ASSO edges (other-xref, role/rela label). A
        _LOFT_STATUS pending record is marked pending; unmarked records
        are not."""
        person: dict[str, Any] = {"id": record.xref.strip("@"), "name": "", "aliases": []}
        assoc_edges: list[tuple[str, str]] = []
        self._parse_identity(person, record)
        self._parse_facts(person, assoc_edges, record)
        if _is_pending(record):
            person["status"] = "pending"
        return person, assoc_edges

    def _parse_identity(self, person: dict[str, Any], record: Any) -> None:
        """The REFN id and NAME (primary + aliases) — what a person is
        named by (the split keeps _parse_person under the gate)."""
        refn_seen = False
        for child in record.children:
            if child.tag == "REFN" and not refn_seen:
                person["id"] = child.text.strip()
                refn_seen = True
            elif child.tag == "NAME":
                text_value = child.text.strip()
                if not person["name"]:
                    person["name"] = text_value
                elif text_value and text_value not in person["aliases"]:
                    person["aliases"].append(text_value)

    def _parse_facts(self, person: dict[str, Any], assoc_edges: list[tuple[str, str]], record: Any) -> None:
        """The life facts the export re-emits: BIRT/DEAT dates,
        occupations, residences, ASSO edges (the split keeps
        _parse_person under the gate)."""
        for child in record.children:
            if child.tag == "BIRT":
                person["dob"] = _fact_date(child)
            elif child.tag == "DEAT":
                person["dod"] = _fact_date(child)
            elif child.tag == "OCCU" and child.text.strip():
                person.setdefault("occupations", []).append(child.text.strip())
            elif child.tag == "RESI":
                person.setdefault("residence", []).append(_residence(child))
            elif child.tag == "ASSO":
                assoc_edges.append((child.pointer, _rela_kind(child)))

    def _parse_families(self) -> list[dict[str, Any]]:
        """The FAM records from the document's own state -> wire families:
        spouse members, children, and a dated marriage survives the
        round-trip (2026-08-06)."""
        families: list[dict[str, Any]] = []
        for record in self._records:
            if record.tag != "FAM":
                continue
            members = {c.tag: c.pointer for c in record.children if c.tag in ("HUSB", "WIFE")}
            children = [c.pointer for c in record.children if c.tag == "CHIL"]
            marriage = None
            for child in record.children:
                if child.tag == "MARR":
                    marriage = _fact_date(child)
            families.append({**members, "children": children, "marriage": marriage, "xref": record.xref})
        return families

    def _build_edges(
        self, families: list[dict[str, Any]], associations: dict[str, list[tuple[str, str]]], pending_fams: set[str]
    ) -> list[dict[str, str]]:
        """The FAM and ASSO records -> archive relationship edges: a
        two-parent FAM is a spouse edge (a dated marriage rides it,
        2026-08-06), each child gets a parent edge per member, and every
        ASSO becomes an edge of its role/rela label. A pending FAM's
        edges are marked pending."""
        edges: list[dict[str, str]] = []
        for fam in families:
            pending = fam.get("xref") in pending_fams
            if "HUSB" in fam and "WIFE" in fam:
                edge: dict[str, str] = {"a": fam["HUSB"], "b": fam["WIFE"], "kind": "spouse"}
                if fam.get("marriage"):
                    edge["date"] = fam["marriage"]
                if pending:
                    edge["pending"] = "true"
                edges.append(edge)
            parents = [fam.get("HUSB"), fam.get("WIFE")]
            parents = [p for p in parents if p]
            for child in fam["children"]:
                for parent in parents:
                    edge = {"a": parent, "b": child, "kind": "parent"}
                    if pending:
                        edge["pending"] = "true"
                    edges.append(edge)
        edges.extend(
            {"a": xref, "b": other, "kind": kind} for xref, rels in associations.items() for other, kind in rels
        )
        return edges

    def _parse_places(self) -> list[dict[str, Any]]:
        """The file's places from the document's own state -> Place
        entities: every distinct PLAC payload name anywhere in the file
        (a payload can sit under RESI, DEAT, MARR, SLGS, SOUR DATA —
        nested past the record's own children) plus the PLAC records'
        names. A PLAC record's id rides its REFN (the round-trip seam,
        like people); payload names get a deterministic slug id. A
        pending PLAC record is marked. Sorted by id."""
        names_by_id: dict[str, str] = {}
        names: set[str] = set()
        pending: set[str] = set()
        for record in self._records:
            if record.tag == "PLAC":
                name = next((c.text.strip() for c in record.children if c.tag == "NAME"), "")
                if name:
                    names.add(name)
                    refn = next((c.text.strip() for c in record.children if c.tag == "REFN"), "")
                    if refn:
                        names_by_id[name] = refn
                    if _is_pending(record):
                        pending.add(name)
            _collect_place_payloads(record, names)
        taken: set[str] = set(names_by_id.values())
        places: list[dict[str, Any]] = []
        for name in sorted(names):
            pid = names_by_id.get(name) or _place_id(name, taken)
            taken.add(pid)
            place: dict[str, Any] = {"id": pid, "name": name}
            if name in pending:
                place["status"] = "pending"
            places.append(place)
        return sorted(places, key=lambda p: p["id"])  # id order, like every other record file

    @classmethod
    def from_archive(cls, archive: Archive) -> GedcomDocument:
        """The archive's identity tables -> a document — the archive
        export path (stories and estimate evidence ride the records)."""
        people = archive.get_identity("people")
        places = archive.get_identity("places")
        if people is None or places is None:
            raise RuntimeError("archive needs people and places identity tables")
        return cls(
            {
                "people": people["people"],
                "relationships": people.get("relationships") or [],
                "places": places["places"],
            },
            archive=archive,
        )

    @classmethod
    def from_shapes(cls, shapes: dict[str, Any]) -> GedcomDocument:
        """A folder's record files (people.json + places.json) -> a
        document — the island export path. Self-contained: no archive
        rides along."""
        return cls(shapes)

    def wire_shapes(self) -> dict[str, Any]:
        """The folder's record shapes from this document's state — the
        island folder's record files (people.json + places.json)."""
        return {"people": self._people, "relationships": self._relationships, "places": self._places}

    def to_text(self) -> str:
        """The confirmed subset as GEDCOM 7.0 text. Confirmed people and
        edges export as facts; ESTIMATED records export too — a human's
        guess is part of the family record — each annotated with a NOTE
        carrying the evidence that produced it (the review conversation's
        recorded basis); PENDING records — the island's _LOFT_STATUS, the
        archive's proposed — stay out (2026-08-09, user)."""
        export = _export_set({"people": self._people, "relationships": self._relationships}, {"places": self._places})
        families, fam_notes = _FamilyUnits(export.edges, self._archive).build()
        notes_by_person = _story_notes(self._archive, export.exported_ids) if self._archive is not None else {}
        associations = _associations(export.edges, self._archive)

        lines: list[str] = [
            "0 HEAD",
            "1 SOUR the-loft-export",
            "2 VERS 0.1",
            "1 GEDC",
            "2 VERS 7.0",
            "2 FORM LINEAGE-LINKED",
            "1 CHAR UTF-8",
        ]
        # the places as standalone PLAC records — the round trip: the
        # import's places must be re-emittable; nothing pending leaves
        places_out = [p for p in self._places if p.get("status") not in ("pending", "proposed")]
        for i, place in enumerate(sorted(places_out, key=lambda p: p["id"]), start=1):
            lines += [f"0 @PL{i}@ PLAC", f"1 REFN {place['id']}", f"1 NAME {place['name']}"]

        for fam in families:
            lines += _family_lines(fam, export.by_id, export.xref, fam_notes)

        for pid in sorted(export.exported_ids):
            lines += _person_lines(
                person=export.by_id[pid],
                pid=pid,
                xref=export.xref,
                place_names=export.place_names,
                notes=notes_by_person.get(pid, []),
                associations=associations.get(pid, []),
                archive=self._archive,
            )

        lines.append("0 TRLR")
        return "\n".join(lines) + "\n"
