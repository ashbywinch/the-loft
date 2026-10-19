"""The /api/assess request.

The page the contribution started from and the account so far — the model's
input for the assessment. The narrator is never read from here: the capture
API resolves it from the verified session, so a client-claimed name is
ignored.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tools.anchor import Anchor


@dataclass(frozen=True)
class AssessRequest:
    """The assessment request: the page, and the account told so far."""

    anchor: Anchor
    account: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AssessRequest:
        """The capture a client states — an absent anchor is the archive's
        default page, an absent account is an empty one."""
        return cls(anchor=Anchor.from_dict(raw.get("anchor", {})), account=str(raw.get("account", "")))
