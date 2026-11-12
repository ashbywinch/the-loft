"""The A7 verification gate — TECHSPEC/11 §Verification.

The gate checks counts, item versions, content bytes, the identity/review/
pipeline records, a 10 items / 5 people / 5 documents sample read, rebuild
equality (the projections before and after replaying the event log), the old
tree's byte-identity, and that the dry-run's operation list is the executed
one. It never writes; the only write is the rebuild's own projection replay.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from loft.live.batch_row import page_id_of
from loft.live.store import LiveStore
from pipeline.registry import list_batches
from tools.archive import Archive
from tools.records import ImportsTable, OrgsTable, PeopleTable, PlacesTable, ThemesTable
from tools.store import DiskStore


@dataclass(frozen=True)
class IdentitySources:
    """The archive's four identity tables, as the gate reads them."""

    people: PeopleTable
    places: PlacesTable
    orgs: OrgsTable
    themes: ThemesTable


@dataclass(frozen=True)
class VerificationReport:
    """What the gate found and the counts it compared."""

    findings: tuple[str, ...]
    counts: dict[str, int]
    digest_before: str
    digest_after: str

    @property
    def ok(self) -> bool:
        return not self.findings


class Projections:
    """The projection tables the rebuild replays and the digest covers."""

    TABLES: ClassVar[tuple[str, ...]] = (
        "people",
        "person_residences",
        "places",
        "orgs",
        "themes",
        "theme_items",
        "relationships",
        "items",
        "item_refs",
        "item_assets",
        "item_content",
        "documents",
        "document_pages",
        "batches",
        "scans",
        "pages",
        "readings",
        "page_rows",
        "page_row_links",
        "row_checks",
        "row_adjustments",
        "review_sessions",
        "review_messages",
        "review_decisions",
        "assets",
        "aliases",
        "claims",
        "commands",
        "jobs",
        "accounts",
        "search_docs",
    )

    @classmethod
    def digest(cls, connection: sqlite3.Connection) -> str:
        """A stable sha over every projection row, in rowid order."""
        digest = hashlib.sha256()
        for table in cls.TABLES:
            digest.update(table.encode("utf-8"))
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                digest.update(json.dumps(dict(row), sort_keys=True, default=str).encode("utf-8"))
        return digest.hexdigest()


