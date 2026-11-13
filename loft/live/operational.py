"""The operational backup — the full DB, content store and event log.

TECHSPEC/07 §18.8: the backup is the restore source and the audit trail, never
filtered. It writes the SQL dump, `content/`, the event log by year, the
content catalog, the schema/migration files, the vocabulary and the manifest;
`verify()` restores the dump into a scratch DB and compares every table.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from loft.live.errors import LiveError
from loft.live.schema import Schema
from loft.live.store import LiveStore
from loft.live.verify import Projections
from tools.dated_fact import PRECISIONS
from tools.loft_paths import LoftPaths
from tools.records import (
    EVENT_KINDS,
    ITEM_STATUSES,
    ITEM_TYPES,
    RECORD_STATUSES,
    RELATIONSHIP_KINDS,
    TRANSCRIPTION_STATUSES,
)


class BackupError(LiveError):
    """The operational backup cannot be written to this path or is corrupt."""


@dataclass(frozen=True)
class BackupReport:
    """What the backup wrote: its counts and the exported point."""

    out: Path
    counts: dict[str, int]
    files: int
    exported_through: int


@dataclass(frozen=True)
class BackupVerification:
    """The backup's restore check: findings and the restored counts."""

    findings: tuple[str, ...]
    counts: dict[str, int]

    @property
    def ok(self) -> bool:
        return not self.findings


