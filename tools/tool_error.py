"""A tool result that says the call could not be answered: an unknown tool,
a missing argument, or an id the archive does not hold.

The error is fed back to the model as the tool's answer — never a crash and
never a silent empty result — so the model can correct its own call. The
shape the model reads (``{"error": …}``) is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolError:
    """A tool's refusal — the error saying why the call was not answered."""

    error: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ToolError:
        """The error a wire record states."""
        return cls(error=str(raw.get("error", "")))

    def to_dict(self) -> dict[str, Any]:
        """The error as its wire record."""
        return {"error": self.error}
