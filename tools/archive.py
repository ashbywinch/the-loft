"""The archive library — the one way to touch the archive's files.

Every read and write of the archive goes through this module
(docs/CONTRIBUTIONS.md): it enforces the append-only rule (delegating the
write check to tools/store.py), resolves sidecar versions (item.json,
item-2.json, … — the highest wins), marks deletions with tombstones instead
of removing files, and manages the proposed person/place records. The capture
server, the tools, and the import flow use this — never raw paths.

The sidecar versions are self-contained: a superseding file carries the full
metadata again plus ``supersedes`` naming the file it replaces, so a reader
in 2060 can follow the chain (docs/archive-durability.md).
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast, overload

from loft.live.errors import Conflict
from loft.live.items import ContentInput, default_trust
from pipeline.identification import Identification
from tools.anchor import Anchor
from tools.asset import Asset
from tools.gone_person import GonePerson
from tools.gone_place import GonePlace
from tools.memory import Knowledge, Memory, StoryRequest
from tools.projection import Projection, projection_json
from tools.records import (
    IdentityTable,
    ImportsTable,
    Item,
    OrgsTable,
    PeopleTable,
    Person,
    Place,
    PlacesTable,
    ReviewDecision,
    ReviewQueue,
    Session,
    ThemesTable,
    is_valid_record_id,
    split_content,
    validate_identity,
)
from tools.ref import Ref
from tools.store import FileStore

if TYPE_CHECKING:
    from loft.live.identities import Identities
    from loft.live.item_writes import ItemWrites
    from loft.live.page_writes import PageWrites
    from loft.live.review_writes import ReviewWrites


def _valid_record_id(record_id: str) -> str:
    """The record-id rule lives in tools.records (the classes own the wire
    format); this is the write-path enforcement — a crafted id must never
    reach a store path, where it could escape the proposed queue and delete
    an identity table."""
    if not is_valid_record_id(record_id):
        raise ArchiveError(f"invalid record id: {record_id!r}")
    return record_id


def _merged_refs(existing: tuple[Ref, ...], proposed: tuple[Ref, ...]) -> tuple[Ref, ...]:
    """The document's links after one identification read: every existing
    link keeps its own status (a confirmed link is never downgraded to a
    proposal), and a proposed link is added only for an entity the document
    does not already name."""
    by_id = {ref.id: ref for ref in existing}
    for ref in proposed:
        by_id.setdefault(ref.id, ref)
    return tuple(by_id.values())


def _with_people(table: PeopleTable | None, people: tuple[Person, ...]) -> PeopleTable:
    """The people table with the pass's proposed records appended."""
    if table is None:
        raise ArchiveError("archive has no people identity table")
    updated = table
    for person in people:
        if person.status == "proposed":
            updated = updated.with_record(person)
    return updated


def _with_places(table: PlacesTable | None, places: tuple[Place, ...]) -> PlacesTable:
    """The places table with the pass's proposed records appended."""
    if table is None:
        raise ArchiveError("archive has no places identity table")
    updated = table
    for place in places:
        if place.status == "proposed":
            updated = updated.with_record(place)
    return updated


def _versioned_path(label: str, subject: str, base: str, version: int) -> str:
    """One versioned append-only chain's path: ``base`` is the location and
    stem without the suffix, and the ``.json`` / ``-N.json`` form follows —
    sidecar chains live at assets/<id>/item, identity tables at the archive
    root (people, places, ...)."""
    if version < 1:
        raise ArchiveError(f"{label} version must be >= 1: {subject} v{version}")
    return f"{base}.json" if version == 1 else f"{base}-{version}.json"


def _import_session() -> Session:
    """The default pending document-import session."""
    return Session(
        id="import-documents",
        kind="import-review",
        title="The document import",
        status="pending",
        # the session's lifecycle at a glance: current
        # is the resume point; attempts is one entry per walk of
        # the review — the transcript and decisions of each walk,
        # separated so a fresh agent can see what happened in THIS
        # walk versus the last one
        current=None,
        attempts=(),
    )


def _import_session_apply(table: ImportsTable | None) -> ImportsTable:
    """The import-session mutation: write the pending document-import
    session once — a no-op when it is already present."""
    session = _import_session()
    # a missing table is an error to raise, never a silent stand-in
    if table is None:
        return ImportsTable(imports=(session,))
    if table.has("import-documents"):
        return table  # already present — a no-op writes nothing
    return table.with_session(session)


# The proposed-queue record kinds — the person/place methods differ only in
# the record class and the queue/table name; the shared helpers are typed
# over this.
ProposedRecord = TypeVar("ProposedRecord", Person, Place)

# The identity-table seam's own generic: ``_mutate_identity`` re-reads one
# table, applies the caller's mutation, and writes the next version — one
# implementation for every table type.
TTable = TypeVar("TTable", PeopleTable, PlacesTable, OrgsTable, ThemesTable, ImportsTable)


class ArchiveError(RuntimeError):
    """Raised when the archive invariant is broken."""


