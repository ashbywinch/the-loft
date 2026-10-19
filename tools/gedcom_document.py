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

The island's records are classes, one per type and module
(tools/gedcom_person.py, gedcom_place.py, gedcom_edge.py,
gedcom_family.py, gedcom_date.py, gedcom_residence.py,
gedcom_association.py, gedcom_associations.py), their set and files are
tools/gedcom_shapes.py's, and the stories' notes tools/story_notes.py's.
This module keeps what the GEDCOM 7 TEXT format is: reading records out of
a file, rendering records back into lines (xrefs, notes and record order
are the document's, never one record's), and the export's routing.

Verified by tests parsing the output with gedcom7 (a strict ABNF grammar —
a successful parse IS the standard validation) and by the
tests/fixtures/maximal70.ged round-trip (import -> export -> import
identical on the confirmed subset, both directions).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, final

import gedcom7

from tools.archive import Archive
from tools.gedcom_association import GedcomAssociation
from tools.gedcom_associations import GedcomAssociations
from tools.gedcom_date import PERIOD_RE, GedcomDate
from tools.gedcom_edge import GedcomEdge
from tools.gedcom_family import GedcomFamily
from tools.gedcom_person import GedcomPerson
from tools.gedcom_place import GedcomPlace
from tools.gedcom_residence import GedcomResidence
from tools.gedcom_shapes import GedcomShapes
from tools.projection import resolved_items
from tools.story_notes import StoryNotes


def _lines(text: str, level: int = 1) -> list[str]:
    """Payload text split into GEDCOM lines with CONT continuations — the
    NOTE rides at `level` (1 under an INDI, 2 under an ASSO; a level-1
    note under an association attaches itself to the person instead)."""
    lines = text.splitlines() or [""]
    out = [f"{level} NOTE {lines[0]}"]
    out += [f"{level + 1} CONT {line}" for line in lines[1:]]
    return out


def _estimate_basis(archive: Archive | None, person_id: str) -> dict[str, str] | None:
    """The recorded basis of an estimated link — the review session's
    decision carries the conversation's evidence (who said it, when, their
    own words). Estimated things export WITH the conversation that
    generated them, so the evidence for the estimate is visible (user).
    None for the island (a folder's records carry no review history)."""
    if archive is None:
        return None
    imports = archive.get_identity("imports")
    if imports is None:
        return None
    for imp in imports.imports:
        for attempt in imp.attempts:
            for decision in attempt.decisions:
                if decision.person_id == person_id and decision.decision == "estimated":
                    basis = decision.basis
                    if basis and basis.get("text"):
                        # the review's own words: every value the decision
                        # states is text (the note renders it verbatim)
                        return {str(key): str(value) for key, value in basis.items()}
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
    edges: tuple[GedcomEdge, ...]
    place_names: dict[str, str]
    by_id: dict[str, GedcomPerson]
    xref: dict[str, str]


def _export_set(shapes: GedcomShapes) -> _ExportSet:
    """The confirmed/estimated people and edges that leave the archive —
    proposed records stay out (2026-08-09 review) — plus the lookup maps:
    exported ids, edges, place names, people by id, and the deterministic
    xref ids (sorted order, documented mapping)."""
    exported = tuple(person for person in shapes.people if person.status in (None, "confirmed", "estimated"))
    exported_ids = {person.id for person in exported}
    edges = tuple(
        edge
        for edge in shapes.relationships
        if edge.a in exported_ids
        and edge.b in exported_ids
        and edge.status in (None, "confirmed", "estimated")  # proposed edges stay out too (2026-08-09 review)
    )
    place_names = {place.id: place.name for place in shapes.places}
    by_id = {person.id: person for person in exported}
    xref = {pid: f"P{i}" for i, pid in enumerate(sorted(exported_ids), start=1)}
    return _ExportSet(exported_ids, edges, place_names, by_id, xref)


