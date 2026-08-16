"""Demo content for fake loft instances — fictional only, never real names
(tests/test_demo_data.py guards it; AGENTS.md). `Archive.create_demo()` seeds
a demo archive from this module, then publishes the projection.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from tools.records import split_content

if TYPE_CHECKING:
    from tools.archive import Archive

# The demo default is a dedicated folder, never the real projection — a bare
# run must not be able to clobber app/data with fictional content (2026-08-04
# review, raised twice; the projection has one writer: tools/publish).
OUT = Path(__file__).resolve().parent.parent / "demo" / "data"

# --------------------------------------------------------------------------
# The demo cast — a fictional family, not anyone's.
# --------------------------------------------------------------------------
PEOPLE: list[dict[str, Any]] = [
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
]

# --------------------------------------------------------------------------
# Demo relationships — typed family edges, same shape as the archive's
# identity table. label_a is what B is to A.
# --------------------------------------------------------------------------
RELATIONSHIPS: list[dict[str, str]] = [
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
]

# --------------------------------------------------------------------------
# Demo places — invented geography (coordinates are plausible, not geocoded
# evidence; this is demo content).
# --------------------------------------------------------------------------
PLACES: list[dict[str, Any]] = [
    {
        "id": "pl-mallowfield",
        "name": "Mallowfield",
        "note": "Where Aria and Jack lived above the clock shop.",
        "x": 42,
        "y": 48,
        "lat": 52.1,
        "lng": -1.4,  # lucidlint: ignore magic-number demo longitude — invented geography data, not a computed constant
        "precision": "town",
    },
    {
        "id": "pl-riverfield",
        "name": "Riverfield",
        "note": "The village Meg and Nora moved to in 1971.",
        "x": 58,
        "y": 55,
        "lat": 52.3,
        "lng": -1.1,  # lucidlint: ignore magic-number demo longitude — invented geography data, not a computed constant
        "precision": "town",
    },
    {
        "id": "pl-the-yard",
        "name": "The old boatyard",
        "note": "Harry's yard on the river — dinghies and skiffs.",
        "x": 61,
        "y": 62,
        "lat": 52.32,
        "lng": -1.05,  # lucidlint: ignore magic-number demo longitude — invented geography data, data, not a constant
        "precision": "town",
    },
    {
        "id": "pl-the-school",
        "name": "The village school",
        "note": "Lily's primary school in Riverfield.",
        "x": 55,
        "y": 50,
        "lat": 52.29,
        "lng": -1.12,  # lucidlint: ignore magic-number demo longitude — invented geography data, data, not a constant
        "precision": "town",
    },
    {
        "id": "pl-the-river",
        "name": "The river",
        "note": "Picnics and first swimming lessons.",
        "x": 63,
        "y": 66,
        "lat": 52.33,
        "lng": -1.02,  # lucidlint: ignore magic-number demo longitude — invented geography data, data, not a constant
        "precision": "region",
    },
]

# --------------------------------------------------------------------------
# Demo themes.
# --------------------------------------------------------------------------
THEMES: list[dict[str, Any]] = [
    {
        "id": "t-the-boats",
        "title": "The boats",
        "subtitle": "Harry's yard and the dinghies",
        "items": [{"id": "object-the-dinghy", "note": "The first dinghy Harry built."}],
    },
    {
        "id": "t-the-shop",
        "title": "The shop",
        "subtitle": "Clocks, then groceries",
        "items": [{"id": "doc-the-receipt", "note": "A receipt from the shop's last year."}],
    },
    {
        "id": "t-the-move",
        "title": "The move",
        "subtitle": "Mallowfield to Riverfield, 1971",
        "items": [{"id": "letter-1971-09-20", "note": "Aria's account of the move."}],
    },
    {
        "id": "t-school-days",
        "title": "School days",
        "subtitle": "Lily's memories",
        "items": [{"id": "story-the-school", "note": "Lily on Mrs Quinn."}],
    },
]

# --------------------------------------------------------------------------
# Demo items — letters, photos, objects, stories. All invented.
# --------------------------------------------------------------------------
LETTERS: tuple[dict[str, Any], ...] = (
    {
        "id": "letter-1963-03-14",
        "type": "letter",
        "title": "The first weeks in the shop",
        "date": "1963-03-14",
        "date_precision": "exact",
        "description": "",
        "story": "A letter with a full transcription.",
        "people": [{"id": "p-aria", "status": "confirmed"}],
        "places": [{"id": "pl-mallowfield", "status": "confirmed"}],
        "themes": [{"id": "t-the-shop", "status": "confirmed"}],
        "source": "Box 1 — Letters",
        "transcription": "Dear Mother, the shop is quiet this week, which suits Jack — he has "
        "taken apart the tall clock twice and put it back better each time. Meg has started "
        "school and came home proud of a drawing of the river.",
        "sensitive": False,
        "status": "catalogued",
        "assets": [
            {"kind": "page", "file": "page-1.svg", "caption": "Page 1"},
            {"kind": "page", "file": "page-2.svg", "caption": "Page 2"},
        ],
        "created": "2026-08-04",
    },
    {
        "id": "letter-1971-09-20",
        "type": "letter",
        "title": "The move",
        "date": "1971-09-20",
        "date_precision": "exact",
        "description": "",
        "story": "A letter with a full transcription.",
        "people": [{"id": "p-aria", "status": "confirmed"}, {"id": "p-meg", "status": "confirmed"}],
        "places": [{"id": "pl-riverfield", "status": "confirmed"}],
        "themes": [{"id": "t-the-move", "status": "confirmed"}],
        "source": "Box 1 — Letters",
        "transcription": "Dear Mother, the move went smoothly. Meg and Nora have the shop "
        "running already, and Harry has promised a dinghy for the summer. The river is "
        "behind the house, which the children think is the whole point.",
        "sensitive": False,
        "status": "catalogued",
        "assets": [
            {"kind": "page", "file": "page-1.svg", "caption": "Page 1"},
            {"kind": "page", "file": "page-2.svg", "caption": "Page 2"},
        ],
        "created": "2026-08-04",
    },
)

PHOTOS: tuple[dict[str, Any], ...] = (
    {
        "id": "photo-picnic",
        "type": "photo",
        "title": "The picnic",
        "date": "1972",
        "date_precision": "approx",
        "description": "A family picnic by the river.",
        "story": "Meg: the summer the children learned to swim.",
        "told_by": "p-meg",
        "people": [{"id": "p-lily", "status": "confirmed"}, {"id": "p-pip", "status": "confirmed"}],
        "places": [{"id": "pl-the-river", "status": "confirmed"}],
        "themes": [],
        "sensitive": False,
        "status": "catalogued",
        "assets": [{"kind": "photo", "file": "picnic.svg", "caption": "By the river"}],
        "created": "2026-08-04",
    },
    {
        "id": "photo-the-boats",
        "type": "photo",
        "title": "The dinghies",
        "date": "1981",
        "date_precision": "approx",
        "description": "Harry's yard in the summer.",
        "story": "",
        "people": [{"id": "p-harry", "status": "confirmed"}],
        "places": [{"id": "pl-the-yard", "status": "confirmed"}],
        "themes": [{"id": "t-the-boats", "status": "confirmed"}],
        "sensitive": False,
        "status": "catalogued",
        "assets": [{"kind": "photo", "file": "boats.svg", "caption": "The yard"}],
        "created": "2026-08-04",
    },
)

OBJECTS: tuple[dict[str, Any], ...] = (
    {
        "id": "object-the-dinghy",
        "type": "object",
        "title": "The first dinghy",
        "date": "1981",
        "date_precision": "approx",
        "description": "The first boat Harry built at the yard.",
        "story": "Still in the family; the children learned to row in her.",
        "provenance": "Built by Harry, 1981.",
        "people": [{"id": "p-harry", "status": "confirmed"}],
        "places": [{"id": "pl-the-yard", "status": "confirmed"}],
        "themes": [{"id": "t-the-boats", "status": "confirmed"}],
        "sensitive": False,
        "status": "catalogued",
        "assets": [{"kind": "photo", "file": "dinghy.svg", "caption": "The dinghy"}],
        "created": "2026-08-04",
    },
    {
        "id": "object-the-yard",
        "type": "object",
        "title": "The yard",
        "date": "1981",
        "date_precision": "approx",
        "description": "The boatyard as it was.",
        "story": "",
        "provenance": "",
        "people": [],
        "places": [{"id": "pl-the-yard", "status": "confirmed"}],
        "themes": [{"id": "t-the-boats", "status": "confirmed"}],
        "sensitive": False,
        "status": "catalogued",
        "assets": [{"kind": "photo", "file": "yard.svg", "caption": "The slipway"}],
        "created": "2026-08-04",
    },
)

DOCUMENTS: tuple[dict[str, Any], ...] = (
    {
        "id": "doc-the-receipt",
        "type": "document",
        "title": "The shop's last receipt",
        "date": "2004",
        "date_precision": "year",
        "description": "A receipt from the shop's final year. Described, not yet located.",
        "story": "",
        "provenance": "",
        "source": "The family's accounts, 2004",
        "people": [{"id": "p-nora", "status": "confirmed"}],
        "places": [{"id": "pl-riverfield", "status": "confirmed"}],
        "themes": [{"id": "t-the-shop", "status": "confirmed"}],
        "transcription": "",
        "sensitive": False,
        "status": "catalogued",
        "assets": [],
        "created": "2026-08-04",
    },
)

STORIES: tuple[dict[str, Any], ...] = (
    {
        "id": "story-the-move",
        "type": "story",
        "title": "The move",
        "date": "1971",
        "date_precision": "year",
        "description": "",
        "story": "The van was too small and the piano went in the front seat. Nora and I "
        "drove the whole way laughing about it.",
        "told_by": "p-meg",
        "source": "Session, 2026-08-04 — demo content",
        "people": [{"id": "p-nora", "status": "confirmed"}],
        "places": [{"id": "pl-riverfield", "status": "confirmed"}],
        "themes": [{"id": "t-the-move", "status": "confirmed"}],
        "sensitive": False,
        "status": "catalogued",
        "assets": [],
        "created": "2026-08-04",
    },
    {
        "id": "story-the-school",
        "type": "story",
        "title": "Mrs Quinn",
        "date": "1978",
        "date_precision": "year",
        "description": "",
        "story": "Mrs Quinn made us read out loud every Friday. I was terrified until I "
        "realised everyone else was too.",
        "told_by": "p-lily",
        "source": "Session, 2026-08-04 — demo content",
        "people": [{"id": "p-quinn", "status": "confirmed"}],
        "places": [{"id": "pl-the-school", "status": "confirmed"}],
        "themes": [{"id": "t-school-days", "status": "confirmed"}],
        "sensitive": False,
        "status": "catalogued",
        "assets": [],
        "created": "2026-08-04",
    },
    {
        "id": "story-the-picnic",
        "type": "story",
        "title": "The picnic",
        "date": "1972",
        "date_precision": "year",
        "description": "",
        "story": "The river was cold and Pip fell in twice on purpose. Gran brought sandwiches and a tart.",
        "told_by": "p-lily",
        "source": "Session, 2026-08-04 — demo content",
        "people": [{"id": "p-aria", "status": "confirmed"}, {"id": "p-pip", "status": "confirmed"}],
        "places": [{"id": "pl-the-river", "status": "confirmed"}],
        "themes": [],
        "sensitive": False,
        "status": "catalogued",
        "assets": [],
        "created": "2026-08-04",
    },
)

ALL_ITEMS: tuple[dict[str, Any], ...] = LETTERS + PHOTOS + OBJECTS + DOCUMENTS + STORIES


def create_demo(archive: Archive) -> None:
    """Seed *archive* with the fictional demo content (identity tables +
    items), ready for ``Archive.publish()`` — the create-demo surface the
    `loft create-demo` command runs."""
    archive.save_identity("people", {"people": PEOPLE, "relationships": RELATIONSHIPS})
    archive.save_identity("places", {"places": PLACES})
    archive.save_identity("themes", {"themes": THEMES})
    items = [dict(it) for it in ALL_ITEMS]
    # PRD §19.2: every story carries kind (audio | text) — demo stories are text
    for it in items:
        if it["type"] == "story":
            it.setdefault("kind", "text")
    for it in items:
        sidecar, content = split_content(it)
        archive.save_item(sidecar, content or None)
    print(f"seeded demo archive ({len(items)} items)")
