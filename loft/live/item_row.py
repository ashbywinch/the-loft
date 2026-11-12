"""The item projection's row mapping — the domain type owns no SQL.

TECHSPEC/05 §18.4: the item's scalar fields become columns, the small nested
structures JSON columns, its refs/assets/content child rows, and the shared
version/event columns carry its position in the log. The content bytes live
in the content store; `item_content` holds the sha and the trust.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import sqlite3
from dataclasses import dataclass, replace
from typing import Any, ClassVar

from loft.live.errors import Conflict, StaleVersion
from loft.live.identity_map import date_value, disposition_of
from loft.live.person_row import RowPosition
from tools.asset import Asset
from tools.dated_fact import DatedFact
from tools.records import Item
from tools.ref import Ref


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class ItemRef:
    """One item → entity link, with the disposition and basis it was held with."""

    kind: str
    ref_id: str
    status: str
    date: DatedFact | None = None
    basis: dict[str, str] | None = None


@dataclass(frozen=True)
class ItemAsset:
    """One item → asset edge: the kind, the file name, the caption, the order."""

    asset_id: str
    kind: str
    file: str
    caption: str
    ordinal: int


@dataclass(frozen=True)
class AssetRecord:
    """One file in the asset catalog — bytes stay on disk, the row names them."""

    asset_id: str
    sha256: str
    kind: str
    mime: str
    size: int
    path: str
    derivative_of: str | None = None
    event_seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        """The catalog entry as the event payload's reference."""
        out: dict[str, Any] = {
            "asset_id": self.asset_id,
            "sha256": self.sha256,
            "kind": self.kind,
            "mime": self.mime,
            "size": self.size,
            "path": self.path,
        }
        if self.derivative_of is not None:
            out["derivative_of"] = self.derivative_of
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AssetRecord:
        return cls(
            asset_id=str(raw["asset_id"]),
            sha256=str(raw["sha256"]),
            kind=str(raw["kind"]),
            mime=str(raw["mime"]),
            size=int(raw["size"]),
            path=str(raw["path"]),
            derivative_of=raw.get("derivative_of"),
        )


@dataclass(frozen=True)
class ItemContent:
    """One item's current content kind, its sha, and whether it is trusted."""

    kind: str
    sha256: str
    trust: str

    def to_dict(self) -> dict[str, str]:
        return {"sha256": self.sha256, "trust": self.trust}

    @classmethod
    def from_dict(cls, kind: str, raw: dict[str, str]) -> ItemContent:
        return cls(kind=kind, sha256=str(raw["sha256"]), trust=str(raw["trust"]))


