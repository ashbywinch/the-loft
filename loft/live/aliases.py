"""The alias projection — a merged id redirects to its survivor.

TECHSPEC/05 §18.2: a `merged` event names `merged_into`, and the `aliases`
projection resolves the loser to the survivor. The projection is a fold of
`merged`/`unmerged` events; B1 writes the merge half and read consumers use
it to exclude the loser from browse and the compatibility export.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Alias:
    """One merged id and the record it now resolves to."""

    loser_kind: str
    loser_id: str
    survivor_kind: str
    survivor_id: str
    event_seq: int


class Aliases:
    """The alias projection's read side (the write lives in the merge verb)."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def all(self) -> tuple[Alias, ...]:
        rows = self.connection.execute("SELECT * FROM aliases ORDER BY loser_kind, loser_id").fetchall()
        return tuple(
            Alias(
                loser_kind=row["loser_kind"],
                loser_id=row["loser_id"],
                survivor_kind=row["survivor_kind"],
                survivor_id=row["survivor_id"],
                event_seq=row["event_seq"],
            )
            for row in rows
        )

    def get(self, entity_kind: str, entity_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT survivor_id FROM aliases WHERE loser_kind = ? AND loser_id = ?", (entity_kind, entity_id)
        ).fetchone()
        return None if row is None else str(row["survivor_id"])

    def losers(self, entity_kind: str) -> frozenset[str]:
        rows = self.connection.execute("SELECT loser_id FROM aliases WHERE loser_kind = ?", (entity_kind,)).fetchall()
        return frozenset(str(row["loser_id"]) for row in rows)

    def write(
        self,
        *,
        loser_kind: str,
        loser_id: str,
        survivor_kind: str,
        survivor_id: str,
        event_seq: int,
    ) -> None:
        """Record one redirect (the merge verb's projection write)."""
        self.connection.execute(
            """INSERT INTO aliases (loser_kind, loser_id, survivor_kind, survivor_id, event_seq)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (loser_kind, loser_id) DO UPDATE SET
                 survivor_kind = excluded.survivor_kind,
                 survivor_id = excluded.survivor_id,
                 event_seq = excluded.event_seq""",
            (loser_kind, loser_id, survivor_kind, survivor_id, event_seq),
        )


class MemoryAliases:
    """The memory store's alias projection — the same surface, one dict."""

    def __init__(self, entries: dict[tuple[str, str], Alias]) -> None:
        self.entries = entries

    def all(self) -> tuple[Alias, ...]:
        return tuple(self.entries[key] for key in sorted(self.entries))

    def get(self, entity_kind: str, entity_id: str) -> str | None:
        alias = self.entries.get((entity_kind, entity_id))
        return None if alias is None else alias.survivor_id

    def losers(self, entity_kind: str) -> frozenset[str]:
        return frozenset(entity_id for kind, entity_id in self.entries if kind == entity_kind)

    def write(
        self,
        *,
        loser_kind: str,
        loser_id: str,
        survivor_kind: str,
        survivor_id: str,
        event_seq: int,
    ) -> None:
        self.entries[(loser_kind, loser_id)] = Alias(
            loser_kind=loser_kind,
            loser_id=loser_id,
            survivor_kind=survivor_kind,
            survivor_id=survivor_id,
            event_seq=event_seq,
        )
