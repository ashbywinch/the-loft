"""The archive library — the one way to touch the archive's files.

Every read and write of the archive goes through this module
(docs/CONTRIBUTIONS.md): it enforces the append-only rule (delegating the
write check to tools/store.py), resolves sidecar versions (item.json,
item-2.json, … — the highest wins), marks deletions with tombstones instead
of removing files, and manages the proposed person/place records. The capture
server, the tools, and the import flow use this — never raw paths.

The sidecar versions are self-contained: a superseding file carries the full
metadata again plus ``supersedes`` naming the file it replaces, so a reader
in 2060 can follow the chain (docs/TECH-SPEC.md §3).
"""

from __future__ import annotations

import copy
import json
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast, final

from tools.records import Item, Person, Place, ReviewDecision, ReviewQueue, Session, is_valid_record_id
from tools.store import FileStore

SIDECAR = "item.json"


def _valid_record_id(record_id: str) -> str:
    """The record-id rule lives in tools.records (the classes own the wire
    format); this is the write-path enforcement — a crafted id must never
    reach a store path, where it could escape the proposed queue and delete
    an identity table (2026-08-05 bot review, security concern)."""
    if not is_valid_record_id(record_id):
        raise ArchiveError(f"invalid record id: {record_id!r}")
    return record_id


# Primary content lives in files the sidecar describes (never as sidecar
# JSON fields — docs/TECH-SPEC.md §3): a story is story.txt, a letter or
# document's transcription is transcription.txt. Content files version with
# their sidecar: v1 -> story.txt, v2 -> story-2.txt, … (append-only).
CONTENT_FILES: dict[str, str] = {"story": "story.txt", "transcription": "transcription.txt"}
CONTENT_CAPTIONS: dict[str, str] = {"story": "The story, verbatim", "transcription": "The transcription"}

# The archive's identity tables (people + relationships, places, themes) live
# at the archive root and follow the same append-only versioning as sidecars:
# people.json, people-2.json, … — the highest wins.
IDENTITY_TABLES = ("people", "places", "themes", "orgs", "imports")


class ArchiveError(RuntimeError):
    """Raised when the archive invariant is broken."""


