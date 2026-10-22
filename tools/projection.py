"""The derivation engine — everything computed from the archive's primary
data, in one place (docs/TECHSPEC.md §3): resolved items (highest sidecar,
primary content embedded from its file), identity tables, the index and
transcripts. Publish (batch), import (scan ingest) and the capture server
(site stories) all derive through this module — never a second copy of the
rules. Derived output is regenerable: same archive, same output.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from tools.item_assets import ItemAssets
from tools.placeholders import asset_svg, initials_of, svg_avatar
from tools.projection_index import ProjectionIndex
from tools.published_ids import PublishedIds
from tools.records import (
    CONTENT_FILES,
    ImportsTable,
    Item,
    OrgsTable,
    PeopleTable,
    Person,
    PlacesTable,
    ThemesTable,
)

if TYPE_CHECKING:
    from tools.archive import Archive


class DeriveError(RuntimeError):
    """Raised when the archive cannot be derived (missing identity table, …)."""


def resolved_items(archive: Archive) -> list[Item]:
    """Every live item as the projection publishes it: the highest sidecar,
    tombstoned items gone, primary content (story / transcription) embedded
    from its content file and the content asset entries stripped — the
    projection embeds text, the reader never renders a content file as an
    image. The projection's copy is derived, never re-validated: the sidecar
    was validated at the archive's write seam."""
    items: list[Item] = []
    for item_id in archive.item_ids():
        item = archive.get_item(item_id)
        if item is None:
            continue  # tombstoned — gone from the projection
        raw = dict(item.raw)
        raw.pop("supersedes", None)  # the supersession chain is archive-internal, not projection content
        if not raw.get("chat"):
            raw.pop("chat", None)  # a capture record exists or it doesn't — never an empty field
        assets = list(raw.get("assets") or [])
        for kind in CONTENT_FILES:
            entry = next((a for a in assets if a.get("kind") == kind), None)
            if entry is None:
                continue
            text = archive.read_content(item_id, entry["file"])
            if text is None:
                # a sidecar referencing a content file the archive doesn't
                # have is silent data loss — a partial Drive sync is the
                # realistic trigger (PRD §7); publish fails loudly instead
                # of shipping a blank story/transcription (2026-08-04
                # review, raised 3x)
                raise DeriveError(f"{item_id}: content file {entry['file']} referenced by its sidecar is missing")
            raw[kind] = text
            assets = [a for a in assets if a is not entry]
        # the projection's items carry the content fields per type (the app
        # reads them unconditionally — app/views/stories.js, item.js): story
        # everywhere (descriptions on letters/photos/objects), transcription
        # on stories/letters/documents only
        raw.setdefault("story", "")
        if raw.get("type") in ("story", "letter", "document"):
            raw.setdefault("transcription", "")
        raw["assets"] = assets
        items.append(Item(raw))
    return items


def imports_projection(archive: Archive) -> ImportsTable:
    """The import sessions — empty when the archive has none (never
    imported, or the fictional demo); a missing imports table is a
    legitimate archive, not an error (2026-08-07)."""
    return archive.get_identity("imports") or ImportsTable(imports=())


def build_transcripts(items: list[Item]) -> dict[str, str]:
    """id -> transcription for every item that has one."""
    return {it.id: str(it.raw.get("transcription")) for it in items if it.raw.get("transcription")}


def _same_person(a: Person, b: Person) -> bool:
    """Two records are the same person when the name matches and the dates
    don't disagree — a proposed record whose dob differs from the table's
    is a different person with the same name (the record book has three
    Richards, two Eleanors, two Stephens), not a fragment to dedup."""
    a_dob = a.dob.date if a.dob else None
    b_dob = b.dob.date if b.dob else None
    return a_dob is None or b_dob is None or a_dob == b_dob


