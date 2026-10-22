"""One ASSO record of the GEDCOM interchange: the other person and the label.

The non-family edge as the person's own association — ``subject`` is the
person the ASSO sits on, ``other`` the person it points at, ``kind`` the
ROLE/RELA label (GEDCOM 7's ROLE, the earlier RELA), and ``note`` the
evidence lines an estimated edge carries (the reviewer's own words, who
said them, and when).

It has no wire record of its own: an association leaves as the relationship
edge it becomes (``GedcomEdge``) and re-emits as ASSO lines
(gedcom_document.py's ``_association_lines``).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GedcomAssociation:
    """One ASSO record: its subject, the other person, the label, and the
    evidence note lines."""

    subject: str
    other: str
    kind: str
    note: tuple[str, ...] = ()