def split_content(item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Separate primary content from metadata at the write seam (capture,
    import): the story text (story-type items) and the transcription
    (letters/documents) become content files; descriptions — the story field
    on photos and objects — stay as metadata. Returns (sidecar, content);
    feed both to :meth:`Archive.save_item`. The inverse of the derive
    engine's embedding (tools/derive.py)."""
    sidecar = dict(item)
    content: dict[str, str] = {}
    item_type = sidecar["type"]
    if item_type == "story":
        story = sidecar.pop("story", "") or ""
        transcription = sidecar.pop("transcription", "") or ""
        if story:
            content["story"] = story
        if transcription:  # a recorded testimony with a transcription keeps it
            content["transcription"] = transcription
    elif item_type in ("letter", "document"):
        transcription = sidecar.pop("transcription", "") or ""
        if transcription:
            content["transcription"] = transcription
    else:  # photo, object — the story field is a description, keep it
        sidecar.pop("transcription", None)
    return sidecar, content


@final
class Archive:
    """Domain access to the archive: resolution, supersession, tombstones."""

    # the identity-table write lock (2026-08-09): the server's threads share
    # one Archive, and save_identity's read-compute-write must be atomic
    # between them — see save_identity for the full story
    _save_lock = threading.RLock()

    def __init__(self, store: FileStore) -> None:
        self.store: FileStore = store

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
        identity data and the drift guard would miss it (2026-08-05 bot
        review)."""
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
            # version (2026-08-05 bot review)
            missing = 1 if not versions else first_missing
            raise ArchiveError(
                f"{label} version chain has a gap: v{missing} is missing but v{min(higher)} is present "
                "— a partial sync of the archive? fix the files, never the projection"
            )
        return versions

    def _sidecar_path(self, item_id: str, version: int) -> str:
        if version < 1:
            raise ArchiveError(f"sidecar version must be >= 1: {item_id} v{version}")
        return f"assets/{item_id}/{SIDECAR}" if version == 1 else f"assets/{item_id}/item-{version}.json"

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        """The highest-version sidecar, or None when missing or tombstoned."""
        versions = self._sidecar_versions(item_id)
        if not versions:
            return None
        item = json.loads(self.store.read(self._sidecar_path(item_id, max(versions))))
        return None if item.get("status") == "deleted" else item

    def item_ids(self) -> list[str]:
        """Every item folder in the archive (deleted or not)."""
        return sorted({p.split("/")[1] for p in self.store.list("assets") if p.startswith("assets/")})

    def _identity_versions(self, name: str) -> list[int]:
        if name not in IDENTITY_TABLES:
            raise ArchiveError(f"unknown identity table: {name}")
        return self._contiguous_versions(
            f"identity {name}",
            lambda v: self._identity_path(name, v),
            re.compile(rf"{re.escape(name)}-(\d+)\.json"),
        )

    def _identity_path(self, name: str, version: int) -> str:
        if version < 1:
            raise ArchiveError(f"identity version must be >= 1: {name} v{version}")
        return f"{name}.json" if version == 1 else f"{name}-{version}.json"

    def get_identity(self, name: str) -> dict[str, Any] | None:
        """The highest-version identity table, or None when absent."""
        versions = self._identity_versions(name)
        if not versions:
            return None
        return json.loads(self.store.read(self._identity_path(name, max(versions))))

    def content_path(self, item_id: str, filename: str) -> str:
        """The store path for one content file — the same id guard as every
        other write path, and a filename is a bare name: no separators, no
        '..', so a crafted id or filename cannot escape assets/<id>/
        (2026-08-05 bot review, security concern)."""
        item_id = _valid_record_id(item_id)
        if "/" in filename or "\\" in filename or ".." in filename:
            raise ArchiveError(f"invalid content filename: {filename!r}")
        return f"assets/{item_id}/{filename}"

    def read_content(self, item_id: str, filename: str) -> str | None:
        """The item's content file text, or None when it doesn't exist."""
        path = self.content_path(item_id, filename)
        return self.store.read(path) if self.store.exists(path) else None

    def read_content_prefix(self, item_id: str, filename: str, limit: int) -> str | None:
        """The item's content file's first ``limit`` bytes decoded, or None
        when the file doesn't exist — the bounded peek that lets a
        shortlist filter check a transcription WITHOUT reading the whole
        file (2026-08-11 review: the review context never full-scans the
        archive on a chat message)."""
        path = self.content_path(item_id, filename)
        return self.store.read_prefix(path, limit) if self.store.exists(path) else None

    def read_file_bytes(self, item_id: str, filename: str) -> bytes | None:
        """A content file's raw bytes — scans and images are binary, never
        decoded as text (a JPEG decoded to str and re-encoded corrupts)."""
        path = self.content_path(item_id, filename)
        return self.store.read_bytes(path) if self.store.exists(path) else None

    def save_file(self, item_id: str, filename: str, content: str | bytes) -> None:
        """Write one content file (a scan, a page image) into an item's
        folder — the append-only store refuses to overwrite an existing file.
        Used by import (scans entering the archive) and the bootstrap."""
        self.store.write_new(self.content_path(item_id, filename), content)

    # -- writes ------------------------------------------------------------

    def save_item(self, item: dict[str, Any], content: dict[str, str] | None = None) -> int:
        """Create or supersede: writes the next version, never edits an
        existing file (the store refuses edits). The sidecar is validated
        against the Item record (tools/records.py) before writing — the
        whole object model is enforced at the one write seam (2026-08-05).
        *content* maps a content kind ("story", "transcription") to the
        primary text, written as a versioned content file the sidecar
        references — primary content is never a sidecar JSON field. Returns
        the version written."""
        item_id = _valid_record_id(item["id"])
        try:
            Item.from_dict(item)
        except ValueError as e:
            raise ArchiveError(f"invalid item: {e}") from e
        versions = self._sidecar_versions(item_id)
        version = (versions[-1] if versions else 0) + 1
        payload = dict(item)
        if version > 1:
            payload["supersedes"] = self._sidecar_path(item_id, version - 1)
        pending_content: list[tuple[str, str]] = []
        if content is not None:
            payload["assets"] = list(payload.get("assets") or [])
            present_kinds = {k for k, v in content.items() if v}
            # a content kind omitted from a re-save is a cleared field —
            # its old entry would otherwise publish the previous text
            # forever (2026-08-05 bot review)
            payload["assets"] = [
                a for a in payload["assets"] if a.get("kind") not in CONTENT_FILES or a.get("kind") in present_kinds
            ]
            for kind, text in content.items():
                if not text:
                    continue
                bare, caption = CONTENT_FILES.get(kind), CONTENT_CAPTIONS.get(kind)
                if bare is None:
                    raise ArchiveError(f"unknown content kind: {kind}")
                filename = self._content_filename(bare, version)
                pending_content.append((filename, text))
                # match the existing entry by kind, not by the bare v1 name —
                # a re-save that loaded the current sidecar carries the
                # versioned file name, and appending would publish stale text
                entry = next((a for a in payload["assets"] if a.get("kind") == kind), None)
                if entry is not None:
                    entry["file"] = filename
                else:
                    payload["assets"].append({"kind": kind, "file": filename, "caption": caption})
        # the sidecar goes FIRST: a crash mid-save leaves the version advanced
        # (sidecar present, content missing), so the next save supersedes and
        # writes a fresh content file. Content-first left an orphan content
        # file with no sidecar — the next save collided with the same filename
        # and was permanently blocked (2026-08-04 review finding).
        self.store.write_new(self._sidecar_path(item_id, version), json.dumps(payload, indent=1, ensure_ascii=False))
        for filename, text in pending_content:
            self.store.write_new(self.content_path(item_id, filename), text)
        return version

    @staticmethod
    def _content_filename(bare: str, version: int) -> str:
        """story.txt at v1, story-2.txt at v2 — content versions with its sidecar."""
        if version == 1:
            return bare
        stem, suffix = bare.rsplit(".", 1)
        return f"{stem}-{version}.{suffix}"

    def save_identity(self, name: str, table: dict[str, Any]) -> int:
        """Create or supersede an identity table — the same append-only rule
        as sidecars: never edits, a change is the next version. Callers with
        a ready-made table use this; callers that READ then modify must use
        ``_mutate_identity`` instead — the lock here covers only the
        version computation and the write (2026-08-10 review: a writer that
        read the table before the lock could still supersede a concurrent
        writer's change, silently dropping it — the claimed no-lost-update
        guarantee only holds when the read is inside the lock)."""
        with self._save_lock:
            versions = self._identity_versions(name)
            version = (versions[-1] if versions else 0) + 1
            payload = dict(table)
            if version > 1:
                payload["supersedes"] = self._identity_path(name, version - 1)
            self.store.write_new(self._identity_path(name, version), json.dumps(payload, indent=1, ensure_ascii=False))
            return version

    def _mutate_identity(self, name: str, mutate: Callable[[dict[str, Any] | None], dict[str, Any]]) -> int:
        """Atomic read-modify-write of an identity table (2026-08-10
        review: the lock must span the READ, the mutation, AND the write —
        a writer that read the table before the lock still supersedes a
        concurrent writer's change). The caller expresses its intent as a
        function of the current table; the seam re-reads under the lock,
        applies, and writes the next version. Returns the version written."""
        with self._save_lock:
            table = self.get_identity(name)
            before = copy.deepcopy(table)
            payload = mutate(table)
            if payload == before:
                # a no-op mutation (a stale decision, a pending, an
                # unchanged record) writes NOTHING — byte-identical versions
                # would clutter the append-only history the PRD describes as
                # the archive's troubleshooting record (2026-08-11 review)
                versions = self._identity_versions(name)
                return versions[-1] if versions else 0
            versions = self._identity_versions(name)
            version = (versions[-1] if versions else 0) + 1
            if version > 1:
                payload["supersedes"] = self._identity_path(name, version - 1)
            self.store.write_new(self._identity_path(name, version), json.dumps(payload, indent=1, ensure_ascii=False))
            return version

    def delete_item(self, item_id: str, reason: str) -> int:
        """Tombstone: supersede with a ``status: deleted`` marker — the old
        files stay forever. Returns the tombstone's version."""
        item_id = _valid_record_id(item_id)
        current = self.get_item(item_id)
        return self.save_item(
            {
                "id": item_id,
                "type": (current or {}).get("type", "item"),
                "title": (current or {}).get("title", item_id),
                "status": "deleted",
                "reason": reason,
            }
        )

    # -- proposed records --------------------------------------------------
    # The propose/confirm seam: a proposed person/place is the SAME record
    # type as a confirmed one (tools/records.py), marked proposed and queued
    # here until a person promotes it into the identity table. Append-only:
    # the proposed file stays after promotion; derive skips ids already in
    # the table.

    def propose_person(self, person: dict[str, Any]) -> None:
        """Queue a person record for review — validated, marked proposed."""
        try:
            record = Person.from_dict(person).as_proposed()
        except ValueError as e:
            raise ArchiveError(f"cannot propose person: {e}") from e
        record_id = _valid_record_id(record.id)
        self.store.write_new(
            f"proposed/people/{record_id}.json",
            json.dumps(record.to_dict(), indent=1, ensure_ascii=False),
        )

    def propose_place(self, place: dict[str, Any]) -> None:
        """Queue a place record for review — validated, marked proposed."""
        try:
            record = Place.from_dict(place).as_proposed()
        except ValueError as e:
            raise ArchiveError(f"cannot propose place: {e}") from e
        record_id = _valid_record_id(record.id)
        self.store.write_new(
            f"proposed/places/{record_id}.json",
            json.dumps(record.to_dict(), indent=1, ensure_ascii=False),
        )

    def confirm_person(self, person_id: str, relation: str | None = None) -> dict[str, Any]:
        """The import's pending people — confirm one (kept = confirmed).
        Supersedes the people table; a confirmed record omits the status
        key. ``relation`` pins the SPECIFIC kinship the review settled on
        ("first cousin once removed (Nora's cousin via Fern)") — never a
        bare "cousin" (user, 2026-08-08). Idempotent: confirming a
        confirmed person changes nothing."""
        table = self.get_identity("people")
        assert table is not None, "archive has no people table"
        person = next((p for p in table["people"] if p["id"] == person_id), None)
        if person is None:
            raise KeyError(f"no person {person_id}")
        if person.get("status") == "proposed":
            confirmed = {k: v for k, v in person.items() if k != "status"}
            if relation:
                confirmed["relation"] = relation
            table["people"] = [confirmed if p["id"] == person_id else p for p in table["people"]]
            self.save_identity("people", table)
            return confirmed
        return person

    def dismiss_person(self, person_id: str) -> None:
        """The import's pending people — dismiss one (dropped = gone): the
        person and their relationships leave the people table (supersede)."""

        def apply(table: dict[str, Any] | None) -> dict[str, Any]:
            assert table is not None, "archive has no people table"
            person = next((p for p in table["people"] if p["id"] == person_id), None)
            if person is None:
                raise KeyError(f"no person {person_id}")
            if person.get("status") != "proposed":
                raise ValueError(f"{person_id} is not proposed — dismiss only removes pending people")
            table["people"] = [p for p in table["people"] if p["id"] != person_id]
            table["relationships"] = [
                r for r in table.get("relationships", []) if r.get("a") != person_id and r.get("b") != person_id
            ]
            return table

        self._mutate_identity("people", apply)

    def resolve_person(
        self, person_id: str, decision: str, basis: dict[str, str] | None = None
    ) -> tuple[dict[str, Any] | None, bool, bool]:
        """The review's four dispositions for a proposed person (user,
        2026-08-09): the decision vocabulary is NOT the status vocabulary —
        "confirm" is a status, never an action. ``attested`` -> confirmed
        (the reviewer's own verified word); ``estimated`` -> the status
        estimated with the recorded basis {text, by, when} — the reviewer's
        words, the named person, the date; ``pending`` -> the import's guess
        stays proposed, nothing changes; ``delete`` -> the person leaves the
        table. Returns (the person record — None when a duplicate delete
        finds the person already gone —, changed, was_proposed): did the
        mutation alter the record, and was the person still proposed at
        mutation time. Both flags are set INSIDE the lock, in the mutation
        itself, so a concurrent duplicate decision cannot misread them — a
        post-hoc status comparison raced (a confirmed record omits the
        status key, and the pre-read status was stale for a second
        concurrent decide; 2026-08-11 review). The whole read-check-write
        is atomic."""
        result: dict[str, Any] = {}

        def apply(current: dict[str, Any] | None) -> dict[str, Any]:
            assert current is not None, "archive has no people table"
            person = next((p for p in current["people"] if p["id"] == person_id), None)
            if person is None:
                # a duplicate delete (double-tap, two devices) finds the
                # person already removed — that is the already-resolved
                # state, never an error (2026-08-11 review: it used to 400
                # and the UI showed "That didn't save" for a deletion that
                # had already succeeded)
                result["person"] = None
                result["changed"] = False
                result["was_proposed"] = False
                return current
            if person.get("status") != "proposed":
                # the queue never holds resolved people — a stale decision is a
                # state, not an error: the person stays as they are (2026-08-09)
                result["person"] = person
                result["changed"] = False
                result["was_proposed"] = False
                return current
            if decision == "pending":
                result["person"] = person
                result["changed"] = False
                result["was_proposed"] = True
                return current
            if decision == "delete":
                current["people"] = [p for p in current["people"] if p["id"] != person_id]
                current["relationships"] = [
                    r for r in current.get("relationships", []) if r.get("a") != person_id and r.get("b") != person_id
                ]
                result["person"] = {"id": person_id, "gone": True}
                result["changed"] = True
                result["was_proposed"] = True
                return current
            updated = dict(person)
            if decision == "estimated":
                if basis is None or not str(basis.get("text", "")).strip():
                    raise ValueError(f"estimated needs a basis: {person_id}")
                updated["status"] = "estimated"
                updated["basis"] = basis
            elif decision == "attested":
                updated.pop("status", None)  # confirmed records omit the status key
            else:
                raise ValueError(f"unknown decision: {decision!r}")
            current["people"] = [updated if p["id"] == person_id else p for p in current["people"]]
            result["person"] = updated
            result["changed"] = True
            result["was_proposed"] = True
            return current

        self._mutate_identity("people", apply)
        return result["person"], result["changed"], result["was_proposed"]

    def proposed_people(self) -> list[Person]:
        """The queued proposed people — typed records; a corrupt file fails
        loudly (the fail-fast convention), never silently dropped: a skipped
        record would surface later as a confusing dangling-ref failure, or
        vanish with no trace (2026-08-05 bot review)."""
        out: list[Person] = []
        for path in self.store.list("proposed/people"):
            try:
                out.append(Person.from_dict(json.loads(self.store.read(path))))
            except ValueError as e:
                raise ArchiveError(f"corrupt proposed record {path}: {e}") from e
        return out

    def proposed_places(self) -> list[Place]:
        """The queued proposed places — typed records; corrupt files fail
        loudly, never silently skipped (2026-08-05 bot review)."""
        out: list[Place] = []
        for path in self.store.list("proposed/places"):
            try:
                out.append(Place.from_dict(json.loads(self.store.read(path))))
            except ValueError as e:
                raise ArchiveError(f"corrupt proposed record {path}: {e}") from e
        return out

    def proposed_ids(self) -> set[str]:
        """Ids of proposed people and places (unverified, awaiting review)."""
        return {p.id for p in self.proposed_people()} | {pl.id for pl in self.proposed_places()}

    def promote_person(self, person_id: str) -> int:
        """Confirm a proposed person: supersede the people identity table
        with the record appended (append-only). Returns the new version."""
        person_id = _valid_record_id(person_id)
        path = f"proposed/people/{person_id}.json"
        if not self.store.exists(path):
            raise ArchiveError(f"no proposed person record: {person_id}")
        record = Person.from_dict(json.loads(self.store.read(path)))
        table = self.get_identity("people")
        if table is None:
            raise ArchiveError("archive has no people identity table")
        if any(p["id"] == person_id for p in table["people"]):
            raise ArchiveError(f"{person_id} is already in the people table")
        table["people"].append(record.as_confirmed().to_dict())
        return self.save_identity("people", table)

    def promote_place(self, place_id: str) -> int:
        """Confirm a proposed place: supersede the places identity table
        with the record appended (append-only). Returns the new version."""
        place_id = _valid_record_id(place_id)
        path = f"proposed/places/{place_id}.json"
        if not self.store.exists(path):
            raise ArchiveError(f"no proposed place record: {place_id}")
        record = Place.from_dict(json.loads(self.store.read(path)))
        table = self.get_identity("places")
        if table is None:
            raise ArchiveError("archive has no places identity table")
        if any(p["id"] == place_id for p in table["places"]):
            raise ArchiveError(f"{place_id} is already in the places table")
        table["places"].append(record.as_confirmed().to_dict())
        return self.save_identity("places", table)

    def _referencing_catalogued(self, record_id: str, ref_kind: str) -> list[str]:
        """Every catalogued item whose refs still point at *record_id* —
        rejecting a proposed record the stories reference would leave
        dangling refs at publish (2026-08-05 bot review). An extraction the
        reviewer kept is a link too; an unticked one (on: false) is excluded
        content and does not block the reject."""
        extraction_kind = "person" if ref_kind == "people" else "place"
        referrers: list[str] = []
        for item_id in self.item_ids():
            item = self.get_item(item_id)
            if not item or item.get("status") != "catalogued":
                continue
            if any(r.get("id") == record_id for r in item.get(ref_kind) or []):
                referrers.append(item_id)
                continue
            if any(
                ex.get("on") is not False and ex.get("match") == record_id
                for ex in (item.get("chat") or {}).get("extractions") or []
                if ex.get("kind") == extraction_kind
            ):
                referrers.append(item_id)
        return referrers

    def reject_proposed_person(self, person_id: str) -> None:
        """Drop a proposed person the review did not confirm — a passing
        mention with no attestation is not a cast member (2026-08-05). The
        proposed queue is the one place the store deletes; a double reject
        fails loudly; a record that catalogued stories still reference is
        refused — relink the stories first (2026-08-05 bot review)."""
        person_id = _valid_record_id(person_id)
        path = f"proposed/people/{person_id}.json"
        if not self.store.exists(path):
            raise ArchiveError(f"no proposed person record: {person_id}")
        self._refuse_reject_while_referenced(person_id, "people")
        self.store.delete(path)

    def reject_proposed_place(self, place_id: str) -> None:
        """Drop a proposed place the review did not confirm — a passing
        story mention with an unknown location is fiction, not a place
        entity (2026-08-05: the moored-barges records came from a dev-test
        story). The proposed queue is the one place the store deletes; a
        double reject fails loudly; a record that catalogued stories still
        reference is refused — relink the stories first (2026-08-05 bot
        review)."""
        place_id = _valid_record_id(place_id)
        path = f"proposed/places/{place_id}.json"
        if not self.store.exists(path):
            raise ArchiveError(f"no proposed place record: {place_id}")
        self._refuse_reject_while_referenced(place_id, "places")
        self.store.delete(path)

    def _refuse_reject_while_referenced(self, record_id: str, ref_kind: str) -> None:
        referrers = self._referencing_catalogued(record_id, ref_kind)
        if referrers:
            raise ArchiveError(
                f"cannot reject {record_id}: catalogued stories still reference it "
                f"({', '.join(sorted(referrers))}) — relink the stories or keep the record"
            )

    # -- the high-level domain acts (the object-model surface, 2026-08-06) --

    def publish(self, data_dir: Path = Path("app/data")) -> None:
        """Regenerate the projection (app/data) from the archive — the
        curator's publish act; the derivation is Projection's machinery."""
        from tools.projection import Projection

        Projection(self, data_dir).build()

    def create_demo(self) -> None:
        """Seed a demo archive with the fictional demo content (fictional
        only, never real names). The projection follows from a separate
        ``publish()`` — the CLI's create-demo chains seed then publish to
        the demo's own data dir, never app/data (2026-08-06)."""
        from tools.demo_data import create_demo

        create_demo(self)

    def capture_document(self, scans: Path) -> None:
        """Capture the scanned documents (the 2001 email; the interview
        demo's documents) — idempotent, proposed records for the review
        seam. `loft capture-document`."""
        from tools.document_capture import capture_demo_documents, capture_document

        # the record book first: the email's corrections patch people the
        # record book creates the confirmed cast (ids come from the dataset) — on
        # a fresh archive the reverse order KeyErrors (review, 2026-08-07)
        capture_demo_documents(self, scans)
        capture_document(self, scans)
        # the session the import leaves behind (user, 2026-08-07): the
        # document import stays pending until its proposed people are
        # confirmed or dismissed — the front page shows the session, and
        # refresh_import_status() completes it when nothing is pending
        self._ensure_import_session()

    def _ensure_import_session(self) -> None:
        """Idempotent: write the pending document-import session once."""
        imports = self.get_identity("imports")
        if imports is not None and any(s.get("id") == "import-documents" for s in imports["imports"]):
            return
        record = Session.from_dict(
            {
                "id": "import-documents",
                "kind": "import-review",
                "title": "The document import",
                "status": "pending",
                # the session's lifecycle at a glance (2026-08-09): current is
                # the resume point; attempts is one entry per walk of the review
                # — the transcript and decisions of each walk, separated so a
                # fresh agent can see what happened in THIS walk versus the
                # last one (the accumulated-mess fix)
                "current": None,
                "attempts": [],
            }
        ).to_dict()
        if imports is None:
            self.save_identity("imports", {"imports": [record]})
        else:
            imports["imports"] = [s for s in imports["imports"] if s.get("id") != "import-documents"] + [record]
            self.save_identity("imports", imports)

    def refresh_import_status(self) -> None:
        """Complete pending import sessions when nothing is left to review:
        the import's proposals (proposed people) are all confirmed or
        dismissed, so the session is done (2026-08-07, user)."""
        people = self.get_identity("people")
        pending_people = any(p.get("status") == "proposed" for p in (people or {}).get("people", []))
        if pending_people:
            return
        imports = self.get_identity("imports")
        if imports is None or not any(s.get("status") == "pending" for s in imports.get("imports", [])):
            return

        def apply(table: dict[str, Any] | None) -> dict[str, Any]:
            assert table is not None
            for i, s in enumerate(table["imports"]):
                if s.get("status") == "pending":
                    table["imports"][i] = Session.from_dict(s).completed().to_dict()
            return table

        self._mutate_identity("imports", apply)

    # -- the sessions API (the archive's slice of the store API, 2026-08-09)
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
        all_people = tuple(Person.from_dict(p) for p in (people or {}).get("people", []))
        pending = tuple(p for p in all_people if p.status == "proposed")
        return ReviewQueue(pending=pending, already=len(all_people) - len(pending))

    def get_review_session(self, session_id: str) -> Session | None:
        """The session — the lifecycle at a glance (status, current,
        attempts) — or None when the session doesn't exist. Typed: the
        Session class is the model (coding-standards: domain concepts are
        classes)."""
        imports = self.get_identity("imports")
        if imports is None:
            return None
        session = next((s for s in imports.get("imports", []) if s.get("id") == session_id), None)
        return Session.from_dict(session) if session else None

    def start_review_attempt(self, session_id: str) -> int:
        """Begin a new walk of the review — a fresh attempt starts only when
        the last is empty or finished (Session.start_attempt), so a
        mid-walk re-render continues the same attempt. Returns the current
        attempt's index. Atomic (2026-08-10 review)."""
        result: dict[str, int] = {}

        def apply(table: dict[str, Any] | None) -> dict[str, Any]:
            if table is None:
                raise ArchiveError(f"no imports table for session {session_id}")
            session = next((s for s in table["imports"] if s.get("id") == session_id), None)
            if session is None:
                raise ArchiveError(f"no import session {session_id}")
            updated = Session.from_dict(session).start_attempt()
            result["attempt"] = len(updated.attempts) - 1
            table["imports"] = [updated.to_dict() if s.get("id") == session_id else s for s in table["imports"]]
            return table

        self._mutate_identity("imports", apply)
        return result["attempt"]

    def record_review_message(
        self, session_id: str, role: str, text: str, when: str, thinking: str | None = None
    ) -> None:
        """Append one spoken line to the session's CURRENT attempt — the
        line the family saw, verbatim, and (for assistant turns) the raw
        verdict as the thinking (2026-08-09: the transcript is the
        messages; the model's reasoning goes back to it verbatim on later
        calls). The read-modify-write is atomic — the read happens inside
        the lock, after any concurrent writer's (2026-08-10 review)."""
        if role not in ("user", "assistant"):
            raise ArchiveError(f"unknown message role: {role!r}")

        def apply(table: dict[str, Any] | None) -> dict[str, Any]:
            if table is None:
                raise ArchiveError(f"no imports table for session {session_id}")
            session = next((s for s in table["imports"] if s.get("id") == session_id), None)
            if session is None:
                raise ArchiveError(f"no import session {session_id}")
            updated = Session.from_dict(session).add_message(
                cast(Literal["user", "assistant"], role), text, when, thinking
            )
            table["imports"] = [updated.to_dict() if s.get("id") == session_id else s for s in table["imports"]]
            return table

        self._mutate_identity("imports", apply)

    def record_review_decision(self, session_id: str, decision: ReviewDecision) -> None:
        """Record a review outcome — it advances the resume point; the last
        decision clears it (Session.add_decision). Atomic (2026-08-10)."""

        def apply(table: dict[str, Any] | None) -> dict[str, Any]:
            if table is None:
                raise ArchiveError(f"no imports table for session {session_id}")
            session = next((s for s in table["imports"] if s.get("id") == session_id), None)
            if session is None:
                raise ArchiveError(f"no import session {session_id}")
            updated = Session.from_dict(session).add_decision(decision)
            table["imports"] = [updated.to_dict() if s.get("id") == session_id else s for s in table["imports"]]
            return table

        self._mutate_identity("imports", apply)

    def capture_memory(
        self,
        client: Any,
        *,
        anchor: dict[str, Any],
        who: str,
        account: str,
        status: str = "draft",
    ) -> dict[str, Any]:
        """Capture a narrator's memory end to end — assess the account,
        build the story, save it through the append-only store, and refresh
        the projection. The headless form of the server's capture API
        (`loft capture-memory`); the interactive form runs on Server."""
        from tools.memory import Knowledge, Memory
        from tools.projection import projection_json

        projection = {name: json.loads(text) for name, text in projection_json(self).items()}
        knowledge = Knowledge.from_projection(
            people=projection["people.json"]["people"],
            places=projection["places.json"]["places"],
            themes=projection["themes.json"]["themes"],
            items=projection["index.json"]["items"],
        )
        flow = Memory(client, knowledge)
        assessment = flow.assess(anchor=anchor, who=who, account=account)
        story, new_people, new_places = flow.build_story(
            anchor=anchor,
            who=who,
            title=assessment["title"],
            account=account,
            extractions=assessment["extractions"],
            facts=assessment["facts"],
            existing_ids=set(self.item_ids()) | self.proposed_ids(),
            status=status,
        )
        sidecar, content = split_content(story)
        self.save_item(sidecar, content=content)
        for person in new_people:
            self.propose_person(person)
        for place in new_places:
            self.propose_place(place)
        self.publish()
        return story
