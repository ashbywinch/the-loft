"""The contradiction a review turn found between the reviewer's words and
the archive's attested facts: the flag, and the attested fact that conflicts.

The check flags ONLY genuine conflicts with the attested facts — the wrong
person for an attested death, a disputed confirmed relationship — never a
different version of an unverified import guess, and never a fact the
archive simply does not have. Its wire form (``{"found": …, "detail": …}``)
is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Contradiction:
    """The verdict's contradiction check — whether one was found, and the
    attested fact it conflicts with (empty when none was found)."""

    found: str = ""
    detail: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Contradiction:
        """The check a wire record states — the flag normalized to the
        lowercase word the wire carries, the detail kept verbatim."""
        return cls(found=str(raw.get("found", "")).strip().lower(), detail=str(raw.get("detail", "")))

    def to_dict(self) -> dict[str, Any]:
        """The check as its wire record."""
        return {"found": self.found, "detail": self.detail}