class ItemRow:
    """The item rows: the item, its refs, its assets and its content."""

    REF_KINDS: ClassVar[dict[str, str]] = {
        "people": "person",
        "places": "place",
        "orgs": "org",
        "themes": "theme",
        "items": "item",
    }

    REF_ACCESSORS: ClassVar[dict[str, str]] = {
        "people": "people_refs",
        "places": "place_refs",
        "orgs": "org_refs",
        "themes": "theme_refs",
        "items": "item_refs",
    }

    MAPPED: ClassVar[frozenset[str]] = frozenset(
        {
            "id",
            "type",
            "title",
            "date",
            "date2",
            "date_precision",
            "status",
            "source",
            "description",
            "provenance",
            "sensitive",
            "created",
            "identified",
            "date_mentions",
            "people",
            "places",
            "orgs",
            "themes",
            "items",
            "assets",
            "supersedes",
        }
    )

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "item_id",
        "type",
        "title",
        "date_json",
        "date",
        "date2",
        "date_precision",
        "status",
        "source",
        "description",
        "provenance",
        "sensitive",
        "created",
        "identified",
        "date_mentions_json",
        "extra_json",
        "version",
        "event_no",
        "event_seq",
        "updated_at",
    )

    @classmethod
    def asset_id(cls, item_id: str, file: str) -> str:
        """The asset's stable id — its item and its file name, never a sha."""
        return f"{item_id}/{file}"

    @classmethod
    def asset_path(cls, item_id: str, file: str) -> str:
        """Where the bytes are today: the archive-relative item folder. The
        exporter re-homes them in A8; the import records where it read them."""
        return f"assets/{item_id}/{file}"

    @classmethod
    def to_values(cls, item: Item, position: RowPosition) -> tuple[Any, ...]:
        """The column values for one item row, in `items`' column order."""
        raw = item.raw
        date = item.date
        precision = item.date_precision
        date_json = _json(date_value(date, precision, raw.get("date2"))) if date else None
        extra = {key: value for key, value in raw.items() if key not in cls.MAPPED}
        mentions = raw.get("date_mentions")
        return (
            item.id,
            item.type,
            item.title,
            date_json,
            date or None,
            str(raw.get("date2") or "") or None,
            precision or None,
            item.status,
            str(raw.get("source") or "") or None,
            str(raw.get("description") or "") or None,
            str(raw.get("provenance") or "") or None,
            1 if item.sensitive else 0,
            str(raw.get("created") or "") or None,
            1 if item.identified else 0,
            _json(mentions) if mentions else None,
            _json(extra) if extra else None,
            position.version,
            position.event_no,
            position.event_seq,
            position.updated_at,
        )

    @classmethod
    def refs(cls, item: Item) -> tuple[ItemRef, ...]:
        """The item's links, mapped to the disposition + basis and deduped by
        id — the projection's key is (item, kind, id), so a repeated link is
        the same link."""
        out: list[ItemRef] = []
        for plural, kind in cls.REF_KINDS.items():
            seen: set[str] = set()
            for ref in getattr(item, cls.REF_ACCESSORS[plural]):
                if ref.id in seen:
                    continue
                seen.add(ref.id)
                status, basis = _disposition(ref)
                out.append(ItemRef(kind=kind, ref_id=ref.id, status=status, date=ref.date, basis=basis))
        return tuple(out)

    @classmethod
    def assets(cls, item: Item, catalog: tuple[AssetRecord, ...]) -> tuple[ItemAsset, ...]:
        """The item's asset edges, in sidecar order; every one has a catalog row."""
        by_file = {record.asset_id: record for record in catalog}
        out: list[ItemAsset] = []
        for ordinal, asset in enumerate(item.assets):
            asset_id = cls.asset_id(item.id, asset.file)
            if asset_id not in by_file:
                raise Conflict(f"item {item.id} has no asset catalog row for {asset.file}")
            out.append(
                ItemAsset(asset_id=asset_id, kind=asset.kind, file=asset.file, caption=asset.caption, ordinal=ordinal)
            )
        return tuple(out)

    @classmethod
    def catalog_entry(cls, item_id: str, asset: Asset, data: bytes, event_seq: int) -> AssetRecord:
        """The catalog row for one sidecar asset, computed from its bytes."""
        mime = mimetypes.guess_type(asset.file)[0] or "application/octet-stream"
        return AssetRecord(
            asset_id=cls.asset_id(item_id, asset.file),
            sha256=hashlib.sha256(data).hexdigest(),
            kind=asset.kind,
            mime=mime,
            size=len(data),
            path=cls.asset_path(item_id, asset.file),
            event_seq=event_seq,
        )


@dataclass(frozen=True)
class ItemState:
    """One item row and its child rows — the aggregate the projection writes."""

    item: Item
    position: RowPosition
    refs: tuple[ItemRef, ...]
    assets: tuple[ItemAsset, ...]
    contents: tuple[ItemContent, ...]
    catalog: tuple[AssetRecord, ...]