class _FamilyUnits:
    """The FAM record builder — the routing state the spouse-pair and
    single-parent passes thread through (families, the notes that ride them,
    the id counter, the pair lookup) is one object's state, the passes are its
    methods. The five module functions that used to thread 12 structures
    through 'archive' are this class's machinery."""

    def __init__(self, edges: tuple[GedcomEdge, ...], archive: Archive | None) -> None:
        self._edges = edges
        self._archive = archive
        self._pairs: set[tuple[str, str]] = set()
        self._marriage_dates: dict[tuple[str, str], GedcomDate] = {}
        self._pair_notes: dict[tuple[str, str], list[str]] = {}
        self._families: list[GedcomFamily] = []
        self._fam_notes: dict[str, list[str]] = {}
        self._fam_of_pair: dict[tuple[str, str], str] = {}
        self._parent_of: dict[str, list[str]] = {}
        self._estimated_parent_edges: set[tuple[str, str]] = set()
        self._children_of: dict[str, list[str]] = {}
        self._single_parent: dict[str, list[str]] = {}
        self._counter = 0

    def build(self) -> tuple[GedcomFamily, ...]:
        """The FAM records: spouse pairs + their children, then single-parent
        FAMS — each carrying the evidence notes of the estimated edges that
        created it."""
        self._spouse_pairs()
        self._pair_families()
        self._parent_edges()
        self._route_children()
        paired = tuple(
            replace(fam, children=tuple(sorted(set(self._children_of.get(fam.id, []))))) for fam in self._families
        )
        families = paired + self._single_parent_families()
        return tuple(replace(fam, notes=tuple(self._fam_notes.get(fam.id, []))) for fam in families)

    def _spouse_pairs(self) -> None:
        """The spouse edges -> the sorted pairs, their marriage dates, and
        the evidence notes for estimated pairs."""
        for edge in self._edges:
            if edge.kind != "spouse":
                continue
            a, b = edge.a, edge.b
            pair = (a, b) if a < b else (b, a)
            self._pairs.add(pair)
            if edge.date is not None:
                self._marriage_dates[pair] = edge.date  # a dated marriage exports as 1 MARR (2026-08-06)
            if edge.status == "estimated":
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
            self._families.append(GedcomFamily(id=fid, a=pair[0], b=pair[1], marriage=self._marriage_dates.get(pair)))
            if pair in self._pair_notes:
                self._fam_notes.setdefault(fid, []).extend(self._pair_notes[pair])

    def _parent_edges(self) -> None:
        """The parent edges -> child -> parents, and the estimated
        (parent, child) pairs whose evidence rides the FAM."""
        for edge in self._edges:
            if edge.kind != "parent":
                continue
            self._parent_of.setdefault(edge.b, []).append(edge.a)
            if edge.status == "estimated":
                # (parent, child) — the evidence rides the FAM
                self._estimated_parent_edges.add((edge.a, edge.b))

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
                    self._families.append(GedcomFamily(id=fid, a=pair[0], b=pair[1], children=(child,)))
                    # the child that created this FAM is also routed via
                    # children_of — the final reset below must not clobber it
                    # (2026-08-06 review: a child of an unmarried pair vanished)
                    self._children_of.setdefault(fid, []).append(child)
                    if any((parent, child) in self._estimated_parent_edges for parent in uniq):
                        # concatenate — a spouse estimate's evidence must not be
                        # overwritten by the parent edge's (R9; 2026-08-11 review)
                        self._fam_notes.setdefault(fid, []).extend(
                            _estimate_note(
                                _estimate_basis(self._archive, child) or _estimate_basis(self._archive, uniq[0])
                            )
                        )
            else:
                self._single_parent.setdefault(uniq[0], []).append(child)

    def _single_parent_families(self) -> tuple[GedcomFamily, ...]:
        """The single-parent FAM records — the children whose other parent
        is unconfirmed — with the estimated edges' evidence notes appended
        (concatenate — never overwrite a spouse estimate's evidence, R9;
        2026-08-11 review)."""
        families: list[GedcomFamily] = []
        for parent in sorted(self._single_parent):
            self._counter += 1
            fid = f"F{self._counter}"
            families.append(
                GedcomFamily(id=fid, a=parent, b=None, children=tuple(sorted(set(self._single_parent[parent]))))
            )
            if any((parent, child) in self._estimated_parent_edges for child in self._single_parent[parent]):
                self._fam_notes.setdefault(fid, []).extend(
                    _estimate_note(
                        _estimate_basis(self._archive, self._single_parent[parent][0])
                        or _estimate_basis(self._archive, parent)
                    )
                )
        return tuple(families)


