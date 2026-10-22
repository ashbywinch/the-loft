"""A route's refusal.

Every gated route answers a refusal with the same shape — ``{"ok": false,
"error": …}`` — so the app reads ONE error shape, never a per-route one. The
status code is the route's own (401 unauthenticated, 400 malformed, 403
cross-origin, 404 unknown, 422 unusable, 503 no model): it never rides this
record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorAnswer:
    """A route's refusal — the reason the client shows the family."""

    error: str

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {"ok": False, "error": self.error}
