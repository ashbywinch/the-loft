"""The row-adjustments answer.

The corrected rows the build produced from the reviewer's drawn lines — the
same rows the correction persisted beside the lines that made them, so the
surface renders exactly what the file holds — and the violations the same
traces hold (`Rows.validate`), so a drawing that caught no writing is named
to the person who drew it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RowAdjustmentsAnswer:
    """The row-adjustments route's answer: the page's corrected rows, and what
    the traces broke."""

    batch_id: str
    page: str
    rows: list[dict[str, Any]]
    violations: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {
            "ok": True,
            "batch_id": self.batch_id,
            "page": self.page,
            "rows": self.rows,
            "violations": list(self.violations),
        }
