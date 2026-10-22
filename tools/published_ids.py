"""The ids the published projection carries, one set per link kind.

Every link an item carries (people, places, themes, orgs, items) must resolve
in the published projection — a link to an entity the reader cannot see is
dangling. These are the ids the app actually serves: they come from the
published tables, not the archive, so a draft artifact is never a resolution
target.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublishedIds:
    """The published ids of each link kind — a link resolves when its id is
    in the kind's set."""

    people: frozenset[str]
    places: frozenset[str]
    themes: frozenset[str]
    orgs: frozenset[str]
    items: frozenset[str]

    def holds(self, kind: str, record_id: str) -> bool:
        """Whether the published projection of *kind* carries *record_id* —
        an unknown kind (a link kind outside the five) carries nothing, so
        its links never resolve."""
        return record_id in getattr(self, kind, frozenset())
