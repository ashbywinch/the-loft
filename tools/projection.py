"""The derivation engine — everything computed from the archive's primary
data, in one place (docs/TECH-SPEC.md §3): resolved items (highest sidecar,
primary content embedded from its file), identity tables, the index and
transcripts. Publish (batch), import (scan ingest) and the capture server
(site stories) all derive through this module — never a second copy of the
rules. Derived output is regenerable: same archive, same output.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tools.records import CONTENT_FILES

if TYPE_CHECKING:
    from tools.archive import Archive
from tools.placeholders import asset_svg, initials_of, svg_avatar
from tools.records import validate_identity

CONTENT_FIELD = {"story": "story", "transcription": "transcription"}


class DeriveError(RuntimeError):
    """Raised when the archive cannot be derived (missing identity table, …)."""


def resolved_items(archive: Archive) -> list[dict[str, Any]]:
    """Every live item: the highest sidecar, tombstoned items gone, primary
    content (story / transcription) embedded from its content file and the
    content asset entries stripped — the projection embeds text, the reader
    never renders a content file as an image."""
    items: list[dict[str, Any]] = []
    for item_id in archive.item_ids():
        item = archive.get_item(item_id)
        if item is None:
            continue  # tombstoned — gone from the projection
        item.pop("supersedes", None)  # the supersession chain is archive-internal, not projection content
        if not item.get("chat"):
            item.pop("chat", None)  # a capture record exists or it doesn't — never an empty field
        assets = list(item.get("assets") or [])
        for kind, _bare in CONTENT_FILES.items():
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
            item[CONTENT_FIELD[kind]] = text
            assets = [a for a in assets if a is not entry]
        # the projection's items carry the content fields per type (the app
        # reads them unconditionally — app/views/stories.js, item.js): story
        # everywhere (descriptions on letters/photos/objects), transcription
        # on stories/letters/documents only
        item.setdefault("story", "")
        if item.get("type") in ("story", "letter", "document"):
            item.setdefault("transcription", "")
        item["assets"] = assets
        items.append(item)
    return items


def identity(archive: Archive, name: str) -> dict[str, Any]:
    """The identity table (people + relationships, places, themes), or a
    DeriveError when the archive has none — derived data needs its source.
    Validated on the way out (unique ids, required fields, every
    relationship resolves, kinds closed) with the archive-internal
    ``supersedes`` chain stripped — the projection is content, the chain is
    not (2026-08-04 review finding: people.json shipped 'supersedes')."""
    table = archive.get_identity(name)
    if table is None:
        raise DeriveError(f"archive has no {name} identity table")
    try:
        return validate_identity(name, table)
    except ValueError as e:
        raise DeriveError(f"{name} identity table is invalid: {e}") from e


def imports_projection(archive: Archive) -> dict[str, Any]:
    """The import sessions — empty when the archive has none (never
    imported, or the fictional demo); a missing imports table is a
    legitimate archive, not an error (2026-08-07)."""
    table = archive.get_identity("imports")
    return table if table is not None else {"imports": []}


def build_index(items: list[dict[str, Any]]) -> dict[str, Any]:
    """The index: items sorted by date then id — deterministic, so the same
    archive always publishes the same projection."""
    return {
        "generated": date.today().isoformat(),
        "items": sorted(items, key=lambda it: (it["date"], it["id"])),
    }


def build_transcripts(items: list[dict[str, Any]]) -> dict[str, str]:
    """id -> transcription for every item that has one."""
    return {it["id"]: it["transcription"] for it in items if it.get("transcription")}


def _same_person(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Two records are the same person when the name matches and the dates
    don't disagree — a proposed record whose dob differs from the table's
    is a different person with the same name (the record book has three
    Richards, two Eleanors, two Stephens), not a fragment to dedup."""
    a_dob = (a.get("dob") or {}).get("date")
    b_dob = (b.get("dob") or {}).get("date")
    return a_dob is None or b_dob is None or a_dob == b_dob


