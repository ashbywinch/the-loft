"""One region the orientation report flagged: a block running in its own
direction.

The hint is the model's own record (``{"region", "degrees", "approx_box"}``,
the shape its prompt documents). Only its direction is consumed today — a
page is multi-direction when any hint disagrees with the page's dominant
angle — so the fields the model omits stay omitted on the way out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.model.orientation_line import READING_DEGREES


@dataclass(frozen=True)
class OrientationHint:
    """One flagged region: the degrees its text reads at, its short name,
    and the region's approximate box in NORMALIZED 0-1000 units when the
    model gave one."""

    degrees: int
    region: str | None = None
    approx_box: list[float] | None = None

    def __post_init__(self) -> None:
        if self.degrees not in READING_DEGREES:
            raise ValueError(f"a region reads at one of {READING_DEGREES} degrees, got {self.degrees}")

    @classmethod
    def of(cls, raw: Any) -> OrientationHint | None:
        """The hint a raw report entry holds — None when it is not a record
        with a readable direction."""
        if not isinstance(raw, dict) or raw.get("degrees") not in READING_DEGREES:
            return None
        box = raw.get("approx_box")
        region = raw.get("region")
        return cls(
            degrees=int(raw["degrees"]),
            region=None if region is None else str(region),
            approx_box=list(box) if isinstance(box, list) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """The hint as its report record (a field the model omitted stays
        omitted)."""
        out: dict[str, Any] = {"degrees": self.degrees}
        if self.region is not None:
            out["region"] = self.region
        if self.approx_box is not None:
            out["approx_box"] = self.approx_box
        return out
