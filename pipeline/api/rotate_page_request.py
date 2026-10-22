"""The rotate request.

The reviewer's orientation fix, stated as the DESIRED cumulative rotation in
quarter-turns — no image travels, the backend has it (the front and back end
are different boxes). 0 is a real intent: the reviewer's rotate-back to the
ORIGINAL orientation.

Anything that is not a quarter-turn count states no intent, and the page is
rotated by the default one quarter-turn — a malformed body must never rotate
a page by an unintended amount.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pipeline.api.sync import QUARTERS_PER_TURN


@dataclass(frozen=True)
class RotatePageRequest:
    """The orientation fix: the cumulative rotation the reviewer wants."""

    quarters: int = 1

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> RotatePageRequest:
        """The rotation a client states, or the default when it states none."""
        quarters = raw.get("quarters")
        if isinstance(quarters, int) and quarters in range(QUARTERS_PER_TURN):
            return cls(quarters=quarters)
        return cls()