def _family_lines(fam: GedcomFamily, by_id: dict[str, GedcomPerson], xref: dict[str, str]) -> list[str]:
    """The GEDCOM lines for one FAM record."""
    lines = [f"0 @{fam.id}@ FAM"]
    if fam.a is not None:
        lines.append(f"1 {by_id[fam.a].role(0)} @{xref[fam.a]}@")
    if fam.b is not None:
        lines.append(f"1 {by_id[fam.b].role(1)} @{xref[fam.b]}@")
    if fam.marriage is not None:
        # a dated spouse edge exports as a MARR event — the date is
        # attested data, never dropped on export
        lines.append("1 MARR")
        lines.append(f"2 DATE {fam.marriage.payload()}")
    lines += [f"1 CHIL @{xref[child]}@" for child in fam.children]
    lines += list(fam.notes)  # an estimated edge's evidence (user)
    return lines


def _story_notes(archive: Archive, exported_ids: set[str]) -> StoryNotes:
    """The catalogued stories' verbatim text as NOTES on each exported
    person they reference (the shoehorn)."""
    notes = StoryNotes()
    for story in resolved_items(archive):
        if story.type != "story" or story.status != "catalogued":
            continue
        text = str(story.raw.get("story") or "").strip()
        if not text:
            continue
        # lucidlint: ignore loop-pipeline the notes index is built by a side-effecting add(), not a pure collection
        for ref in story.people_refs:
            if ref.id in exported_ids:
                notes.add(ref.id, text)
    return notes


def _associations(edges: tuple[GedcomEdge, ...], archive: Archive | None) -> GedcomAssociations:
    """The non-family edges (sibling/inlaw/teacher) as ASSO records keyed
    by the subject person; an estimated edge's evidence attaches to the
    association, not the person."""
    associations = GedcomAssociations()
    for edge in edges:
        if edge.kind in ("spouse", "parent"):
            continue
        note = (
            # level 2: the evidence attaches to THIS association, not the
            # person
            _estimate_note(_estimate_basis(archive, edge.b) or _estimate_basis(archive, edge.a), level=2)
            if edge.status == "estimated"
            else []
        )
        associations.add(GedcomAssociation(subject=edge.a, other=edge.b, kind=edge.kind, note=tuple(note)))
    return associations


def _event_date_lines(lines: list[str], date: GedcomDate | None, tag: str) -> None:
    """The BIRT/DEAT event and its DATE payload — emitted only when the
    record states a date."""
    if date is not None:
        lines += [f"1 {tag}", f"2 DATE {date.payload()}"]


# a type for one use
# lucidlint: ignore long-param-list a single call site (the export's per-person loop) — a parameter object would add
def _person_lines(
    person: GedcomPerson,
    pid: str,
    xref: dict[str, str],
    place_names: dict[str, str],
    notes: tuple[str, ...],
    associations: tuple[GedcomAssociation, ...],
    archive: Archive | None,
) -> list[str]:
    """The GEDCOM lines for one INDI record."""
    lines = [f"0 @{xref[pid]}@ INDI"]
    lines.append(f"1 REFN {pid}")  # the archive id — the round-trip seam for the importer
    lines.append(f"1 NAME {person.name}")
    lines += [f"1 NAME {alias}" for alias in person.aliases]
    _event_date_lines(lines, person.dob, "BIRT")
    _event_date_lines(lines, person.dod, "DEAT")
    lines += [f"1 OCCU {occupation}" for occupation in person.occupations]
    lines += _residence_lines(person.residence, place_names)
    for note in sorted(set(notes)):
        lines += _lines(note)
    if person.status == "estimated":
        # the estimate's evidence rides on the person — their own words,
        # who said them, and when (user)
        lines += _estimate_note(person.basis or _estimate_basis(archive, pid))
    lines += _association_lines(associations, xref)
    return lines


