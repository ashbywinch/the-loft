"""The review migration's decision mapping (TECHSPEC/11 §What maps).

The old review decision vocabulary is `attested`/`estimated`/`pending`/
`delete`. The target's is `attested`/`pending`/`delete`: an old `estimated`
was the reviewer's own recollection, so it becomes `attested` held with
recollection/possible, keeping the reviewer's own words; `attested` keeps its
evidence and is knowledge/certain.
"""

from __future__ import annotations

from typing import Any


class DecisionBases:
    """The two basis/confidence pairs the migration assigns."""

    KNOWN: dict[str, str] = {"basis": "knowledge", "confidence": "certain"}
    RECOLLECTED: dict[str, str] = {"basis": "recollection", "confidence": "possible"}


def decision_disposition(decision: str, basis: dict[str, Any] | None = None) -> tuple[str, dict[str, Any] | None]:
    """The target decision and its basis for one old review decision."""
    if decision == "estimated":
        return "attested", _with_basis(DecisionBases.RECOLLECTED, basis)
    if decision == "attested":
        return "attested", _with_basis(DecisionBases.KNOWN, basis)
    return decision, dict(basis) if basis else None


def _with_basis(assigned: dict[str, str], basis: dict[str, Any] | None) -> dict[str, Any]:
    """The assigned basis/confidence plus the reviewer's own words beside it."""
    out: dict[str, Any] = dict(assigned)
    for key, value in (basis or {}).items():
        out.setdefault(key, value)
    return out