def people_projection(archive: Archive) -> dict[str, Any]:
    """The people projection: the identity table plus any proposed records —
    the propose/confirm seam means a catalogued story's ref to a proposed
    person must resolve in the published projection. A proposed record whose
    id is already confirmed was promoted: the table wins, the stale file is
    skipped. The cast never fragments: a proposed record whose NAME already
    exists in the table or in an earlier proposal is skipped when it names
    the same person — same name AND no contradicting dob (2026-08-05 bot
    review; refined same day: distinct dobs = distinct people, the record
    book's repeated names)."""
    table = identity(archive, "people")
    known = {p["id"] for p in table["people"]}
    by_name: dict[str, list[dict[str, Any]]] = {}
    # setdefault group-by in one pass keeps first-seen key order; a dict comprehension
    # cannot group without an O(n²) rescan or sorted+groupby changing the key order
    # lucidlint: ignore loop-pipeline setdefault group-by — no one-pass dict comprehension
    for person in table["people"]:
        by_name.setdefault(person["name"].strip().lower(), []).append(person)
    for person in archive.proposed_people():
        record = person.to_dict()
        if person.id in known:
            continue
        candidates = by_name.get(person.name.strip().lower(), [])
        if any(_same_person(p, record) for p in candidates):
            continue
        table["people"].append(record)
        by_name.setdefault(person.name.strip().lower(), []).append(record)
    return table


def places_projection(archive: Archive) -> dict[str, Any]:
    """The places projection — the same proposed merge as people, plus a
    name-dedup: a proposed record whose NAME already exists in the table (a
    story mention minted a fresh id) is skipped — the moored-barges ×3 came
    from exactly this (2026-08-05)."""
    table = identity(archive, "places")
    known = {p["id"] for p in table["places"]}
    known_names = {p["name"].strip().lower() for p in table["places"]}
    added_names: set[str] = set()
    for place in archive.proposed_places():
        key = place.name.strip().lower()
        if place.id in known or key in known_names or key in added_names:
            continue
        added_names.add(key)
        table["places"].append(place.to_dict())
    return table


def orgs_projection(archive: Archive) -> dict[str, Any]:
    """The organisations projection — the identity table, validated, or an
    empty list when the archive predates the orgs seam (additive: an
    archive with no orgs table must still publish). No proposed merge yet:
    an org the family engaged with is confirmed at import review
    (2026-08-05); a proposed-org seam can join later."""
    table = archive.get_identity("orgs")
    if table is None:
        return {"orgs": []}
    try:
        return validate_identity("orgs", table)
    except ValueError as e:
        raise DeriveError(f"orgs identity table is invalid: {e}") from e


# The avatar palette — named hues the placeholder SVGs understand
# (tools/placeholders.py). A person without a hand-picked hue still gets a
# stable one derived from the id: same person, same colour, every publish.
AVATAR_HUES = ("amber", "lilac", "rose", "sage", "sky", "slate")


def _hue_for(person: dict[str, Any]) -> str:
    hue = person.get("hue")
    if hue:
        return hue
    return AVATAR_HUES[sum(ord(c) for c in person["id"]) % len(AVATAR_HUES)]


def avatar_files(people: list[dict[str, Any]]) -> dict[str, str]:
    """avatar-<id>.svg -> content, derived from the people records."""
    return {
        f"avatar-{person['id']}.svg": svg_avatar(initials_of(person["name"]), _hue_for(person)) for person in people
    }


def asset_contents(archive: Archive, items: list[dict[str, Any]]) -> dict[str, dict[str, str | bytes]]:
    """item_id -> {filename: content} for every asset: copied from the
    archive when the scan is there (raw bytes — a scan is binary, never
    decoded as text), else a generated placeholder. A real scan always
    wins over the stand-in."""
    out: dict[str, dict[str, str | bytes]] = {}
    for item in items:
        files: dict[str, str | bytes] = {}
        for asset in item.get("assets") or []:
            filename = asset["file"]
            real = archive.read_file_bytes(item["id"], filename)
            files[filename] = real if real is not None else asset_svg(item, filename)
        out[item["id"]] = files
    return out