def _residence_lines(residence: tuple[GedcomResidence, ...], place_names: dict[str, str]) -> list[str]:
    """The person's RESI event lines — a pending/proposed residence never
    leaves; the DATE line only when the residence has dates (a bare RESI
    is legal); the place is the NAME as given (an archive residence's id
    resolves through the export's place set); any note rides along."""
    lines: list[str] = []
    for entry in residence:
        if entry.status in ("pending", "proposed"):
            continue  # nothing unconfirmed leaves the archive
        lines.append("1 RESI")
        if entry.from_ and entry.to:
            lines.append(f"2 DATE FROM {entry.from_} TO {entry.to}")
        elif entry.from_:
            # a one-sided residence: emit the side that exists — never a
            # dangling 'TO ' (review-bot finding on PR #61)
            lines.append(f"2 DATE FROM {entry.from_}")
        elif entry.to:
            lines.append(f"2 DATE TO {entry.to}")
        if entry.place:
            lines.append(f"2 PLAC {place_names.get(entry.place, entry.place)}")
        if entry.note:
            lines += _lines(entry.note, level=2)
    return lines


def _association_lines(associations: tuple[GedcomAssociation, ...], xref: dict[str, str]) -> list[str]:
    """The ASSO record lines for one person's non-family edges (sibling /
    in-law / teacher) — an estimated edge's evidence rides the
    association."""
    lines: list[str] = []
    for association in sorted(associations, key=lambda record: (record.other, record.kind, record.note)):
        label = "in-law" if association.kind == "inlaw" else association.kind
        lines += [f"1 ASSO @{xref[association.other]}@", f"2 RELA {label}"] + list(association.note)
    return lines


@dataclass(frozen=True)
class _People:
    """The parsed people state — named fields instead of a positional
    tuple (the call site reads every name)."""

    by_id: dict[str, GedcomPerson]
    associations: GedcomAssociations
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
    names.update(child.text.strip() for child in node.children if child.tag == "PLAC" and child.text.strip())
    for child in node.children:
        _collect_place_payloads(child, names)


def _fact_date(record: Any) -> GedcomDate | None:
    """The event record's own DATE payload as a date record, when it
    states one."""
    for child in record.children:
        if child.tag == "DATE" and child.text.strip():
            return GedcomDate.from_payload(child.text)
    return None


def _residence(record: Any) -> GedcomResidence:
    """One RESI record -> the residence record: the place NAME as given —
    never a link to a Place — the dates, and any NOTE text. An
    unlocatable place is only text now; the invented unknown-place
    ValueError is gone."""
    from_: str = ""
    to: str = ""
    place: str = ""
    note: str | None = None
    for child in record.children:
        if child.tag == "DATE" and child.text.strip():
            period = PERIOD_RE.match(child.text.strip())
            if period:
                from_, to = period.group(1).strip(), period.group(2).strip()
            else:
                from_ = to = child.text.strip()
        elif child.tag == "PLAC" and child.text.strip():
            place = child.text.strip()
        elif child.tag == "NOTE" and child.text and not note:
            note = child.text.strip()
    return GedcomResidence(from_=from_, to=to, place=place, note=note)


def _rela_kind(record: Any) -> str:
    """The ASSO's kind: GEDCOM 7 uses ROLE, the earlier form RELA — read
    both, map 'in-law' to the archive's 'inlaw'."""
    for child in record.children:
        if child.tag in ("ROLE", "RELA") and child.text.strip():
            label = child.text.strip().lower()
            return "inlaw" if label == "in-law" else label
    return ""


