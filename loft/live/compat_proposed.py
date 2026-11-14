"""The proposed-queue compatibility exporter — the old per-record queue files.

TECHSPEC/08 §19.4 and REWRITE-PLAN B3b: from the flip a proposal is a row in
the identity table (status `proposed`), but the old readers still list
`proposed/people|places/` and parse one file per record. After every identity
write this exporter writes a file for every proposed row — create-if-absent,
because the old queue is append-only — and removes the file whose row is
rejected or gone (the one delete the old store performed, the review's
reject). A promoted record keeps the file it was queued with: the projection
skips an id the table already holds.
"""

from __future__ import annotations

import json

from loft.live.protocols import IdentityStore
from tools.archive import Archive


class ProposedCompatibility:
    """Maintain the old proposed-queue files from the live rows."""

    def __init__(self, store: IdentityStore, archive: Archive) -> None:
        self.store = store
        self.archive = archive

    def write(self) -> tuple[str, ...]:
        """Write a file for every proposed row, remove one whose row is
        rejected or gone; return the queue paths touched, in write order."""
        touched: list[str] = []
        for directory, collection in (("people", self.store.people), ("places", self.store.places)):
            for record in collection.all():
                path = self._path(directory, record.id)
                if record.status == "proposed" and not self.archive.store.exists(path):
                    self.archive.store.write_new(path, json.dumps(record.to_dict(), indent=1, ensure_ascii=False))
                    touched.append(path)
            for path in self.archive.store.list(f"proposed/{directory}"):
                if not path.endswith(".json"):
                    continue  # a queue record is a .json file; anything else is not ours to remove
                current = collection.get(self._record_id(path))
                if current is None or current.status == "rejected":
                    self.archive.store.delete(path)
                    touched.append(path)
        return tuple(touched)

    @staticmethod
    def _path(directory: str, record_id: str) -> str:
        return f"proposed/{directory}/{record_id}.json"

    @staticmethod
    def _record_id(path: str) -> str:
        """The id a queue file names — its bare stem, never a path."""
        return path.rsplit("/", 1)[-1].removesuffix(".json")