# lucidlint: ignore long-param-list a single call site — a parameter object would add a type for one use
def _validate_refs(
    items: list[dict[str, Any]],
    people_ids: set[str],
    place_ids: set[str],
    theme_ids: set[str],
    org_ids: set[str],
    themes: dict[str, Any],
) -> None:
    """Every link a catalogued item carries must resolve in the published
    projection — a ref to an entity the reader cannot see is dangling.
    Items are the special case: a draft artifact is hidden from everyone
    but its owner, so a confirmed item ref to a draft (or missing) target
    is dangling even though the item exists (2026-08-05: story-2026-08-03-05
    confirmed a draft object-sb-mirosa). A theme record's curated items
    list must resolve too — a tombstoned letter left in a theme is a
    dangling card (2026-08-05)."""
    item_ids = {it["id"] for it in items}
    by_id = {it["id"]: it for it in items}
    known = {
        "people": people_ids,
        "places": place_ids,
        "themes": theme_ids,
        "orgs": org_ids,
        "items": item_ids,
    }
    for item in items:
        if item.get("status") != "catalogued":
            continue
        _check_kind_refs(item, known, by_id)
        _check_comment(item, by_id, item_ids)
        _check_extractions(item, known, by_id)
    _check_theme_items(themes, by_id)


def _check_kind_refs(item: dict[str, Any], known: dict[str, set[str]], by_id: dict[str, dict[str, Any]]) -> None:
    """The item's people/places/themes/orgs/items refs — each must resolve
    in the published projection. A confirmed ref to a draft (or missing)
    target is dangling even though the item exists (2026-08-05:
    story-2026-08-03-05 confirmed a draft object-sb-mirosa)."""
    for kind in ("people", "places", "themes", "orgs", "items"):
        for ref in item.get(kind) or []:
            rid = ref.get("id")
            if not rid:
                continue
            if rid not in known[kind]:
                raise DeriveError(f"{item['id']} links {rid}, which is not in the published projection")
            if kind == "items" and ref.get("status") == "confirmed":
                _require_catalogued(
                    rid,
                    by_id,
                    subject=item["id"],
                    action="confirms a link to",
                    remedy="catalogue the artifact or downgrade the link to proposed",
                )


def _check_comment(item: dict[str, Any], by_id: dict[str, dict[str, Any]], item_ids: set[str]) -> None:
    """The anchor a story comments on is a link too — a draft or tombstoned
    target is invisible to every visitor but the owner (2026-08-05 bot
    review, importance 7)."""
    comment_on = item.get("comment_on")
    if comment_on:
        if comment_on not in item_ids:
            raise DeriveError(f"{item['id']} comments on {comment_on}, which is not in the published projection")
        _require_catalogued(
            comment_on,
            by_id,
            subject=item["id"],
            action="comments on",
            remedy="catalogue the artifact or remove the comment link",
        )


def _check_extractions(item: dict[str, Any], known: dict[str, set[str]], by_id: dict[str, dict[str, Any]]) -> None:
    """The item's extraction matches — same promise as a link, so each must
    resolve in the same projection sets; an item match is the same dangling
    class as a confirmed ref (2026-08-05 review). Extraction kinds use the
    singular; "org" joined with the story-flow parity (2026-08-05)."""
    extraction_kinds = {"person": "people", "place": "places", "theme": "themes", "item": "items", "org": "orgs"}
    for extraction in (item.get("chat") or {}).get("extractions") or []:
        if extraction.get("on") is False:
            continue  # the reviewer unticked it — excluded content is not a link
        match = extraction.get("match")
        if not match:
            continue  # an unresolved extraction (kinship filter) is honest output
        table_name = extraction_kinds.get(str(extraction.get("kind") or ""), "")
        known_ids = known.get(table_name, set())
        if match not in known_ids:
            raise DeriveError(
                f"{item['id']} extraction {extraction.get('name')!r} matches {match}, "
                "which is not in the published projection"
            )
        if extraction.get("kind") == "item":
            _require_catalogued(
                match,
                by_id,
                subject=item["id"],
                action=f"extraction {extraction.get('name')!r} matches",
                remedy="catalogue the artifact or clear the match",
            )


