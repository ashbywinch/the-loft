"""The review-state compatibility exporter — the old `imports.json` table.

TECHSPEC/08 §19.4 and REWRITE-PLAN B3: after a review write the old readers
(the projection's `imports.json`, the archive's session reads, the review hub)
must see the same table. The exporter rebuilds it from the live sessions — the
transcript, the decisions and the assistant's thinking text (restored from its
content sha) — and writes a new version only when it moved. The old writer is
append-only and versioned; `save_identity` owns the chain.
"""

from __future__ import annotations

from loft.live.protocols import ItemStore
from tools.archive import Archive
from tools.records import ImportsTable


class ImportsCompatibility:
    """Rebuild `imports.json` from the live review sessions."""

    def __init__(self, store: ItemStore, archive: Archive) -> None:
        self.store = store
        self.archive = archive

    def write(self) -> bool:
        """Write a new imports-table version when the store's sessions moved."""
        table = self.table()
        current = self.archive.get_identity("imports")
        if current is not None and current.to_dict() == table.to_dict():
            return False
        self.archive.save_identity("imports", table)
        return True

    def table(self) -> ImportsTable:
        """The old table's sessions, in their create order."""
        sessions = [
            session
            for session_id in self.store.reviews.session_ids()
            if (session := self.store.reviews.session(session_id)) is not None
        ]
        return ImportsTable(imports=tuple(sessions))