def people_projection(archive: Archive) -> PeopleTable:
    """The people projection: the identity table plus any proposed records —
    the propose/confirm seam means a catalogued story's ref to a proposed
    person must resolve in the published projection. A proposed record whose
    id is already confirmed was promoted: the table wins, the stale file is
    skipped. The cast never fragments: a proposed record whose NAME already
    exists in the table or in an earlier proposal is skipped when it names
    the same person — same name AND no contradicting dob (2026-08-05 bot
    review; refined same day: distinct dobs = distinct people, the record
    book's repeated names)."""
    table = archive.get_identity("people")
    if table is None:
        raise DeriveError("archive has no people identity table")
    known = {p.id for p in table.people}
    by_name: dict[str, list[Person]] = {}
    # setdefault group-by in one pass keeps first-seen key order; a dict comprehension
    # cannot group without an O(n²) rescan or sorted+groupby changing the key order
    # lucidlint: ignore loop-pipeline setdefault group-by — no one-pass dict comprehension
    for person in table.people:
        by_name.setdefault(person.name.strip().lower(), []).append(person)
    people = list(table.people)
    for person in archive.proposed_people():
        if person.id in known:
            continue
        candidates = by_name.get(person.name.strip().lower(), [])
        if any(_same_person(candidate, person) for candidate in candidates):
            continue
        people.append(person)
        by_name.setdefault(person.name.strip().lower(), []).append(person)
    return replace(table, people=tuple(people))


def places_projection(archive: Archive) -> PlacesTable:
    """The places projection — the same proposed merge as people, plus a
    name-dedup: a proposed record whose NAME already exists in the table (a
    story mention minted a fresh id) is skipped — the moored-barges ×3 came
    from exactly this (2026-08-05)."""
    table = archive.get_identity("places")
    if table is None:
        raise DeriveError("archive has no places identity table")
    known = {p.id for p in table.places}
    known_names = {p.name.strip().lower() for p in table.places}
    added_names: set[str] = set()
    places = list(table.places)
    for place in archive.proposed_places():
        key = place.name.strip().lower()
        if place.id in known or key in known_names or key in added_names:
            continue
        added_names.add(key)
        places.append(place)
    return replace(table, places=tuple(places))


def orgs_projection(archive: Archive) -> OrgsTable:
    """The organisations projection — the identity table, or an empty list
    when the archive predates the orgs seam (additive: an archive with no
    orgs table must still publish). No proposed merge yet: an org the family
    engaged with is confirmed at import review (2026-08-05); a proposed-org
    seam can join later."""
    return archive.get_identity("orgs") or OrgsTable(orgs=())


# The avatar palette — named hues the placeholder SVGs understand
# (tools/placeholders.py). A person without a hand-picked hue still gets a
# stable one derived from the id: same person, same colour, every publish.
AVATAR_HUES = ("amber", "lilac", "rose", "sage", "sky", "slate")


def _hue_for(person: Person) -> str:
    if person.hue:
        return person.hue
    return AVATAR_HUES[sum(ord(c) for c in person.id) % len(AVATAR_HUES)]


def avatar_files(people: tuple[Person, ...]) -> dict[str, str]:
    """avatar-<id>.svg -> content, derived from the people records."""
    return {f"avatar-{person.id}.svg": svg_avatar(initials_of(person.name), _hue_for(person)) for person in people}


def asset_contents(archive: Archive, items: list[Item]) -> list[ItemAssets]:
    """Every asset publish writes, one record per item: copied from the
    archive when the scan is there (raw bytes — a scan is binary, never
    decoded as text), else a generated placeholder. A real scan always
    wins over the stand-in."""
    out: list[ItemAssets] = []
    for item in items:
        files: dict[str, str | bytes] = {}
        for asset in item.assets:
            real = archive.read_file_bytes(item.id, asset.file)
            files[asset.file] = real if real is not None else asset_svg(item, asset.file)
        out.append(ItemAssets(item_id=item.id, files=files))
    return out


# An extraction states its kind in the singular (person, place, theme, item,
# org) — the published set it must resolve against is the plural table.
_EXTRACTION_TABLES = {"person": "people", "place": "places", "theme": "themes", "item": "items", "org": "orgs"}


def _validate_refs(items: list[Item], ids: PublishedIds, themes: ThemesTable) -> None:
    """Every link a catalogued item carries must resolve in the published
    projection — a ref to an entity the reader cannot see is dangling.
    Items are the special case: a draft artifact is hidden from everyone
    but its owner, so a confirmed item ref to a draft (or missing) target
    is dangling even though the item exists. A theme record's curated
    items list must resolve too — a tombstoned letter left in a theme is a
    dangling card."""
    by_id = {it.id: it for it in items}
    for item in items:
        if item.status != "catalogued":
            continue
        _RefChecker(ids, by_id).check(item)
    _check_theme_items(themes, by_id)


