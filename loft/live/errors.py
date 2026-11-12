"""The errors a caller can act on — no SQLite exception escapes the boundary.

TECHSPEC/08 §19.3: a stale write carries the current value, a uniqueness
collision is a Conflict, a missing record is NotFound, and a busy lock is
Busy. The surface decides between a retry, a merge and a message.
"""

from __future__ import annotations

from typing import Any


class LiveError(RuntimeError):
    """Base class for the live store's failures."""


class NotFound(LiveError):  # noqa: N818 — the TECHSPEC names this error
    """The requested record does not exist."""


class Conflict(LiveError):  # noqa: N818 — the TECHSPEC names this error
    """A uniqueness or append-only rule refused the change."""


class Busy(LiveError):  # noqa: N818 — the TECHSPEC names this error
    """Another writer holds the database lock."""


class StaleVersion(LiveError):  # noqa: N818 — the TECHSPEC names this error
    """The base version the caller supplied is no longer current."""

    def __init__(self, current: Any, base: int | None) -> None:
        super().__init__(f"stale version {base}; current is {current!r}")
        self.current = current
        self.base = base
