"""The migration's precondition: a verified backup marker (TECHSPEC/11).

The marker is the backup procedure's claim that the archive was copied and
verified. Every importer checks it before reading a record, so an import can
never run against an unbacked-up tree.
"""

from __future__ import annotations

import json
from pathlib import Path

from loft.live.errors import LiveError


class BackupMarkerError(LiveError):
    """The migration refuses to run without a verified backup marker."""


def check_marker(marker: Path) -> None:
    """Refuse unless `marker` is a readable JSON file with `verified: true`."""
    if not marker.is_file():
        raise BackupMarkerError(f"no verified backup marker at {marker} — take the snapshot first")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BackupMarkerError(f"backup marker {marker} is unreadable: {error}") from error
    if payload.get("verified") is not True:
        raise BackupMarkerError(f"backup marker {marker} is not verified")
