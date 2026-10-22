"""One registry record as it sits on disk: the file it lives in and the batch
record it holds.

The registry's seam reads the records by their paths (a record's own path is
the user's folder, which is never what we write to), so the two travel
together — an entry is the file and the record in it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline.batch_record import BatchRecord


@dataclass(frozen=True)
class RegistryEntry:
    """A registry file and the batch record it holds."""

    path: Path
    record: BatchRecord
