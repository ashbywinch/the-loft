"""One link a record carries to another record: the id, the confirmation
status, and — where the evidence states one — the involvement date.

The reference is the archive's one link record: an item's people/places/
orgs/themes/items refs and a story's links are the same shape, and its wire
form (``{"id": …, "status": …}``, plus ``date`` where the text dates that
entity's involvement) is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from tools.dated_fact import DatedFact

# The link's confirmation status: proposed = guessed by an agent and awaiting
# the review; confirmed = the owner's verified word. An absent status is an
# asserted link with no review seam.
RefStatus = Literal["confirmed", "proposed"]
REF_STATUSES = ("confirmed", "proposed")


@dataclass(frozen=True)
class Ref:
    """A link to another record — the id, the status, the involvement date."""

    id: str
    status: RefStatus | None = None
    date: DatedFact | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], label: str = "ref") -> Ref:
        """The link a wire record states — ``label`` names the collection in
        the error (an item's people, a story's items)."""
        record_id = str(raw.get("id", "")).strip()
        if not record_id:
            raise ValueError(f"{label} ref missing id: {raw!r}")
        status = raw.get("status")
        if status is not None and status not in REF_STATUSES:
            raise ValueError(f"{label} ref has bad status: {raw!r}")
        date = raw.get("date")
        return cls(
            id=record_id,
            status=cast("RefStatus | None", status),
            date=DatedFact.from_dict(date, f"{label} ref date") if date else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """The link as its wire record — an absent status or date stays
        absent (an asserted link with no review seam carries no status)."""
        out: dict[str, Any] = {"id": self.id}
        if self.status is not None:
            out["status"] = self.status
        if self.date is not None:
            out["date"] = self.date.to_dict()
        return out