class _RefChecker:
    """The dangling-link checks for the published projection — owns the
    resolution maps (the published id sets and by_id) the three per-item
    checks all read, with one check per catalogued item as its entry point.
    The (by_id, item) clump the checks used to thread is this object's
    state."""

    def __init__(self, ids: PublishedIds, items: Mapping[str, Item]) -> None:
        self._ids = ids
        self._items = items

    def check(self, item: Item) -> None:
        """Every link a catalogued item carries must resolve in the
        published projection — a ref to an entity the reader cannot see is
        dangling."""
        self._check_kind_refs(item)
        self._check_comment(item)
        self._check_extractions(item)

    def _check_kind_refs(self, item: Item) -> None:
        """The item's people/places/themes/orgs/items refs — each must resolve
        in the published projection. A confirmed ref to a draft (or missing)
        target is dangling even though the item exists (2026-08-05:
        story-2026-08-03-05 confirmed a draft object-sb-mirosa)."""
        for kind, refs in (
            ("people", item.people_refs),
            ("places", item.place_refs),
            ("themes", item.theme_refs),
            ("orgs", item.org_refs),
            ("items", item.item_refs),
        ):
            for ref in refs:
                if not self._ids.holds(kind, ref.id):
                    raise DeriveError(f"{item.id} links {ref.id}, which is not in the published projection")
                if kind == "items" and ref.status == "confirmed":
                    self._require_catalogued(
                        ref.id,
                        subject=item.id,
                        action="confirms a link to",
                        remedy="catalogue the artifact or downgrade the link to proposed",
                    )

    def _check_comment(self, item: Item) -> None:
        """The anchor a story comments on is a link too — a draft or
        tombstoned target is invisible to every visitor but the owner
        (2026-08-05 bot review, importance 7)."""
        comment_on = item.raw.get("comment_on")
        if comment_on:
            if not self._ids.holds("items", comment_on):
                raise DeriveError(f"{item.id} comments on {comment_on}, which is not in the published projection")
            self._require_catalogued(
                comment_on,
                subject=item.id,
                action="comments on",
                remedy="catalogue the artifact or remove the comment link",
            )

    def _check_extractions(self, item: Item) -> None:
        """The item's extraction matches — same promise as a link, so each
        must resolve in the same projection sets; an item match is the same
        dangling class as a confirmed ref (2026-08-05 review). Extraction
        kinds use the singular; "org" joined with the story-flow parity
        (2026-08-05)."""
        for extraction in (item.raw.get("chat") or {}).get("extractions") or []:
            if extraction.get("on") is False:
                continue  # the reviewer unticked it — excluded content is not a link
            match = extraction.get("match")
            if not match:
                continue  # an unresolved extraction (kinship filter) is honest output
            table = _EXTRACTION_TABLES.get(str(extraction.get("kind") or ""), "")
            if not self._ids.holds(table, match):
                raise DeriveError(
                    f"{item.id} extraction {extraction.get('name')!r} matches {match}, "
                    "which is not in the published projection"
                )
            if extraction.get("kind") == "item":
                self._require_catalogued(
                    match,
                    subject=item.id,
                    action=f"extraction {extraction.get('name')!r} matches",
                    remedy="catalogue the artifact or clear the match",
                )

    def _require_catalogued(self, target_id: str, subject: str, action: str, remedy: str) -> None:
        """A link's target must be a catalogued item — a draft artifact is
        hidden from everyone but its owner, so a confirmed link to a draft
        (or missing) target is dangling even though the item exists."""
        target = self._items.get(target_id)
        if target is not None and target.status == "catalogued":
            return
        state = "missing from the archive" if target is None else "still a draft"
        raise DeriveError(f"{subject} {action} {target_id}, which is {state} — {remedy}")


def _check_theme_items(themes: ThemesTable, items: Mapping[str, Item]) -> None:
    """A theme record's curated items list must resolve too — a tombstoned
    letter left in a theme is a dangling card."""
    for theme in themes.themes:
        for item_id in theme.item_ids():
            target = items.get(item_id)
            if target is None:
                raise DeriveError(f"theme {theme.id} lists {item_id}, which is not in the published projection")
            if target.status != "catalogued":
                raise DeriveError(
                    f"theme {theme.id} lists {item_id}, which is still a draft — "
                    "catalogue the artifact or remove it from the theme"
                )


