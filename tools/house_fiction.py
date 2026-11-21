"""The house fiction — a fictional family for examples and fake instances.

Aria, Jack, Meg, Harry, Nora, Lily and Pip Barlow, Mrs Rosa Quinn, and the
towns of Mallowfield and Riverfield. Never a real name, place or fact: the
no-PII guard checks this module against the family's markers
(`tests/test_no_pii_in_repo.py`), and `tests/test_fiction.py` pins the cast's
integrity.

Use these names in fixtures, prompts, eval inputs, docs and a demo instance.
The retired demo command used to seed this cast; the data is kept because
consistency is cheaper than inventing a new family each time.
"""

from __future__ import annotations

from typing import Any, ClassVar


class HouseFiction:
    """The Barlow cast: its people, typed edges and invented geography."""

    PEOPLE: ClassVar[tuple[dict[str, Any], ...]] = (
        {
            "id": "p-aria",
            "name": "Aria Barlow",
            "pronouns": "she/her",
            "aliases": ["Aria", "Gran"],
            "years": "—",
            "relation": "the letter writer",
            "bio": "Wrote weekly letters home for years; kept every reply.",
            "hue": "amber",
        },
        {
            "id": "p-jack",
            "name": "Jack Barlow",
            "pronouns": "he/him",
            "aliases": ["Jack"],
            "years": "—",
            "relation": "the clockmaker",
            "bio": "Repaired clocks and watches at the Mallowfield shop.",
            "hue": "slate",
        },
        {
            "id": "p-meg",
            "name": "Meg Barlow",
            "pronouns": "she/her",
            "aliases": ["Meg", "Mum"],
            "years": "—",
            "relation": "the narrator",
            "bio": "Aria and Jack's daughter. Moved to Riverfield in 1971.",
            "hue": "rose",
        },
        {
            "id": "p-harry",
            "name": "Harry Barlow",
            "aliases": ["Harry"],
            "years": "—",
            "relation": "the boat builder",
            "bio": "Aria and Jack's son; built dinghies at the old yard.",
            "hue": "sky",
        },
        {
            "id": "p-nora",
            "name": "Nora Barlow",
            "pronouns": "she/her",
            "aliases": ["Nora"],
            "years": "—",
            "relation": "Meg's partner",
            "bio": "Ran the village shop with Meg after the move.",
            "hue": "sage",
        },
        {
            "id": "p-lily",
            "name": "Lily Barlow",
            "pronouns": "they/them",
            "aliases": ["Lily"],
            "years": "—",
            "relation": "in the stories",
            "bio": "Meg and Nora's child; remembers the picnics and the school.",
            "hue": "lilac",
        },
        {
            "id": "p-pip",
            "name": "Pip Barlow",
            "aliases": ["Pip"],
            "years": "—",
            "relation": "in the stories",
            "bio": "Meg and Nora's child.",
            "hue": "sky",
        },
        {
            "id": "p-quinn",
            "name": "Mrs Rosa Quinn",
            "aliases": ["Mrs Quinn"],
            "years": "—",
            "relation": "Lily's year-2 teacher",
            "bio": "Taught Lily in year 2 at the village school.",
            "hue": "lilac",
        },
    )

    RELATIONSHIPS: ClassVar[tuple[dict[str, str], ...]] = (
        {"a": "p-aria", "b": "p-jack", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"},
        {"a": "p-aria", "b": "p-meg", "kind": "parent", "label_a": "child", "label_b": "parent"},
        {"a": "p-aria", "b": "p-harry", "kind": "parent", "label_a": "child", "label_b": "parent"},
        {"a": "p-jack", "b": "p-meg", "kind": "parent", "label_a": "child", "label_b": "parent"},
        {"a": "p-jack", "b": "p-harry", "kind": "parent", "label_a": "child", "label_b": "parent"},
        {"a": "p-meg", "b": "p-harry", "kind": "sibling", "label_a": "sibling", "label_b": "sibling"},
        {"a": "p-meg", "b": "p-nora", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"},
        {"a": "p-meg", "b": "p-lily", "kind": "parent", "label_a": "child", "label_b": "parent"},
        {"a": "p-meg", "b": "p-pip", "kind": "parent", "label_a": "child", "label_b": "parent"},
        {"a": "p-nora", "b": "p-lily", "kind": "parent", "label_a": "child", "label_b": "parent"},
        {"a": "p-nora", "b": "p-pip", "kind": "parent", "label_a": "child", "label_b": "parent"},
        {"a": "p-lily", "b": "p-pip", "kind": "sibling", "label_a": "sibling", "label_b": "sibling"},
        {"a": "p-lily", "b": "p-quinn", "kind": "teacher", "label_a": "teacher", "label_b": "student"},
    )

    PLACES: ClassVar[tuple[dict[str, Any], ...]] = (
        {
            "id": "pl-mallowfield",
            "name": "Mallowfield",
            "note": "Where Aria and Jack lived above the clock shop.",
            "x": 42,
            "y": 48,
            "lat": 52.1,
            "lng": -1.4,
            "precision": "town",
        },
        {
            "id": "pl-riverfield",
            "name": "Riverfield",
            "note": "The village Meg and Nora moved to in 1971.",
            "x": 58,
            "y": 55,
            "lat": 52.3,
            "lng": -1.1,
            "precision": "town",
        },
        {
            "id": "pl-the-yard",
            "name": "The old boatyard",
            "note": "Harry's yard on the river — dinghies and skiffs.",
            "x": 61,
            "y": 62,
            "lat": 52.32,
            "lng": -1.05,
            "precision": "town",
        },
        {
            "id": "pl-the-school",
            "name": "The village school",
            "note": "Lily's primary school in Riverfield.",
            "x": 55,
            "y": 50,
            "lat": 52.29,
            "lng": -1.12,
            "precision": "town",
        },
        {
            "id": "pl-the-river",
            "name": "The river",
            "note": "Picnics and first swimming lessons.",
            "x": 63,
            "y": 66,
            "lat": 52.33,
            "lng": -1.02,
            "precision": "region",
        },
    )