def tree_digest(roots: tuple[Path, ...]) -> str:
    """A stable sha over every file's relative path and bytes in the roots."""
    digest = hashlib.sha256()
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            digest.update(str(path.relative_to(root)).encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


class Verification:
    """The gate's checks, over one store and the archive/workspace sources."""

    def __init__(self, store: LiveStore, *, archive_dir: Path, workspace: Path) -> None:
        self.store = store
        self.archive = Archive(DiskStore(archive_dir))
        self.archive_dir = archive_dir
        self.workspace = workspace
        self.findings: list[str] = []

    def findings_for(
        self,
        *,
        dry_operations: tuple[str, ...],
        executed_operations: tuple[str, ...],
        tree_before: str,
        tree_after: str,
    ) -> VerificationReport:
        self._operations(dry_operations, executed_operations)
        self._counts()
        self._versions()
        self._bytes()
        self._sample()
        self._tree(tree_before, tree_after)
        before = Projections.digest(self.store.connection)
        self.store.rebuild_all()
        after = Projections.digest(self.store.connection)
        if before != after:
            self.findings.append("rebuild equality: the projections changed after replaying the event log")
        if self.store.verify_chain() != ():
            self.findings.extend(self.store.verify_chain())
        return VerificationReport(
            findings=tuple(self.findings),
            counts=self._store_counts(),
            digest_before=before,
            digest_after=after,
        )

    def _operations(self, dry: tuple[str, ...], executed: tuple[str, ...]) -> None:
        if dry != executed:
            self.findings.append(
                f"dry-run operations ({len(dry)}) differ from the executed operations ({len(executed)})"
            )

    def _tree(self, before: str, after: str) -> None:
        if before != after:
            self.findings.append("the old tree changed during the migration (it must be read-only)")

    def _counts(self) -> None:
        expected = self._expected_counts()
        actual = self._store_counts()
        for key, count in expected.items():
            if actual.get(key) != count:
                self.findings.append(f"count {key}: store has {actual.get(key)}, archive has {count}")

    def _expected_counts(self) -> dict[str, int]:
        identity = self._identity_tables()
        imports = self._imports_table()
        batches = list_batches(self.workspace / "registry")
        return {
            "people": len(identity.people.people),
            "places": len(identity.places.places),
            "orgs": len(identity.orgs.orgs),
            "themes": len(identity.themes.themes),
            "relationships": len(identity.people.relationships),
            "items": len(self.archive.item_ids()),
            "review_sessions": len(imports.imports),
            "review_messages": sum(
                len(attempt.messages) for session in imports.imports for attempt in session.attempts
            ),
            "review_decisions": sum(
                len(attempt.decisions) for session in imports.imports for attempt in session.attempts
            ),
            "batches": len(batches),
            "scans": sum(len(batch.pages) for batch in batches),
            "pages": sum(len(batch.pages) for batch in batches),
            "documents": sum(len(batch.boundaries or []) for batch in batches),
            "document_pages": sum(len(boundary.pages) for batch in batches for boundary in batch.boundaries or []),
        }

    def _store_counts(self) -> dict[str, int]:
        tables = (
            "people",
            "places",
            "orgs",
            "themes",
            "relationships",
            "items",
            "review_sessions",
            "review_messages",
            "review_decisions",
            "batches",
            "scans",
            "pages",
            "documents",
            "document_pages",
        )
        return {
            table: int(self.store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables
        }

    def _identity_tables(self) -> IdentitySources:
        def table(name: str, kind: type) -> Any:
            value = self.archive.get_identity(name)
            if value is None:
                raise ValueError(f"the archive has no {name} table")
            if not isinstance(value, kind):
                raise ValueError(f"the archive's {name} table is {type(value).__name__}")
            return value

        return IdentitySources(
            people=table("people", PeopleTable),
            places=table("places", PlacesTable),
            orgs=table("orgs", OrgsTable),
            themes=table("themes", ThemesTable),
        )

    def _imports_table(self) -> ImportsTable:
        value = self.archive.get_identity("imports")
        if value is None:
            return ImportsTable(imports=())
        if not isinstance(value, ImportsTable):
            raise ValueError(f"the archive's imports table is {type(value).__name__}")
        return value

    def _versions(self) -> None:
        for row in self.store.connection.execute("SELECT item_id, version FROM items"):
            versions = self.archive.item_versions(row["item_id"])
            if not versions:
                self.findings.append(f"item {row['item_id']} is in the store but not the archive")
            elif int(row["version"]) != max(versions):
                self.findings.append(
                    f"item {row['item_id']} version {row['version']} does not match the archive's {max(versions)}"
                )

    def _bytes(self) -> None:
        for row in self.store.connection.execute("SELECT sha256, bytes FROM content"):
            if row["bytes"] is None:
                continue
            if hashlib.sha256(bytes(row["bytes"])).hexdigest() != row["sha256"]:
                self.findings.append(f"content {row['sha256']} does not match its bytes")
        for row in self.store.connection.execute("SELECT sha256, path FROM assets"):
            path = self.archive_dir / row["path"]
            if not path.is_file():
                self.findings.append(f"asset {row['path']} is missing")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                self.findings.append(f"asset {row['path']} does not match its sha")

    def _sample(self) -> None:
        for row in self.store.connection.execute(
            "SELECT item_id FROM items WHERE status <> 'deleted' ORDER BY item_id LIMIT 10"
        ):
            item = self.store.items.require(row["item_id"])
            old = self.archive.get_item(row["item_id"])
            if old is None:
                self.findings.append(f"sample item {item.id} is not in the archive")
                continue
            if (item.title, item.type, item.date, item.status) != (old.title, old.type, old.date, old.status):
                self.findings.append(f"sample item {item.id} differs from the archive")
        people = self._identity_tables().people
        for person in people.people[:5]:
            if self.store.people.get(person.id) is None:
                self.findings.append(f"sample person {person.id} is missing")
        batches = list_batches(self.workspace / "registry")
        for batch in batches:
            for index, boundary in enumerate((batch.boundaries or [])[:5]):
                document = self.store.documents.get(f"{batch.batch_id}/doc-{index + 1}")
                if document is None:
                    self.findings.append(f"sample document {batch.batch_id}/doc-{index + 1} is missing")
                    continue
                pages = [page.page_id for page in self.store.documents.pages(document.document_id)]
                if pages != [page_id_of(batch.batch_id, page) for page in boundary.pages]:
                    self.findings.append(f"sample document {document.document_id} pages differ")