def projection_json(archive: Archive) -> dict[str, str]:
    """Every derived JSON file for the static projection: index, people,
    places, orgs, themes, imports, transcripts — filename -> the text publish
    writes. One call, one shape — publish and the capture server refresh
    from here (docs/CONTRIBUTIONS.md)."""
    items = resolved_items(archive)
    people = people_projection(archive)
    places = places_projection(archive)
    orgs = orgs_projection(archive)
    themes = archive.get_identity("themes")
    if themes is None:
        raise DeriveError("archive has no themes identity table")
    _validate_refs(
        items,
        PublishedIds(
            people=frozenset(p.id for p in people.people),
            places=frozenset(p.id for p in places.places),
            themes=frozenset(t.id for t in themes.themes),
            orgs=frozenset(o.id for o in orgs.orgs),
            items=frozenset(it.id for it in items),
        ),
        themes=themes,
    )
    imports = imports_projection(archive)
    # the imports payload has always carried the archive's supersession
    # marker (the table is the review's own record, not a published cast);
    # the other tables' chain stays archive-internal
    imports_wire = imports.to_dict()
    if imports.supersedes:
        imports_wire["supersedes"] = imports.supersedes
    files: dict[str, str] = {}
    files["index.json"] = json.dumps(ProjectionIndex.build(items).to_dict(), indent=1, ensure_ascii=False)
    files["people.json"] = json.dumps(people.to_dict(), indent=1, ensure_ascii=False)
    files["places.json"] = json.dumps(places.to_dict(), indent=1, ensure_ascii=False)
    files["orgs.json"] = json.dumps(orgs.to_dict(), indent=1, ensure_ascii=False)
    files["themes.json"] = json.dumps(themes.to_dict(), indent=1, ensure_ascii=False)
    files["imports.json"] = json.dumps(imports_wire, indent=1, ensure_ascii=False)
    files["transcripts.json"] = json.dumps(build_transcripts(items), indent=1, ensure_ascii=False)
    return files


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _remove_dir(path: Path) -> None:
    """A re-publish replaces the previous output wholesale — drop *path*
    when an earlier copy is already there."""
    if path.exists():
        shutil.rmtree(path)


class Projection:
    """The derived app-facing surface (app/data) — the noun behind
    ``Archive.publish()``. The projection is a cache: never hand-edited; a
    change is a change to the archive, then re-publish (TECHSPEC §3-5).
    """

    def __init__(self, archive: Archive, out: Path) -> None:
        self.archive = archive
        self.out = Path(out)

    def build(self) -> None:
        """Regenerate the projection at *out* from the archive — derived, so
        the write path may replace freely (the archive is the store, not
        this)."""
        out = self.out
        archive = self.archive
        out.mkdir(parents=True, exist_ok=True)

        # the assets are the long tail of a publish (scan copies) — swap them
        # FIRST, then the JSONs atomically last: a failure mid-copy leaves the
        # old JSONs serving the old assets, a consistent projection (the
        # alternative — fresh JSONs over a half-written assets/ — serves broken
        # images until the next publish). The swap itself is a millisecond
        # window; re-running publish always repairs (2026-08-05 bot review).
        staged = out / "assets.tmp"
        _remove_dir(staged)
        staged.mkdir(parents=True)

        items = resolved_items(archive=archive)
        for item_assets in asset_contents(archive, items):
            folder = staged / item_assets.item_id
            folder.mkdir(parents=True)
            for filename, content in item_assets.files.items():
                if isinstance(content, bytes):
                    (folder / filename).write_bytes(content)
                else:
                    (folder / filename).write_text(content, encoding="utf-8")

        files = projection_json(archive=archive)
        # the avatars follow the published cast — the people table people.json
        # carries, so an avatar and a person card never disagree
        people = PeopleTable.from_dict(json.loads(files["people.json"]))
        for filename, content in avatar_files(people.people).items():
            (staged / filename).write_text(content, encoding="utf-8")

        assets_dir = out / "assets"
        _remove_dir(assets_dir)
        staged.rename(assets_dir)

        for filename, content in files.items():
            _atomic_write(out / filename, content)