class Archive:
    """Domain access to the archive: resolution, supersession, tombstones."""

    SIDECAR = "item.json"

    # Primary content lives in files the sidecar describes (never as sidecar
    # The archive's identity tables (people + relationships, places, themes) live
    # at the archive root and follow the same append-only versioning as sidecars:
    # people.json, people-2.json, … — the highest wins.
    _IDENTITY_TABLES = ("people", "places", "themes", "orgs", "imports")

    # the identity-table write lock: the server's threads share
    # one Archive, and save_identity's read-compute-write must be atomic
    # between them — see save_identity for the full story
    _save_lock = threading.RLock()

    def __init__(self, store: FileStore) -> None:
        self.store: FileStore = store
        self.identities: Identities | None = None
        self._after_identity_write: Callable[[], Any] | None = None
        self.item_writes: ItemWrites | None = None
        self._after_item_write: Callable[[str], Any] | None = None
        self.reviews: ReviewWrites | None = None
        self._after_review_write: Callable[[], Any] | None = None
        self.page_writes: PageWrites | None = None
        self._after_page_write: Callable[[str], Any] | None = None

    def bind_identity_service(self, identities: Identities, after_write: Callable[[], Any]) -> None:
        """Flip the identity write path to the live store (B1).

        When bound, the identity verbs write one `Change` and then call the
        compatibility exporter, so the old readers see the old-shape tree.
        Unbound, the archive keeps its file write path (the rollback and the
        suite's oracle until E2).
        """
        self.identities = identities
        self._after_identity_write = after_write

    def bind_item_service(self, writes: ItemWrites, after_write: Callable[[str], Any]) -> None:
        """Flip the item write path to the live store (B2).

        `save_item`, `delete_item` and `agree_document` write one `Change`,
        then call the item compatibility exporter for that item, so the old
        readers see the versioned sidecar and content files they parse.
        """
        self.item_writes = writes
        self._after_item_write = after_write

    def _identity_changed(self) -> None:
        """The compatibility export runs synchronously with the write."""
        if self._after_identity_write is not None:
            self._after_identity_write()

    def bind_review_service(self, writes: ReviewWrites, after_write: Callable[[], Any]) -> None:
        """Flip the review-state write path to the live store (B3).

        The session verbs write one `Change` each and the imports-table
        exporter follows, so the projection and the archive's session reads
        see the old table.
        """
        self.reviews = writes
        self._after_review_write = after_write

    def _item_changed(self, item_id: str) -> None:
        """The item compatibility export runs synchronously with the write."""
        if self._after_item_write is not None:
            self._after_item_write(item_id)

    def _imports_changed(self) -> None:
        """The imports-table compatibility export runs with the write."""
        if self._after_review_write is not None:
            self._after_review_write()

    def bind_page_service(self, writes: PageWrites, after_write: Callable[[str], Any]) -> None:
        """Flip the page-work write path to the live store (B4a).

        The review's row correction writes one `Change` and the page
        compatibility exporter follows, so the review surface and the worker
        still read the work files they parse.
        """
        self.page_writes = writes
        self._after_page_write = after_write

    def correct_page_rows(self, page_id: str, adjustments: bytes, reading: dict[str, Any], *, actor: str) -> None:
        """The reviewer's drawn row lines — one change, then the old work
        files (`<page>.row-adjustments.json`, `<page>.rows-adjusted.json`)
        follow from the stored blobs."""
        writes = self.page_writes
        if writes is None:
            raise ArchiveError("no page service bound")
        writes.correct_rows(page_id, adjustments, reading, actor=actor)
        if self._after_page_write is not None:
            self._after_page_write(page_id)

    # -- resolution --------------------------------------------------------

    def _sidecar_versions(self, item_id: str) -> list[int]:
        item_id = _valid_record_id(item_id)  # the last read seam composing a store path from a caller id
        return self._contiguous_versions(
            f"item {item_id}",
            lambda v: self._sidecar_path(item_id, v),
            re.compile(rf"assets/{re.escape(item_id)}/item-(\d+)\.json"),
        )

    def _contiguous_versions(
        self, label: str, path_for: Callable[[int], str], version_pattern: re.Pattern[str]
    ) -> list[int]:
        """Versions 1..N present contiguously. A lost middle version (a
        partial Drive sync of the archive folder is the realistic trigger)
        fails loudly instead of silently serving the older contiguous run —
        publish would otherwise regenerate the projection from stale
        identity data and the drift guard would miss it."""
        versions: list[int] = []
        version = 1
        while True:
            if not self.store.exists(path_for(version)):
                break
            versions.append(version)
            version += 1
        first_missing = version
        directory = "/".join(path_for(1).split("/")[:-1])
        higher = [
            int(m.group(1))
            for path in self.store.list(directory)
            if (m := version_pattern.fullmatch(path)) and int(m.group(1)) > first_missing
        ]
        if higher:
            # the base itself missing (v1 gone, v2+ present) is the same
            # corruption: an empty chain would let the item vanish from the
            # projection, or a fresh v1 be shadowed by the stale higher
            # version
            missing = 1 if not versions else first_missing
            raise ArchiveError(
                f"{label} version chain has a gap: v{missing} is missing but v{min(higher)} is present "
                "— a partial sync of the archive? fix the files, never the projection"
            )
        return versions

    @staticmethod
    def _sidecar_path(item_id: str, version: int) -> str:
        """The sidecar file for one item version — v1 is item.json, later
        versions item-N.json, under assets/<id>/."""
        return _versioned_path("sidecar", item_id, f"assets/{item_id}/item", version)

    def get_item(self, item_id: str) -> Item | None:
        """The highest-version sidecar, or None when missing or tombstoned.
        Typed: the Item record owns the sidecar's wire format and its
        accessors."""
        versions = self._sidecar_versions(item_id)
        if not versions:
            return None
        item = Item(json.loads(self.store.read(self._sidecar_path(item_id, max(versions)))))
        return None if item.status == "deleted" else item

    def item_versions(self, item_id: str) -> list[int]:
        """Every sidecar version the archive holds, contiguous from 1 — the
        migration reads the chain, not only its head."""
        return self._sidecar_versions(item_id)

    def get_item_version(self, item_id: str, version: int) -> Item:
        """One sidecar version, typed but not validated — the migration's
        per-version read (the write seam validates; a historical sidecar is
        read as it was written)."""
        return Item(json.loads(self.store.read(self._sidecar_path(item_id, version))))

    def item_ids(self) -> list[str]:
        """Every item folder in the archive (deleted or not)."""
        return sorted({p.split("/")[1] for p in self.store.list("assets") if p.startswith("assets/")})

    def _identity_versions(self, name: str) -> list[int]:
        if name not in Archive._IDENTITY_TABLES:
            raise ArchiveError(f"unknown identity table: {name}")
        return self._contiguous_versions(
            f"identity {name}",
            lambda v: self._identity_path(name, v),
            re.compile(rf"{re.escape(name)}-(\d+)\.json"),
        )

    @staticmethod
    def _identity_path(name: str, version: int) -> str:
        """One identity table's versioned file — v1 is <name>.json, later
        versions <name>-N.json, at the archive root."""
        return _versioned_path("identity", name, name, version)

    def _identity_version(self, name: str) -> int:
        """The newest version of one identity table — 0 when it is absent."""
        versions = self._identity_versions(name)
        return versions[-1] if versions else 0

    @overload
    def get_identity(self, name: Literal["people"]) -> PeopleTable | None: ...

    @overload
    def get_identity(self, name: Literal["places"]) -> PlacesTable | None: ...

    @overload
    def get_identity(self, name: Literal["orgs"]) -> OrgsTable | None: ...

    @overload
    def get_identity(self, name: Literal["themes"]) -> ThemesTable | None: ...

    @overload
    def get_identity(self, name: Literal["imports"]) -> ImportsTable | None: ...

    @overload
    def get_identity(self, name: str) -> IdentityTable | None: ...

    def get_identity(self, name: str) -> IdentityTable | None:
        """The highest-version identity table as its own record type, or
        None when absent — the table's class owns the wire format and the
        invariants (tools/records.py), so a caller reads fields, never
        keys."""
        versions = self._identity_versions(name)
        if not versions:
            return None
        return validate_identity(name, json.loads(self.store.read(self._identity_path(name, max(versions)))))

    @staticmethod
    def content_path(item_id: str, filename: str) -> str:
        """The store path for one content file — the same id guard as every
        other write path, and a filename is a bare name: no separators, no
        '..', so a crafted id or filename cannot escape assets/<id>/."""
        item_id = _valid_record_id(item_id)
        if "/" in filename or "\\" in filename or ".." in filename:
            raise ArchiveError(f"invalid content filename: {filename!r}")
        return f"assets/{item_id}/{filename}"

    def _read_content_file(
        self, item_id: str, filename: str, limit: int | None = None, *, binary: bool = False
    ) -> str | bytes | None:
        """A content-file read: the exists guard plus one store read —
        text, the first ``limit`` bytes decoded, or raw bytes (scans and
        images are binary, never decoded as text — a JPEG decoded to str
        and re-encoded corrupts)."""
        path = self.content_path(item_id, filename)
        if not self.store.exists(path):
            return None
        if binary:
            return self.store.read_bytes(path)
        return self.store.read_prefix(path, limit) if limit is not None else self.store.read(path)

    def read_content(self, item_id: str, filename: str) -> str | None:
        """The item's content file text, or None when it doesn't exist."""
        return cast(str | None, self._read_content_file(item_id, filename))

    def read_content_prefix(self, item_id: str, filename: str, limit: int) -> str | None:
        """The item's content file's first ``limit`` bytes decoded, or None
        when the file doesn't exist — the bounded peek that lets a
        shortlist filter check a transcription WITHOUT reading the whole
        file (the review context never full-scans the archive on a chat
        message)."""
        return cast(str | None, self._read_content_file(item_id, filename, limit))

    def read_file_bytes(self, item_id: str, filename: str) -> bytes | None:
        """A content file's raw bytes — scans and images are binary, never
        decoded as text (a JPEG decoded to str and re-encoded corrupts)."""
        return cast(bytes | None, self._read_content_file(item_id, filename, binary=True))

    def save_file(self, item_id: str, filename: str, content: str | bytes) -> None:
        """Write one content file (a scan, a page image) into an item's
        folder — the append-only store refuses to overwrite an existing file.
        Used by import (scans entering the archive) and the bootstrap."""
        self.store.write_new(self.content_path(item_id, filename), content)

    # the params ARE the document's identity (title, date, precision), its text
    # and its item id — a facts object would be a second shape for the same
    # fields at every caller (the review gate, the approval, the tests)
    # lucidlint: ignore long-param-list the document's identity is its arguments
    def agree_document(
        self,
        *,
        title: str,
        date: str,
        date_precision: str,
        text: str,
        item_id: str = "",
        status: str = "catalogued",
        actor: str = "import",
    ) -> Item:
        """The reviewed document becomes an archive item: its sidecar (title,
        date, status) and the transcription as the item's own content file.
        A document the review re-agrees supersedes the item it already became
        (``item_id``), never mints a second.

        The id is ``doc-<date>``, or ``doc-<date>-N`` when a document of that
        date is already held — an id is minted once and never changes. The
        sidecar carries no pipeline coordinates: the registry's boundary
        records which item an agreed document became."""
        if not title.strip():
            raise ArchiveError("an agreed document needs a title")
        new_id = item_id or self._document_id(date)
        existing = self.get_item(new_id) if item_id else None
        sidecar: dict[str, Any] = (
            dict(existing.to_dict())
            if existing is not None
            else {
                "id": new_id,
                "type": "document",
                "assets": [],
                "people": [],
                "places": [],
                "themes": [],
                "orgs": [],
                "items": [],
            }
        )
        sidecar.update({"title": title.strip(), "date": date, "date_precision": date_precision, "status": status})
        item = Item(sidecar)
        try:
            self.save_item(item, content={"transcription": text}, actor=actor)
        except ValueError as e:  # Item.from_dict's vocabulary and date checks
            raise ArchiveError(f"the agreed document is not a valid item: {e}") from e
        return item

    def _document_id(self, date: str) -> str:
        """The next free ``doc-<date>`` id (``-2``, ``-3`` … for documents of
        the same date)."""
        held = set(self.item_ids())
        base = f"doc-{date}"
        if base not in held:
            return base
        suffix = 2
        while f"{base}-{suffix}" in held:
            suffix += 1
        return f"{base}-{suffix}"

    # -- identification (stages 7-8) ---------------------------------------

    def record_identification(self, identification: Identification) -> Item:
        """The identification pass's proposals become the document's state:
        the item's refs (merged with the links it already carries — an
        existing link keeps its status, so a pre-existing confirmed link is
        never downgraded to a proposal), the new records in the identity
        tables (proposed — an unagreed record sits marked inside the table it
        will join), and the item's ``identified`` flag, which keeps the
        document from being read again.

        The tables go first: a crash after them leaves proposals nothing
        references (harmless), while the item first would leave refs to
        records that do not exist — which publish refuses."""
        item = self.get_item(identification.item_id)
        if item is None:
            raise ArchiveError(f"no item {identification.item_id}")

        if self.identities is not None:
            self.identities.propose(
                people=tuple(person for person in identification.people if person.status == "proposed"),
                places=tuple(place for place in identification.places if place.status == "proposed"),
                actor="import",
            )
            self._identity_changed()
        else:
            self._mutate_identity("people", lambda table: _with_people(table, identification.people))
            self._mutate_identity("places", lambda table: _with_places(table, identification.places))

        sidecar = dict(item.to_dict())
        sidecar["people"] = [ref.to_dict() for ref in _merged_refs(item.people_refs, identification.people_refs())]
        sidecar["places"] = [ref.to_dict() for ref in _merged_refs(item.place_refs, identification.place_refs())]
        sidecar["identified"] = True
        self.save_item(Item(sidecar), actor="import")
        return Item(sidecar)

    def decide_identification(
        self,
        item_id: str,
        kind: Literal["person", "place"],
        record_id: str,
        decision: str,
        basis: dict[str, str] | None = None,
        *,
        actor: str = "import",
    ) -> Person | Place | GonePerson | GonePlace | None:
        """One stage-8 determination for one entity a document names: the
        item's ref and the identity table's record move together.

        The determinations are PeopleTable.resolved's vocabulary. A record
        the archive already holds as confirmed is never deleted by a
        mention's delete — only the mention goes; a proposed record is
        dismissed once no other item references it, so deleting one
        document's mention never removes a person another document (or a
        story) still names. Returns the record as it now stands — None for
        an id the table does not hold."""
        item_id = _valid_record_id(item_id)
        record_id = _valid_record_id(record_id)
        if decision not in ("attested", "estimated", "pending", "delete"):
            raise ValueError(f"unknown decision: {decision!r}")
        if kind not in ("person", "place"):
            raise ValueError(f"unknown identification kind: {kind!r}")
        item = self.get_item(item_id)
        if item is None:
            raise ArchiveError(f"no item {item_id}")
        refs_key = "people" if kind == "person" else "places"

        if kind == "person":
            people_table = self.get_identity("people")
            if people_table is None:
                raise ArchiveError("archive has no people identity table")
            record: Person | Place | None = people_table.record(record_id)
        else:
            places_table = self.get_identity("places")
            if places_table is None:
                raise ArchiveError("archive has no places identity table")
            record = places_table.record(record_id)
        if record is None:
            return None
        if decision == "pending":
            return record

        refs = item.people_refs if kind == "person" else item.place_refs
        if decision == "delete":
            decided = tuple(ref for ref in refs if ref.id != record_id)
        else:
            # a record the archive already holds as confirmed stays a fact on
            # the mention too: "record as a guess" never downgrades an
            # attested person to the document's guess
            status: Literal["confirmed", "estimated"] = (
                "confirmed" if decision == "attested" or record.status == "confirmed" else "estimated"
            )
            decided = tuple(replace(ref, status=status) if ref.id == record_id else ref for ref in refs)
        sidecar = dict(item.to_dict())
        sidecar[refs_key] = [ref.to_dict() for ref in decided]
        self.save_item(Item(sidecar), actor=actor)

        if decision == "delete" and record.status == "proposed":
            # the mention may be the only evidence: drop a proposal nothing
            # else references, keep one another item still names
            if not self._referencing_catalogued(record_id, refs_key):
                self._dismiss_proposal(kind, record_id, actor=actor)
                return GonePerson(record_id) if kind == "person" else GonePlace(record_id)
            return record
        if record.status == "confirmed":
            return record  # an attested record never becomes a guess
        return self._resolve_proposal(kind, record_id, decision, basis, actor=actor)

    def _dismiss_proposal(self, kind: Literal["person", "place"], record_id: str, *, actor: str) -> None:
        """End one proposed record — the delete determination's table half."""
        if self.identities is not None:
            self._reject_live(self.identities, record_id, kind, actor=actor)
            return
        if kind == "person":

            def dismiss_people(table: PeopleTable | None) -> PeopleTable:
                if table is None:
                    raise ArchiveError("archive has no people identity table")
                return table.dismissed(record_id)

            self._mutate_identity("people", dismiss_people)
        else:

            def dismiss_places(table: PlacesTable | None) -> PlacesTable:
                if table is None:
                    raise ArchiveError("archive has no places identity table")
                return table.dismissed(record_id)

            self._mutate_identity("places", dismiss_places)

    def _resolve_proposal(
        self,
        kind: Literal["person", "place"],
        record_id: str,
        decision: str,
        basis: dict[str, str] | None,
        *,
        actor: str,
    ) -> Person | Place | GonePerson | GonePlace | None:
        """Apply one determination to a proposed record and return it as it
        now stands — the live service's rule, or the table's own rule."""
        if self.identities is not None:
            record = (
                self.identities.resolve_person(record_id, decision, basis, actor=actor)
                if kind == "person"
                else self.identities.resolve_place(record_id, decision, basis, actor=actor)
            )
            self._identity_changed()
            return record
        if kind == "person":
            return self._resolve_person_proposal(record_id, decision, basis)
        return self._resolve_place_proposal(record_id, decision, basis)

    def _resolve_person_proposal(
        self, record_id: str, decision: str, basis: dict[str, str] | None
    ) -> Person | GonePerson | None:
        """PeopleTable.resolved, applied inside the archive's lock."""
        resolved: list[Person | GonePerson | None] = []

        def apply(table: PeopleTable | None) -> PeopleTable:
            if table is None:
                raise ArchiveError("archive has no people identity table")
            updated, record = table.resolved(record_id, decision, basis)
            resolved.append(record)
            return updated

        self._mutate_identity("people", apply)
        return resolved[0] if resolved else None

    def _resolve_place_proposal(
        self, record_id: str, decision: str, basis: dict[str, str] | None
    ) -> Place | GonePlace | None:
        """PlacesTable.resolved, applied inside the archive's lock."""
        resolved: list[Place | GonePlace | None] = []

        def apply(table: PlacesTable | None) -> PlacesTable:
            if table is None:
                raise ArchiveError("archive has no places identity table")
            updated, record = table.resolved(record_id, decision, basis)
            resolved.append(record)
            return updated

        self._mutate_identity("places", apply)
        return resolved[0] if resolved else None

    # -- writes ------------------------------------------------------------

    def item_sidecar_path(self, item_id: str, version: int) -> str:
        """The public path of one sidecar version — the compatibility
        exporter writes the same chain the old writer did."""
        return self._sidecar_path(_valid_record_id(item_id), version)

    def save_item(self, item: Item, content: dict[str, str] | None = None, *, actor: str = "import") -> int:
        """Create or supersede: writes the next version, never edits an
        existing file (the store refuses edits). The sidecar is validated
        against the Item record (tools/records.py) before writing — the
        whole object model is enforced at the one write seam.
        *content* maps a content kind ("story", "transcription") to the
        primary text, written as a versioned content file the sidecar
        references — primary content is never a sidecar JSON field. Returns
        the version written. When the live service is bound, the write is one
        `Change` and the item compatibility exporter follows."""
        if self.item_writes is not None:
            saved = self._save_item_live(item, content, actor=actor)
            self._item_changed(saved.id)
            return saved.version
        item_id = _valid_record_id(item.id)
        try:
            payload = dict(Item.from_dict(item.to_dict()).to_dict())
        except ValueError as e:
            raise ArchiveError(f"invalid item: {e}") from e
        versions = self._sidecar_versions(item_id)
        version = (versions[-1] if versions else 0) + 1
        if version > 1:
            payload["supersedes"] = self._sidecar_path(item_id, version - 1)
        pending_content = self._with_content_assets(payload, content, version) if content is not None else []
        # the sidecar goes FIRST: a crash mid-save leaves the version advanced
        # (sidecar present, content missing), so the next save supersedes and
        # writes a fresh content file. Content-first leaves an orphan content
        # file with no sidecar — the next save collides with the same filename
        # and is permanently blocked.
        self.store.write_new(self._sidecar_path(item_id, version), json.dumps(payload, indent=1, ensure_ascii=False))
        for filename, text in pending_content:
            self.store.write_new(self.content_path(item_id, filename), text)
        return version

    def _with_content_assets(
        self, payload: dict[str, Any], content: dict[str, str], version: int
    ) -> list[tuple[str, str]]:
        """Fold the caller's primary content into the sidecar's assets —
        versioned filenames, a cleared kind stripped, the bytes returned."""
        payload["assets"] = list(payload.get("assets") or [])
        present_kinds = {kind for kind, value in content.items() if value}
        # a content kind omitted from a re-save is a cleared field — its old
        # entry would otherwise publish the previous text forever
        payload["assets"] = [
            asset
            for asset in payload["assets"]
            if asset.get("kind") not in Item.CONTENT_FILES or asset.get("kind") in present_kinds
        ]
        pending: list[tuple[str, str]] = []
        for kind, text in content.items():
            if not text:
                continue
            bare = Item.CONTENT_FILES.get(kind)
            if bare is None:
                raise ArchiveError(f"unknown content kind: {kind}")
            filename = self._content_filename(bare, version)
            pending.append((filename, text))
            entry = next((asset for asset in payload["assets"] if asset.get("kind") == kind), None)
            if entry is not None:
                entry["file"] = filename
            else:
                payload["assets"].append(
                    Asset(kind=kind, file=filename, caption=Item.CONTENT_CAPTIONS.get(kind, "")).to_dict()
                )
        return pending

    def _save_item_live(self, item: Item, content: dict[str, str] | None, *, actor: str) -> Item:
        """The live save: canonical sidecar, content bytes and asset files for
        one `Change`; the service computes the version under its lock."""
        assert self.item_writes is not None  # the caller checked the binding
        item_id = _valid_record_id(item.id)
        try:
            payload = dict(Item.from_dict(item.to_dict()).to_dict())
        except ValueError as e:
            raise ArchiveError(f"invalid item: {e}") from e
        base = self.item_writes.version(item_id)
        version = base + 1
        if version > 1:
            payload["supersedes"] = self._sidecar_path(item_id, version - 1)
        split = split_content(Item(payload))
        supplied = {**split.content, **(content or {})}
        if content is not None or split.content:
            payload = split.sidecar.to_dict()
            self._with_content_assets(payload, supplied, version)
        sidecar = Item(payload)
        # a content kind the caller did not supply keeps its existing file and
        # text: a re-save of the sidecar must never drop the transcription
        texts: dict[str, str] = dict(supplied)
        for asset in sidecar.assets:
            if asset.kind in Item.CONTENT_FILES and asset.kind not in texts:
                existing = self.read_content(item_id, asset.file)
                if existing is not None:
                    texts[asset.kind] = existing
        files: dict[str, bytes] = {}
        for asset in sidecar.assets:
            if asset.kind in Item.CONTENT_FILES and texts.get(asset.kind) is not None:
                files[asset.file] = texts[asset.kind].encode("utf-8")
                continue
            data = self.read_file_bytes(item_id, asset.file)
            if data is None:
                raise ArchiveError(f"item {item_id} references missing file: {asset.file}")
            files[asset.file] = data
        inputs = tuple(
            ContentInput(kind=kind, data=text.encode("utf-8"), trust=default_trust(sidecar, kind))
            for kind, text in texts.items()
            if text
        )
        return self.item_writes.save(sidecar, content=inputs, files=files, base=base or None, actor=actor)

    @staticmethod
    def _content_filename(bare: str, version: int) -> str:
        """story.txt at v1, story-2.txt at v2 — content versions with its sidecar."""
        if version == 1:
            return bare
        stem, suffix = bare.rsplit(".", 1)
        return f"{stem}-{version}.{suffix}"

    def save_identity(self, name: str, table: IdentityTable) -> int:
        """Create or supersede an identity table — the same append-only rule
        as sidecars: never edits, a change is the next version. Callers with
        a ready-made table use this; callers that READ then modify must use
        ``_mutate_identity`` instead — the lock here covers only the
        version computation and the write: a writer that reads the table
        before the lock could still supersede a concurrent writer's change,
        silently dropping it — the no-lost-update guarantee only holds when
        the read is inside the lock."""
        with self._save_lock:
            versions = self._identity_versions(name)
            version = (versions[-1] if versions else 0) + 1
            payload = dict(table.to_dict())
            if version > 1:
                payload["supersedes"] = self._identity_path(name, version - 1)
            self.store.write_new(self._identity_path(name, version), json.dumps(payload, indent=1, ensure_ascii=False))
            return version

    def _mutate_identity(self, name: str, mutate: Callable[[TTable | None], TTable]) -> int:
        """Atomic read-modify-write of an identity table: the lock must
        span the READ, the mutation, AND the write — a writer that reads
        the table before the lock supersedes a concurrent writer's change.
        The caller expresses its intent as a
        function of the current table; the seam re-reads under the lock,
        applies, and writes the next version. The records are immutable, so
        the mutation RETURNS the table it wants — an unchanged return
        writes nothing (no copy, no in-place edit to detect). Returns the
        version written."""
        with self._save_lock:
            table = cast(TTable | None, self.get_identity(name))
            updated = mutate(table)
            if updated == table:
                # a no-op mutation (a keep, a determination that leaves the
                # record identical) writes NOTHING — byte-identical versions
                # would clutter the append-only history the PRD describes as
                # the archive's troubleshooting record
                versions = self._identity_versions(name)
                return versions[-1] if versions else 0
            versions = self._identity_versions(name)
            version = (versions[-1] if versions else 0) + 1
            payload = dict(updated.to_dict())
            if version > 1:
                payload["supersedes"] = self._identity_path(name, version - 1)
            self.store.write_new(self._identity_path(name, version), json.dumps(payload, indent=1, ensure_ascii=False))
            return version

    def delete_item(self, item_id: str, reason: str, *, actor: str = "import") -> int:
        """Tombstone: supersede with a ``status: deleted`` marker — the old
        files stay forever. Returns the tombstone's version."""
        item_id = _valid_record_id(item_id)
        return self.save_item(Item.tombstone(item_id, reason, self.get_item(item_id)), actor=actor)

    # -- proposed records --------------------------------------------------
    # The propose/confirm seam: a proposed person/place is the SAME record
    # type as a confirmed one (tools/records.py), marked proposed and queued
    # here until a person promotes it into the identity table. Append-only:
    # the proposed file stays after promotion; derive skips ids already in
    # the table.

    def _propose(self, kind: str, record: ProposedRecord, directory: str) -> None:
        """Queue one proposed record — marked proposed, written to the
        proposed queue (proposed/people/ or proposed/places/). The record
        is already validated (its class owns the invariants); a crafted id
        fails loudly, because the id becomes the store path."""
        proposed = record.as_proposed()
        if not is_valid_record_id(proposed.id):
            raise ArchiveError(f"cannot propose {kind}: invalid record id: {proposed.id!r}")
        self.store.write_new(
            f"proposed/{directory}/{proposed.id}.json",
            json.dumps(proposed.to_dict(), indent=1, ensure_ascii=False),
        )

    def propose_person(self, person: Person) -> None:
        """Queue a person record for review — marked proposed. From B3b the
        proposal is one `Change` (a row in the people table, marked proposed)
        and the compatibility exporter writes the old
        `proposed/people/<id>.json` file the old readers list."""
        if self.identities is not None:
            _valid_record_id(person.id)
            self.identities.propose(people=(person,), actor="import")
            self._identity_changed()
            return
        self._propose("person", person, "people")

    def propose_place(self, place: Place) -> None:
        """Queue a place record for review — marked proposed (the person
        seam's place twin, B3b)."""
        if self.identities is not None:
            _valid_record_id(place.id)
            self.identities.propose(places=(place,), actor="import")
            self._identity_changed()
            return
        self._propose("place", place, "places")

    def confirm_person(self, person_id: str, relation: str | None = None, *, actor: str = "import") -> Person:
        """The import's pending people — confirm one (kept = confirmed).
        Supersedes the people table; a confirmed record omits the status
        key. ``relation`` pins the SPECIFIC kinship the review settled on
        ("first cousin once removed (Nora's cousin via Fern)") — never a
        bare "cousin" (user). Idempotent: confirming a
        confirmed person changes nothing."""
        if self.identities is not None:
            person = self.identities.confirm_person(person_id, relation, actor=actor)
            self._identity_changed()
            return person
        table = self.get_identity("people")
        assert table is not None, "archive has no people table"
        person = table.record(person_id)
        if person is None:
            raise KeyError(f"no person {person_id}")
        if person.status != "proposed":
            return person
        confirmed = person.as_confirmed()
        if relation:
            confirmed = replace(confirmed, relation=relation)
        self.save_identity("people", table.with_record(confirmed))
        return confirmed

    def resolve_person(
        self, person_id: str, decision: str, basis: dict[str, str] | None = None, *, actor: str = "import"
    ) -> Person | GonePerson | None:
        """The review's four determinations for a person (user): the decision
        vocabulary is NOT the status vocabulary — "confirm" is a status, never an
        action. ``attested`` -> confirmed (the reviewer's own verified word);
        ``estimated`` -> the status estimated with the recorded basis {text, by,
        when} — the reviewer's words, the named person, the date; ``pending`` ->
        nothing changes; ``delete`` -> the person leaves the table.

        Every determination is applied to the record as it stands: a later
        determination supersedes an earlier one, and staleness is never detected
        and never tracked (2026-10-21, user). Returns the record as it now stands
        — None for an id the table does not hold. The determination itself is the
        table's own rule (PeopleTable.resolved); this seam only makes the
        read-apply-write atomic. When the live service is bound, the
        determination is one `Change` and the compatibility export follows."""
        if self.identities is not None:
            record = self.identities.resolve_person(person_id, decision, basis, actor=actor)
            self._identity_changed()
            return record
        ran = False
        record: Person | GonePerson | None = None

        def apply(table: PeopleTable | None) -> PeopleTable:
            nonlocal ran, record
            assert table is not None, "archive has no people table"
            updated, record = table.resolved(person_id, decision, basis)
            ran = True
            return updated

        self._mutate_identity("people", apply)
        assert ran, "the people table mutation never ran"
        return record

    def _proposed(
        self, directory: str, record_type: Callable[[dict[str, Any]], ProposedRecord]
    ) -> list[ProposedRecord]:
        """The queued proposed records of one kind — typed records; a
        corrupt file fails loudly (the fail-fast convention), never
        silently dropped: a skipped record would surface later as a
        confusing dangling-ref failure, or vanish with no trace."""
        out: list[ProposedRecord] = []
        for path in self.store.list(f"proposed/{directory}"):
            try:
                out.append(record_type(json.loads(self.store.read(path))))
            except ValueError as e:
                raise ArchiveError(f"corrupt proposed record {path}: {e}") from e
        return out

    def proposed_people(self) -> list[Person]:
        """The queued proposed people — typed records; a corrupt file fails
        loudly (the fail-fast convention), never silently dropped: a skipped
        record would surface later as a confusing dangling-ref failure, or
        vanish with no trace."""
        return self._proposed("people", Person.from_dict)

    def proposed_places(self) -> list[Place]:
        """The queued proposed places — typed records; corrupt files fail
        loudly, never silently skipped."""
        return self._proposed("places", Place.from_dict)

    def proposed_ids(self) -> set[str]:
        """Ids of proposed people and places (unverified, awaiting review)."""
        return {p.id for p in self.proposed_people()} | {pl.id for pl in self.proposed_places()}

    def _proposed_record(
        self,
        table_name: str,
        record_id: str,
        record_type: Callable[[dict[str, Any]], ProposedRecord],
        kind: str,
    ) -> ProposedRecord:
        """One queued proposed record, typed and validated — a missing file
        fails loudly (confirming a record the review never queued is a
        mistake, never a silent no-op)."""
        record_id = _valid_record_id(record_id)
        path = f"proposed/{table_name}/{record_id}.json"
        if not self.store.exists(path):
            raise ArchiveError(f"no proposed {kind} record: {record_id}")
        return record_type(json.loads(self.store.read(path)))

    def promote_person(self, person_id: str) -> int:
        """Confirm a proposed person: the row joins the table as confirmed
        (append-only). Returns the new table version. From B3b the record is
        the live row — a missing or rejected proposal fails loudly, and one
        already in the table is a contradiction, never a silent no-op."""
        if self.identities is not None:
            self._require_proposed(self.identities, person_id, "person")
            self.identities.promote_person(person_id, actor="import")
            self._identity_changed()
            return self._identity_version("people")
        record = self._proposed_record("people", person_id, Person.from_dict, "person")
        table = self.get_identity("people")
        if table is None:
            raise ArchiveError("archive has no people identity table")
        if table.has(record.id):
            raise ArchiveError(f"{record.id} is already in the people table")
        return self.save_identity("people", table.with_record(record.as_confirmed()))

    def promote_place(self, place_id: str) -> int:
        """Confirm a proposed place: the row joins the table as confirmed
        (append-only). Returns the new table version — the person seam's
        place twin (B3b)."""
        if self.identities is not None:
            self._require_proposed(self.identities, place_id, "place")
            self.identities.promote_place(place_id, actor="import")
            self._identity_changed()
            return self._identity_version("places")
        record = self._proposed_record("places", place_id, Place.from_dict, "place")
        table = self.get_identity("places")
        if table is None:
            raise ArchiveError("archive has no places identity table")
        if table.has(record.id):
            raise ArchiveError(f"{record.id} is already in the places table")
        return self.save_identity("places", table.with_record(record.as_confirmed()))

    def _referencing_catalogued(self, record_id: str, ref_kind: str) -> list[str]:
        """Every catalogued item whose refs still point at *record_id* —
        rejecting a proposed record the stories reference would leave
        dangling refs at publish. An extraction the
        reviewer kept is a link too; an unticked one (on: false) is excluded
        content and does not block the reject."""
        kind = "person" if ref_kind == "people" else "place"
        referrers: list[str] = []
        for item_id in self.item_ids():
            item = self.get_item(item_id)
            if item is None or item.status != "catalogued":
                continue
            if item.references(record_id, kind):
                referrers.append(item_id)
        return referrers

    def _reject_proposed(self, table_name: str, record_id: str, kind: str) -> None:
        """Drop a proposed record the review did not confirm — the proposed
        queue is the one place the store deletes; a double reject fails
        loudly; a record that catalogued stories still reference is refused
        — relink the stories first."""
        record_id = _valid_record_id(record_id)
        path = f"proposed/{table_name}/{record_id}.json"
        if not self.store.exists(path):
            raise ArchiveError(f"no proposed {kind} record: {record_id}")
        self._refuse_reject_while_referenced(record_id, table_name)
        self.store.delete(path)

    def reject_proposed_person(self, person_id: str) -> None:
        """Drop a proposed person the review did not confirm — a passing
        mention with no attestation is not a cast member. The
        proposed queue is the one place the store deletes; a double reject
        fails loudly; a record that catalogued stories still reference is
        refused — relink the stories first. From B3b the row ends marked
        rejected and the queue exporter removes its file."""
        if self.identities is not None:
            self._require_proposed(self.identities, person_id, "person")
            self._reject_live(self.identities, person_id, "person", actor="import")
            return
        self._reject_proposed("people", person_id, "person")

    def reject_proposed_place(self, place_id: str) -> None:
        """Drop a proposed place the review did not confirm — a passing
        story mention with an unknown location is fiction, not a place
        entity. The proposed queue is the one place the store deletes; a
        double reject fails loudly; a record that catalogued stories still
        reference is refused — relink the stories first (the person seam's
        place twin, B3b)."""
        if self.identities is not None:
            self._require_proposed(self.identities, place_id, "place")
            self._reject_live(self.identities, place_id, "place", actor="import")
            return
        self._reject_proposed("places", place_id, "place")

    def _require_proposed(self, identities: Identities, record_id: str, kind: Literal["person", "place"]) -> None:
        """The live queue's guard: a promotion or a reject needs a proposed
        row. A crafted id never reaches the store; a missing or rejected
        proposal fails as the old missing file did; a confirmed record is
        already in the table, never a silent no-op."""
        record_id = _valid_record_id(record_id)
        record = identities.person(record_id) if kind == "person" else identities.place(record_id)
        table = "people" if kind == "person" else "places"
        if record is None or record.status == "rejected":
            raise ArchiveError(f"no proposed {kind} record: {record_id}")
        if record.status != "proposed":
            raise ArchiveError(f"{record_id} is already in the {table} table")

    def _reject_live(
        self, identities: Identities, record_id: str, kind: Literal["person", "place"], *, actor: str
    ) -> None:
        """End a proposal through the live store and remove its queue file. A
        refusal (a catalogued story still names it) surfaces as the archive's
        own error, as the old queue verb did; the old readers' tree follows
        the write."""
        try:
            if kind == "person":
                identities.reject_person(record_id, actor=actor)
            else:
                identities.reject_place(record_id, actor=actor)
        except Conflict as error:
            raise ArchiveError(str(error)) from error
        self._identity_changed()

    def _refuse_reject_while_referenced(self, record_id: str, ref_kind: str) -> None:
        referrers = self._referencing_catalogued(record_id, ref_kind)
        if referrers:
            raise ArchiveError(
                f"cannot reject {record_id}: catalogued stories still reference it "
                f"({', '.join(sorted(referrers))}) — relink the stories or keep the record"
            )

    # -- the high-level domain acts (the object-model surface) --

    def publish(self, data_dir: Path = Path("app/data")) -> None:
        """Regenerate the projection (app/data) from the archive — the
        curator's publish act; the derivation is Projection's machinery."""
        Projection(self, data_dir).build()

    def _ensure_import_session(self) -> None:
        """Idempotent: write the pending document-import session once — the
        read-check-write is atomic under the archive's lock, so two
        concurrent cold starts cannot both compute the same next version
        and kill the walk."""
        if self.reviews is not None:
            self.reviews.ensure(_import_session(), actor="import")
            self._imports_changed()
            return
        self._mutate_identity("imports", _import_session_apply)

    def refresh_import_status(self) -> None:
        """Complete pending import sessions when nothing is left to review:
        the import's proposals (proposed people) are all confirmed or
        dismissed, so the session is done (user)."""
        if self.reviews is not None:
            self.reviews.refresh(actor="import")
            self._imports_changed()
            return
        people = self.get_identity("people")
        pending_people = any(p.status == "proposed" for p in people.people) if people else False
        if pending_people:
            return
        imports = self.get_identity("imports")
        if imports is None or not any(s.status == "pending" for s in imports.imports):
            return

        def apply(table: ImportsTable | None) -> ImportsTable:
            assert table is not None
            return table.completed()

        self._mutate_identity("imports", apply)

    # -- the sessions API (the archive's slice of the store API)
    # The import session's page carries its review record — the transcript,
    # the decisions, and the resume point — persisted on the imports table
    # (user: "all these transcripts should be available from the page of the
    # artifact being transcribed"; user: "extend the API to cover the
    # sessions so nobody has to look at the files unless they're working on
    # the API"). The review flow touches the sessions ONLY through these
    # methods, and the Session class (tools/records.py) owns the wire
    # format and the invariants — the write seam validates, never the
    # callers (coding-standards: enforce at the write seam).

    def review_queue(self) -> ReviewQueue:
        """The review's queue — the proposed links awaiting a decision and
        the already-placed count (the reconcile-first view; the queue never
        holds resolved people). Typed: the queue owns its shape."""
        people = self.get_identity("people")
        all_people = people.people if people else ()
        pending = tuple(p for p in all_people if p.status == "proposed")
        return ReviewQueue(pending=pending, already=len(all_people) - len(pending))

    def get_review_session(self, session_id: str) -> Session | None:
        """The session — the lifecycle at a glance (status, current,
        attempts) — or None when the session doesn't exist. Typed: the
        Session class is the model (coding-standards: domain concepts are
        classes)."""
        if self.reviews is not None:
            return self.reviews.session(session_id)
        imports = self.get_identity("imports")
        if imports is None:
            return None
        return next((s for s in imports.imports if s.id == session_id), None)

    def _update_import_session(self, session_id: str, mutate: Callable[[Session], Session]) -> None:
        """Apply one Session mutation atomically: the read-modify-write
        happens inside the archive's lock, after any concurrent writer's
        change. ``mutate`` runs on the session found in the
        imports table; a missing table or session is an error to raise."""

        if self.reviews is not None:
            self.reviews.update(session_id, mutate, actor="import")
            self._imports_changed()
            return

        def apply(table: ImportsTable | None) -> ImportsTable:
            if table is None:
                raise ArchiveError(f"no imports table for session {session_id}")
            session = next((s for s in table.imports if s.id == session_id), None)
            if session is None:
                raise ArchiveError(f"no import session {session_id}")
            return table.with_session(mutate(session))

        self._mutate_identity("imports", apply)

    def start_review_attempt(self, session_id: str) -> int:
        """Begin a new walk of the review — a fresh attempt starts only when
        the last is empty or finished (Session.start_attempt), so a
        mid-walk re-render continues the same attempt. Returns the current
        attempt's index. Atomic."""
        if self.reviews is not None:
            session = self.reviews.start(session_id, actor="import")
            self._imports_changed()
            return len(session.attempts) - 1
        result: dict[str, int] = {}

        def mutate(session: Session) -> Session:
            updated = session.start_attempt()
            result["attempt"] = len(updated.attempts) - 1
            return updated

        self._update_import_session(session_id, mutate)
        return result["attempt"]

    def record_review_message(
        self, session_id: str, role: str, text: str, when: str, thinking: str | None = None
    ) -> None:
        """Append one spoken line to the session's CURRENT attempt — the
        line the family saw, verbatim, and (for assistant turns) the raw
        verdict as the thinking (the transcript is the messages; the
        model's reasoning goes back to it verbatim on later calls). The
        read-modify-write is atomic — the read happens inside
        the lock, after any concurrent writer's change."""
        if role not in ("user", "assistant"):
            raise ArchiveError(f"unknown message role: {role!r}")

        def mutate(session: Session) -> Session:
            return session.add_message(cast(Literal["user", "assistant"], role), text, when, thinking)

        self._update_import_session(session_id, mutate)

    def record_review_decision(self, session_id: str, decision: ReviewDecision) -> None:
        """Record a review outcome — it advances the resume point; the last
        decision clears it (Session.add_decision). Atomic."""
        self._update_import_session(session_id, lambda session: session.add_decision(decision))

    def capture_memory(
        self,
        client: Any,
        *,
        anchor: Anchor,
        who: str,
        account: str,
        status: str = "draft",
    ) -> Item:
        """Capture a narrator's memory end to end — assess the account,
        build the story, save it through the append-only store, and refresh
        the projection. The headless form of the server's capture API
        (`loft capture-memory`); the interactive form runs on Server."""
        projection = {name: json.loads(text) for name, text in projection_json(self).items()}
        knowledge = Knowledge.from_projection(
            people=projection["people.json"]["people"],
            places=projection["places.json"]["places"],
            themes=projection["themes.json"]["themes"],
            items=projection["index.json"]["items"],
        )
        flow = Memory(client, knowledge)
        assessment = flow.assess(anchor=anchor, who=who, account=account)
        built_story = flow.build_story(
            request=StoryRequest(
                anchor=anchor,
                who=who,
                title=assessment.title,
                account=account,
                extractions=assessment.extractions,
                facts=assessment.facts,
                status=status,
            ),
            existing_ids=set(self.item_ids()) | self.proposed_ids(),
        )
        split = split_content(built_story.story)
        self.save_item(split.sidecar, content=split.content)
        for person in built_story.new_people:
            self.propose_person(person)
        for place in built_story.new_places:
            self.propose_place(place)
        self.publish()
        return built_story.story