def _require_catalogued(
    target_id: str, by_id: dict[str, dict[str, Any]], subject: str, action: str, remedy: str
) -> None:
    """A link's target must be a catalogued item — a draft artifact is
    hidden from everyone but its owner, so a confirmed link to a draft (or
    missing) target is dangling even though the item exists."""
    target = by_id.get(target_id)
    if target is not None and target.get("status") == "catalogued":
        return
    state = "missing from the archive" if target is None else "still a draft"
    raise DeriveError(f"{subject} {action} {target_id}, which is {state} — {remedy}")


def _check_theme_items(themes: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> None:
    """A theme record's curated items list must resolve too — a tombstoned
    letter left in a theme is a dangling card (2026-08-05)."""
    for theme in themes.get("themes") or []:
        for entry in theme.get("items") or []:
            eid = entry.get("id")
            if not eid:
                continue
            target = by_id.get(eid)
            if target is None:
                raise DeriveError(f"theme {theme['id']} lists {eid}, which is not in the published projection")
            if target.get("status") != "catalogued":
                raise DeriveError(
                    f"theme {theme['id']} lists {eid}, which is still a draft — "
                    "catalogue the artifact or remove it from the theme"
                )


def projection_json(archive: Archive) -> dict[str, Any]:
    """Every derived JSON file for the static projection: index, people,
    places, themes, transcripts. One call, one shape — publish and the
    capture server refresh from here (docs/CONTRIBUTIONS.md)."""
    items = resolved_items(archive)
    people = people_projection(archive)
    places = places_projection(archive)
    orgs = orgs_projection(archive)
    themes = identity(archive, "themes")
    _validate_refs(
        items,
        people_ids={p["id"] for p in people["people"]},
        place_ids={p["id"] for p in places["places"]},
        theme_ids={t["id"] for t in themes["themes"]},
        org_ids={o["id"] for o in orgs["orgs"]},
        themes=themes,
    )
    return {
        "index.json": json.dumps(build_index(items), indent=1, ensure_ascii=False),
        "people.json": json.dumps(people, indent=1, ensure_ascii=False),
        "places.json": json.dumps(places, indent=1, ensure_ascii=False),
        "orgs.json": json.dumps(orgs, indent=1, ensure_ascii=False),
        "themes.json": json.dumps(themes, indent=1, ensure_ascii=False),
        "imports.json": json.dumps(imports_projection(archive), indent=1, ensure_ascii=False),
        "transcripts.json": json.dumps(build_transcripts(items), indent=1, ensure_ascii=False),
    }


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def publish(archive: Archive, out: Path) -> None:
    """Regenerate the projection at *out* from *archive* — derived, so the
    write path may replace freely (the archive is the store, not this)."""
    out.mkdir(parents=True, exist_ok=True)

    # the assets are the long tail of a publish (scan copies) — swap them
    # FIRST, then the JSONs atomically last: a failure mid-copy leaves the
    # old JSONs serving the old assets, a consistent projection (the
    # alternative — fresh JSONs over a half-written assets/ — serves broken
    # images until the next publish). The swap itself is a millisecond
    # window; re-running publish always repairs (2026-08-05 bot review).
    staged = out / "assets.tmp"
    if staged.exists():
        shutil.rmtree(staged)
    staged.mkdir(parents=True)

    items = resolved_items(archive)
    for item_id, files in asset_contents(archive, items).items():
        folder = staged / item_id
        folder.mkdir(parents=True)
        for filename, content in files.items():
            if isinstance(content, bytes):
                (folder / filename).write_bytes(content)
            else:
                (folder / filename).write_text(content, encoding="utf-8")

    people = json.loads(projection_json(archive)["people.json"]).get("people", [])
    for filename, content in avatar_files(people).items():
        (staged / filename).write_text(content, encoding="utf-8")

    assets_dir = out / "assets"
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    staged.rename(assets_dir)

    for filename, content in projection_json(archive).items():
        _atomic_write(out / filename, content)


class Projection:
    """The derived app-facing surface (app/data) — the noun behind
    ``Archive.publish()``. The projection is a cache: never hand-edited; a
    change is a change to the archive, then re-publish (TECH-SPEC §3-5).
    """

    def __init__(self, archive: Archive, out: Path) -> None:
        self.archive = archive
        self.out = Path(out)

    def build(self) -> None:
        """Regenerate the projection at *out* from the archive."""
        publish(self.archive, self.out)
