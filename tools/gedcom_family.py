"""One FAM record of the GEDCOM interchange: the pair, the children, the marriage.

The family record both directions route through — the export's sorted
spouse pair with its children (``id`` is the FAM xref, F1..), and the
import's HUSB/WIFE members with theirs (``id`` is the record's xref and the
members are INDI xrefs). ``b`` is None for a single-parent FAM — the
children whose other parent is unconfirmed.

It has no wire record of its own: a family never leaves as a record file,
it leaves as GEDCOM lines (gedcom_document.py's ``_family_lines``) and
arrives as GEDCOM lines. ``notes`` is the evidence an estimated edge's
review conversation recorded, which rides the FAM the edge created.
"""

from __future__ import annotations

from dataclasses import dataclass

from tools.gedcom_date import GedcomDate


@dataclass(frozen=True)
class GedcomFamily:
    """One FAM record: the two members, their children, a dated marriage,
    and the notes the export attaches to the family."""

    id: str
    a: str | None = None
    b: str | None = None
    children: tuple[str, ...] = ()
    marriage: GedcomDate | None = None
    notes: tuple[str, ...] = ()
