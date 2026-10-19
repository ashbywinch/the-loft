"""The catalogued stories' verbatim text, as GEDCOM notes on the people they name.

The export's shoehorn: a catalogued story's text becomes a NOTE on each
exported person the story references. The notes are the document's derived
view — the class holds them by person, so the renderer asks for one person's
notes instead of threading a bare mapping through the export.
"""

from __future__ import annotations


class StoryNotes:
    """The stories' text, by the person it rides on."""

    def __init__(self) -> None:
        self._by_person: dict[str, list[str]] = {}

    def add(self, person_id: str, text: str) -> None:
        """Record one story's text against one person it references."""
        self._by_person.setdefault(person_id, []).append(text)

    def for_person(self, person_id: str) -> tuple[str, ...]:
        """The notes one person's INDI record carries — empty for a person
        no story names (the renderer sorts and de-dupes them)."""
        return tuple(self._by_person.get(person_id, ()))
