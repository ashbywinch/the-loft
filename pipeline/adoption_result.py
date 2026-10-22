"""What adopting one scan folder did: the registry file the record lives in,
and the outcome the caller reports.

The outcomes are one vocabulary — the same four words whichever step decided
them (an exact fingerprint match, a same-pile update, or a fresh record) — so
they are one type, and the result is one shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# ``new``: a fresh record; ``already-registered``: the folder is the record's
# own path; ``re-associated``: the folder moved and its content matched;
# ``content-changed``: the same pile with pages added/removed.
AdoptionOutcome = Literal["new", "already-registered", "re-associated", "content-changed"]


@dataclass(frozen=True)
class AdoptionResult:
    """Where an adoption landed, and what happened to the pile."""

    path: Path
    outcome: AdoptionOutcome