def _associations_of(record: Any) -> tuple[GedcomAssociation, ...]:
    """One INDI record's ASSO children as association records (the other
    record's xref and the role/rela label) — the person's non-family
    edges."""
    return tuple(
        GedcomAssociation(subject=record.xref, other=child.pointer, kind=_rela_kind(child))
        for child in record.children
        if child.tag == "ASSO"
    )


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

    def __init__(self, shapes: GedcomShapes, *, archive: Archive | None = None) -> None:
        self._shapes = shapes
        self._records: list[Any] = []  # the parsed GEDCOM state (shape-built documents carry none)
        self._archive = archive  # the archive-only note sources (stories, estimate evidence)

    @classmethod
    def from_text(cls, text: str) -> GedcomDocument:
        """GEDCOM 7.0 text -> a document. The file alone is the whole
        state: the document parses INTO ITSELF — the records are its
        state and the wire shapes derive from them; places come from the
        file's own PLAC records and payloads, never from an external
        place set."""
        doc = cls(GedcomShapes())
        doc._records = gedcom7.loads(text)
        doc._shapes = doc._shapes_from_records()
        return doc

    def _shapes_from_records(self) -> GedcomShapes:
        """The document's OWN records -> the island's record set: people (id
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

        relationships = tuple(
            GedcomEdge(a=refn(edge.a), b=refn(edge.b), kind=edge.kind, date=edge.date, status=edge.status)
            for edge in edges
            if refn(edge.a) in people.by_id and refn(edge.b) in people.by_id
        )
        return GedcomShapes(
            people=tuple(people.by_id.values()),
            relationships=relationships,
            places=self._parse_places(),
        )

    def _parse_people(self) -> _People:
        """The INDI + FAM records from the document's own state ->
        _People: each person's first REFN (else the record's xref) is
        its archive id (the round-trip seam for the exporter), with NAME
        aliases beyond the first, BIRT/DEAT dates, occupations,
        residence events and ASSO edges keyed by the record's xref;
        pending FAM xrefs go to the edge-builder."""
        people: dict[str, GedcomPerson] = {}
        associations = GedcomAssociations()
        xref_to_refn: dict[str, str] = {}
        pending_fams: set[str] = set()
        for record in self._records:
            if record.tag == "INDI":
                person = self._parse_person(record)
                # lucidlint: ignore loop-pipeline the add is a side effect of the pass that builds the people map
                for association in _associations_of(record):
                    associations.add(association)
                xref_to_refn[record.xref] = person.id
                people[person.id] = person
            elif record.tag == "FAM" and _is_pending(record):
                pending_fams.add(record.xref)
        return _People(people, associations, xref_to_refn, pending_fams)

    def _parse_person(self, record: Any) -> GedcomPerson:
        """One INDI record -> the person's record (id from the first
        REFN, else the xref; aliases beyond the first NAME; BIRT/DEAT
        dates; occupations; residence events with the place NAME as
        given). A _LOFT_STATUS pending record is marked pending; unmarked
        records are not."""
        person = self._parse_facts(self._parse_identity(record), record)
        return replace(person, status="pending") if _is_pending(record) else person

    @staticmethod
    def _parse_identity(record: Any) -> GedcomPerson:
        """The REFN id and NAME (primary + aliases) — what a person is
        named by (the split keeps _parse_person under the gate)."""
        record_id = record.xref.strip("@")
        name = ""
        aliases: list[str] = []
        refn_seen = False
        for child in record.children:
            if child.tag == "REFN" and not refn_seen:
                record_id = child.text.strip()
                refn_seen = True
            elif child.tag == "NAME":
                text_value = child.text.strip()
                if not name:
                    name = text_value
                elif text_value and text_value not in aliases:
                    aliases.append(text_value)
        return GedcomPerson(id=record_id, name=name, aliases=tuple(aliases))

    @staticmethod
    def _parse_facts(person: GedcomPerson, record: Any) -> GedcomPerson:
        """The life facts the export re-emits: BIRT/DEAT dates,
        occupations, residences (the split keeps _parse_person under the
        gate; the ASSO edges are the person's associations)."""
        dob: GedcomDate | None = None
        dod: GedcomDate | None = None
        occupations: list[str] = []
        residence: list[GedcomResidence] = []
        for child in record.children:
            if child.tag == "BIRT":
                dob = _fact_date(child)
            elif child.tag == "DEAT":
                dod = _fact_date(child)
            elif child.tag == "OCCU" and child.text.strip():
                occupations.append(child.text.strip())
            elif child.tag == "RESI":
                residence.append(_residence(child))
        return replace(person, dob=dob, dod=dod, occupations=tuple(occupations), residence=tuple(residence))

    def _parse_families(self) -> tuple[GedcomFamily, ...]:
        """The FAM records from the document's own state -> family records:
        spouse members, children, and a dated marriage survives the
        round-trip (2026-08-06)."""
        families: list[GedcomFamily] = []
        for record in self._records:
            if record.tag != "FAM":
                continue
            members = {c.tag: c.pointer for c in record.children if c.tag in ("HUSB", "WIFE")}
            children = [c.pointer for c in record.children if c.tag == "CHIL"]
            marriage = None
            for child in record.children:
                if child.tag == "MARR":
                    marriage = _fact_date(child)
            families.append(
                GedcomFamily(
                    id=record.xref,
                    a=members.get("HUSB"),
                    b=members.get("WIFE"),
                    children=tuple(children),
                    marriage=marriage,
                )
            )
        return tuple(families)

    @staticmethod
    def _build_edges(
        families: tuple[GedcomFamily, ...], associations: GedcomAssociations, pending_fams: set[str]
    ) -> tuple[GedcomEdge, ...]:
        """The FAM and ASSO records -> the island's edges: a two-parent FAM
        is a spouse edge (a dated marriage rides it, 2026-08-06), each child
        gets a parent edge per member, and every ASSO becomes an edge of its
        role/rela label. A pending FAM's edges are marked pending."""
        edges: list[GedcomEdge] = []
        for fam in families:
            status = "pending" if fam.id in pending_fams else None
            if fam.a is not None and fam.b is not None:
                edges.append(GedcomEdge(a=fam.a, b=fam.b, kind="spouse", date=fam.marriage, status=status))
            # lucidlint: ignore loop-pipeline each parent edge carries the FAM's pending status — not a pure build
            for child in fam.children:
                for parent in (member for member in (fam.a, fam.b) if member is not None):
                    edges.append(GedcomEdge(a=parent, b=child, kind="parent", status=status))
        edges.extend(
            GedcomEdge(a=association.subject, b=association.other, kind=association.kind)
            for association in associations.records()
        )
        return tuple(edges)

    def _parse_places(self) -> tuple[GedcomPlace, ...]:
        """The file's places from the document's own state -> place
        records: every distinct PLAC payload name anywhere in the file
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
        places: list[GedcomPlace] = []
        for name in sorted(names):
            pid = names_by_id.get(name) or _place_id(name, taken)
            taken.add(pid)
            places.append(GedcomPlace(id=pid, name=name, status="pending" if name in pending else None))
        return tuple(places)

    @classmethod
    def from_archive(cls, archive: Archive) -> GedcomDocument:
        """The archive's identity tables -> a document — the archive
        export path (stories and estimate evidence ride the records)."""
        people = archive.get_identity("people")
        places = archive.get_identity("places")
        if people is None or places is None:
            raise RuntimeError("archive needs people and places identity tables")
        return cls(GedcomShapes.from_archive(people, places), archive=archive)

    @classmethod
    def from_shapes(cls, shapes: GedcomShapes) -> GedcomDocument:
        """A folder's record files (people.json + places.json) -> a
        document — the island export path. Self-contained: no archive
        rides along."""
        return cls(shapes)

    def wire_shapes(self) -> GedcomShapes:
        """The folder's record set from this document's state — the
        island folder's record files (people.json + places.json)."""
        return self._shapes

    def to_text(self) -> str:
        """The confirmed subset as GEDCOM 7.0 text. Confirmed people and
        edges export as facts; ESTIMATED records export too — a human's
        guess is part of the family record — each annotated with a NOTE
        carrying the evidence that produced it (the review conversation's
        recorded basis); PENDING records — the island's _LOFT_STATUS, the
        archive's proposed — stay out (2026-08-09, user)."""
        export = _export_set(self._shapes)
        families = _FamilyUnits(export.edges, self._archive).build()
        notes_by_person = (
            _story_notes(self._archive, export.exported_ids) if self._archive is not None else StoryNotes()
        )
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
        places_out = [place for place in self._shapes.places if place.status not in ("pending", "proposed")]
        for i, place in enumerate(places_out, start=1):
            lines += [f"0 @PL{i}@ PLAC", f"1 REFN {place.id}", f"1 NAME {place.name}"]

        for fam in families:
            lines += _family_lines(fam, export.by_id, export.xref)

        for pid in sorted(export.exported_ids):
            lines += _person_lines(
                person=export.by_id[pid],
                pid=pid,
                xref=export.xref,
                place_names=export.place_names,
                notes=notes_by_person.for_person(pid),
                associations=associations.for_person(pid),
                archive=self._archive,
            )

        lines.append("0 TRLR")
        return "\n".join(lines) + "\n"
