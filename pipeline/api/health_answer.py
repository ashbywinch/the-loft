"""The /api/health answer.

The liveness probe the deploy and the app read: the server is up, and whether
a model client is configured on it — a server without the AI still serves the
archive, it just cannot assess or investigate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HealthAnswer:
    """The health route's answer — up, with the AI or without it."""

    ai: bool

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {"ok": True, "ai": self.ai}