class ItemProjection:
    """One connection's item rows: the reader and the guarded writer."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def current_version(self, item_id: str) -> int | None:
        row = self.connection.execute("SELECT version FROM items WHERE item_id = ?", (item_id,)).fetchone()
        return None if row is None else int(row["version"])

    def get(self, item_id: str) -> Item | None:
        """The item a projection row holds, with its refs and assets, or None."""
        row = self.connection.execute("SELECT * FROM items WHERE item_id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        raw: dict[str, Any] = json.loads(row["extra_json"] or "{}")
        raw["id"] = row["item_id"]
        raw["type"] = row["type"]
        raw["title"] = row["title"]
        raw["status"] = row["status"]
        if row["date"] is not None:
            raw["date"] = row["date"]
        if row["date2"] is not None:
            raw["date2"] = row["date2"]
        if row["date_precision"] is not None:
            raw["date_precision"] = row["date_precision"]
        for field_name in ("source", "description", "provenance", "created"):
            if row[field_name] is not None:
                raw[field_name] = row[field_name]
        if row["sensitive"]:
            raw["sensitive"] = True
        if row["identified"]:
            raw["identified"] = True
        if row["date_mentions_json"] is not None:
            raw["date_mentions"] = json.loads(row["date_mentions_json"])
        refs = self.refs(item_id)
        for plural, kind in ItemRow.REF_KINDS.items():
            matching: list[dict[str, Any]] = []
            for ref in refs:
                if ref.kind != kind:
                    continue
                entry: dict[str, Any] = {"id": ref.ref_id, "status": ref.status}
                if ref.date is not None:
                    entry["date"] = ref.date.to_dict()
                matching.append(entry)
            if matching:
                raw[plural] = matching
        assets = self.assets(item_id)
        if assets:
            raw["assets"] = [{"kind": asset.kind, "file": asset.file, "caption": asset.caption} for asset in assets]
        return replace(Item.from_dict(raw), version=row["version"])

    def refs(self, item_id: str) -> tuple[ItemRef, ...]:
        rows = self.connection.execute(
            """SELECT ref_kind, ref_id, status, date, date2, date_precision, basis_json
               FROM item_refs WHERE item_id = ? ORDER BY rowid""",
            (item_id,),
        ).fetchall()
        return tuple(
            ItemRef(
                kind=row["ref_kind"],
                ref_id=row["ref_id"],
                status=row["status"],
                date=(
                    DatedFact.from_dict(
                        {
                            "date": row["date"],
                            "precision": row["date_precision"] or "exact",
                            **({"date2": row["date2"]} if row["date2"] else {}),
                        }
                    )
                    if row["date"]
                    else None
                ),
                basis=json.loads(row["basis_json"]) if row["basis_json"] else None,
            )
            for row in rows
        )

    def assets(self, item_id: str) -> tuple[ItemAsset, ...]:
        rows = self.connection.execute(
            """SELECT edge.asset_id, edge.kind, edge.caption, edge.ordinal, asset.path
               FROM item_assets edge LEFT JOIN assets asset ON asset.asset_id = edge.asset_id
               WHERE edge.item_id = ? ORDER BY edge.ordinal""",
            (item_id,),
        ).fetchall()
        return tuple(
            ItemAsset(
                asset_id=row["asset_id"],
                kind=row["kind"],
                file=(row["path"] or row["asset_id"]).rsplit("/", 1)[-1],
                caption=row["caption"] or "",
                ordinal=row["ordinal"],
            )
            for row in rows
        )

    def contents(self, item_id: str) -> tuple[ItemContent, ...]:
        rows = self.connection.execute(
            "SELECT kind, sha256, trust FROM item_content WHERE item_id = ? ORDER BY rowid",
            (item_id,),
        ).fetchall()
        return tuple(ItemContent(kind=row["kind"], sha256=row["sha256"], trust=row["trust"]) for row in rows)

    def asset(self, asset_id: str) -> AssetRecord | None:
        row = self.connection.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        if row is None:
            return None
        return AssetRecord(
            asset_id=row["asset_id"],
            sha256=row["sha256"],
            kind=row["kind"],
            mime=row["mime"],
            size=row["size"],
            path=row["path"],
            derivative_of=row["derivative_of"],
            event_seq=row["event_seq"],
        )

    def write(self, state: ItemState, *, base: int | None) -> None:
        """Upsert the item and replace its child rows; a zero-row upsert is stale."""
        values = ItemRow.to_values(state.item, state.position)
        placeholders = ", ".join("?" for _ in values)
        assignments = ", ".join(f"{column} = excluded.{column}" for column in ItemRow.COLUMNS if column != "item_id")
        cursor = self.connection.execute(
            f"""INSERT INTO items ({", ".join(ItemRow.COLUMNS)}) VALUES ({placeholders})
                ON CONFLICT (item_id) DO UPDATE SET {assignments}
                WHERE items.version IS ?""",
            (*values, base),
        )
        if cursor.rowcount == 0:
            raise StaleVersion(current=self.get(state.item.id), base=base)
        self._write_catalog(state.catalog)
        self._write_refs(state.item.id, state.refs, state.position.event_seq)
        self._write_assets(state.item.id, state.assets)
        self._write_contents(state.item.id, state.contents)

    def _write_catalog(self, catalog: tuple[AssetRecord, ...]) -> None:
        for record in catalog:
            existing = self.connection.execute(
                "SELECT sha256, kind, mime, size, path FROM assets WHERE asset_id = ?",
                (record.asset_id,),
            ).fetchone()
            if existing is not None:
                stored = (existing["sha256"], existing["kind"], existing["mime"], existing["size"], existing["path"])
                wanted = (record.sha256, record.kind, record.mime, record.size, record.path)
                if stored != wanted:
                    raise Conflict(f"asset {record.asset_id} exists with different bytes")
                continue
            self.connection.execute(
                """INSERT INTO assets (asset_id, sha256, kind, mime, size, path, derivative_of, event_seq)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.asset_id,
                    record.sha256,
                    record.kind,
                    record.mime,
                    record.size,
                    record.path,
                    record.derivative_of,
                    record.event_seq,
                ),
            )

    def _write_refs(self, item_id: str, refs: tuple[ItemRef, ...], event_seq: int) -> None:
        self.connection.execute("DELETE FROM item_refs WHERE item_id = ?", (item_id,))
        for ref in refs:
            date = ref.date
            self.connection.execute(
                """INSERT INTO item_refs (item_id, ref_kind, ref_id, status, date_json, date, date2,
                                          date_precision, basis_json, event_seq)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id,
                    ref.kind,
                    ref.ref_id,
                    ref.status,
                    _json(date_value(date.date, date.precision, date.date2)) if date else None,
                    date.date if date else None,
                    date.date2 if date and date.date2 else None,
                    date.precision if date else None,
                    _json(ref.basis),
                    event_seq,
                ),
            )

    def _write_assets(self, item_id: str, assets: tuple[ItemAsset, ...]) -> None:
        self.connection.execute("DELETE FROM item_assets WHERE item_id = ?", (item_id,))
        for asset in assets:
            self.connection.execute(
                """INSERT INTO item_assets (item_id, asset_id, kind, caption, ordinal)
                   VALUES (?, ?, ?, ?, ?)""",
                (item_id, asset.asset_id, asset.kind, asset.caption, asset.ordinal),
            )

    def _write_contents(self, item_id: str, contents: tuple[ItemContent, ...]) -> None:
        self.connection.execute("DELETE FROM item_content WHERE item_id = ?", (item_id,))
        for content in contents:
            self.connection.execute(
                "INSERT INTO item_content (item_id, kind, sha256, trust) VALUES (?, ?, ?, ?)",
                (item_id, content.kind, content.sha256, content.trust),
            )


def _disposition(ref: Ref) -> tuple[str, dict[str, str]]:
    """The ref's old status as the live disposition + basis (the A3 mapping)."""
    return disposition_of(ref.status)