class OperationalBackup:
    """The operational backup and its restore check."""

    LIVE_ROOTS: ClassVar[tuple[Path, ...]] = (
        LoftPaths.ARCHIVE_DIR,
        LoftPaths.WORKSPACE / "archive",
        LoftPaths.WORKSPACE / "backup",
    )
    CONTRACT_TABLES: ClassVar[tuple[str, ...]] = (
        "events",
        "content",
        "items",
        "item_refs",
        "item_assets",
        "item_content",
        "people",
        "person_residences",
        "places",
        "orgs",
        "themes",
        "theme_items",
        "relationships",
        "documents",
        "document_pages",
        "batches",
        "scans",
        "pages",
        "page_rows",
        "page_row_links",
        "row_checks",
        "row_adjustments",
        "readings",
        "review_sessions",
        "claims",
        "review_messages",
        "review_decisions",
        "assets",
        "aliases",
        "withdrawals",
        "commands",
        "accounts",
    )
    SCHEMA_FILE = "migrations/0001.sql"

    def __init__(self, store: LiveStore, out: Path) -> None:
        self.store = store
        self.out = out

    def write(self) -> BackupReport:
        """Write the operational backup to the scratch path."""
        self._check_out()
        self.out.mkdir(parents=True, exist_ok=True)
        self._write_dump()
        self._write_content()
        self._write_events()
        self._write_catalogs()
        self._write_schema()
        self._write_vocabulary()
        self._write_readme()
        counts = {table: self._count(table) for table in self.CONTRACT_TABLES}
        exported_through = int(self.store.connection.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0])
        self._write_manifest(counts, exported_through)
        return BackupReport(
            out=self.out,
            counts=counts,
            files=len(self._files()),
            exported_through=exported_through,
        )

    def verify(self) -> BackupVerification:
        """Restore the dump into a scratch DB and compare the backup contract."""
        findings: list[str] = []
        manifest_path = self.out / "db-manifest.json"
        if not manifest_path.is_file():
            return BackupVerification(findings=("db-manifest.json is missing",), counts={})
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        listed = manifest.get("files", {})
        actual = {path.relative_to(self.out).as_posix() for path in self.out.rglob("*") if path.is_file()}
        for name, digest in listed.items():
            path = self.out / name
            if not path.is_file():
                findings.append(f"manifest lists a missing file: {name}")
            elif _sha(path) != digest:
                findings.append(f"{name} does not match its sha256")
        for name in sorted(actual - set(listed) - {"db-manifest.json"}):
            findings.append(f"file not in db-manifest.json: {name}")
        dump = (self.out / "db.sql").read_text(encoding="utf-8")
        restored = sqlite3.connect(":memory:")
        restored.row_factory = sqlite3.Row
        try:
            restored.executescript(dump)
            integrity = restored.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                findings.append(f"restored database integrity: {integrity}")
            if Projections.digest(restored) != Projections.digest(self.store.connection):
                findings.append("the restored projections differ from the source")
            counts = {table: _count(restored, table) for table in self.CONTRACT_TABLES}
            if counts != manifest.get("counts"):
                findings.append("the restored counts differ from the manifest")
            findings.extend(self._verify_content(restored))
        finally:
            restored.close()
        return BackupVerification(findings=tuple(findings), counts=counts)

    # -- writes ------------------------------------------------------------

    def _check_out(self) -> None:
        out = self.out.resolve()
        for root in self.LIVE_ROOTS:
            live = root.resolve()
            if out == live or out.is_relative_to(live) or live.is_relative_to(out):
                raise BackupError(f"refusing to write the backup inside the live tree: {out}")
        if out.exists() and any(out.iterdir()):
            raise BackupError(f"{out} is not an empty scratch directory")

    def _write_dump(self) -> None:
        dump = "\n".join(self.store.connection.iterdump()) + "\n"
        (self.out / "db.sql").write_text(dump, encoding="utf-8")

    def _write_content(self) -> None:
        for row in self.store.connection.execute("SELECT sha256, bytes, path FROM content ORDER BY sha256"):
            data = bytes(row["bytes"]) if row["bytes"] is not None else Path(row["path"]).read_bytes()
            directory = self.out / "content" / row["sha256"][:2]
            directory.mkdir(parents=True, exist_ok=True)
            (directory / row["sha256"]).write_bytes(data)

    def _write_events(self) -> None:
        by_year: dict[str, list[dict[str, Any]]] = {}
        for row in self.store.connection.execute("SELECT * FROM events ORDER BY seq"):
            event = dict(row)
            by_year.setdefault(str(event["recorded_at"])[:4], []).append(event)
        directory = self.out / "events"
        directory.mkdir(parents=True, exist_ok=True)
        for year, events in sorted(by_year.items()):
            lines = [json.dumps(event, sort_keys=True, default=str) for event in events]
            (directory / f"events-{year}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_catalogs(self) -> None:
        content = [
            {key: row[key] for key in ("sha256", "mime", "size", "created_at")}
            for row in self.store.connection.execute("SELECT * FROM content ORDER BY sha256")
        ]
        self._write_json("content.json", content)
        assets = [dict(row) for row in self.store.connection.execute("SELECT * FROM assets ORDER BY asset_id")]
        self._write_json("assets.json", assets)

    def _write_schema(self) -> None:
        (self.out / "schema").mkdir(parents=True, exist_ok=True)
        truth = Schema.TRUTH.read_text(encoding="utf-8")
        projections = Schema.PROJECTIONS.read_text(encoding="utf-8")
        (self.out / "schema" / "truth.sql").write_text(truth, encoding="utf-8")
        (self.out / "schema" / "projections.sql").write_text(projections, encoding="utf-8")
        migrations = [
            dict(row) for row in self.store.connection.execute("SELECT * FROM schema_migrations ORDER BY version")
        ]
        self._write_json("migrations.json", migrations)
        (self.out / "migrations").mkdir(parents=True, exist_ok=True)
        (self.out / self.SCHEMA_FILE).write_text(truth + "\n" + projections, encoding="utf-8")

    def _write_vocabulary(self) -> None:
        self._write_json(
            "vocabulary.json",
            {
                "item_types": sorted(ITEM_TYPES),
                "event_kinds": sorted(EVENT_KINDS),
                "item_statuses": sorted(ITEM_STATUSES),
                "record_statuses": sorted(RECORD_STATUSES),
                "relationship_kinds": sorted(RELATIONSHIP_KINDS),
                "date_precisions": sorted(PRECISIONS),
                "transcription_statuses": sorted(TRANSCRIPTION_STATUSES),
            },
        )
        (self.out / "payload-schemas").mkdir(parents=True, exist_ok=True)
        (self.out / "payload-schemas" / "README.md").write_text(
            "# Payload schemas\n\n"
            "The event payloads are the domain classes' wire forms, `payload_schema` 1:\n"
            "`Person`, `Place`, `Org`, `Theme` and `Relationship` (`tools/records.py`,\n"
            "`tools/theme.py`); the item sidecar plus its content shas and asset catalog\n"
            "(`loft/live/items.py`); the review session's attempts (`loft/live/review_row.py`);\n"
            "and the pipeline's batch/page/document states (`loft/live/batch_row.py`,\n"
            "`page_row.py`, `document_row.py`). The schema source is in `schema/`.\n",
            encoding="utf-8",
        )

    def _write_readme(self) -> None:
        (self.out / "README.md").write_text(
            "# The Loft — the operational backup\n\n"
            "This is the full system: the SQL dump, the content store, the event log, the\n"
            "schema and the manifests. It restores the DB; the human archive is a publication,\n"
            "not this backup.\n\n"
            "## Restore\n\n"
            "1. `sqlite3 restored.db < db.sql` — the dump is complete; the pragmas are the\n"
            "   connection's (`schema/truth.sql`).\n"
            "2. `content/` mirrors the content store; the dump carries the inline bytes. A\n"
            "   path-backed blob is re-hashed against its filename.\n"
            "3. `events/` is the audit log; `schema/` and `migrations/` are the DDL and the\n"
            "   migration records; `vocabulary.json` and `payload-schemas/` describe the\n"
            "   payloads.\n"
            "4. `PRAGMA integrity_check`; then `loft rebuild` and compare the projections.\n\n"
            "## Verify\n\n"
            "`db-manifest.json` records `exported_through`, every contract table's count, each\n"
            "entity's head hash and every file's sha256. `loft backup --verify` restores the\n"
            "dump into a scratch DB and compares the projections and the counts.\n",
            encoding="utf-8",
        )

    def _write_manifest(self, counts: dict[str, int], exported_through: int) -> None:
        heads: dict[str, str] = {}
        for row in self.store.connection.execute("SELECT entity_kind, entity_id, hash FROM events ORDER BY seq"):
            heads[f"{row['entity_kind']}/{row['entity_id']}"] = row["hash"]
        files = {
            path.relative_to(self.out).as_posix(): _sha(path)
            for path in self.out.rglob("*")
            if path.is_file() and path.name != "db-manifest.json"
        }
        self._write_json(
            "db-manifest.json",
            {
                "schema": 1,
                "exported_through": exported_through,
                "exported_at": datetime.now(UTC).isoformat(),
                "counts": counts,
                "heads": heads,
                "files": files,
            },
        )

    # -- helpers -----------------------------------------------------------

    def _count(self, table: str) -> int:
        return _count(self.store.connection, table)

    def _files(self) -> list[Path]:
        return [path for path in self.out.rglob("*") if path.is_file()]

    def _write_json(self, name: str, data: Any) -> None:
        path = self.out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    def _verify_content(self, restored: sqlite3.Connection) -> list[str]:
        findings: list[str] = []
        catalog = json.loads((self.out / "content.json").read_text(encoding="utf-8"))
        if len(catalog) != _count(restored, "content"):
            findings.append("content.json does not cover the restored content rows")
        for row in catalog:
            path = self.out / "content" / row["sha256"][:2] / row["sha256"]
            if not path.is_file():
                findings.append(f"content file {row['sha256']} is missing")
            elif _sha(path) != row["sha256"]:
                findings.append(f"content file {row['sha256']} does not match its sha")
            stored = restored.execute("SELECT bytes FROM content WHERE sha256 = ?", (row["sha256"],)).fetchone()
            if (
                stored is not None
                and stored["bytes"] is not None
                and hashlib.sha256(bytes(stored["bytes"])).hexdigest() != row["sha256"]
            ):
                findings.append(f"restored content {row['sha256']} does not match its bytes")
        return findings


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
