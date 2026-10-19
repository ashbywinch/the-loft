"""The page's boxes: the composed box quads and the page size they sit in.

The detector composes one box per line of writing and persists them with the
page's pixel dimensions — the boxes.json artefact. That file is this class's
wire: `from_dict` reads it (refusing a file with no page size, or a "box" that
is not a polygon of [x, y] points), `to_dict` writes it. The page size is a
`PageSize` (`document/page_size.py`) and each box a `Box` polygon
(`document/trace.py`) — the shapes the rest of the row machinery measures in.
"""

from __future__ import annotations

from typing import Any

from document.page_size import PageSize
from document.trace import Box


class Boxes:
    """The page's boxes and the page size they are measured in — boxes.json."""

    def __init__(self, page: PageSize, boxes: list[Box]) -> None:
        self.page = page
        self.boxes = list(boxes)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Boxes:
        """The boxes a boxes.json holds: the page size plus one polygon per
        box, in page pixels."""
        records = raw.get("boxes")
        if not isinstance(records, list):
            raise ValueError("not a Boxes (no top-level 'boxes' list)")
        page = raw.get("page")
        if not isinstance(page, dict) or not {"width", "height"} <= set(page):
            raise ValueError("no page size — not a Boxes")
        boxes: list[Box] = []
        for index, box in enumerate(records):
            if not isinstance(box, list) or not box or not all(_is_point(point) for point in box):
                raise ValueError(f"boxes[{index}] — expected a polygon of [x, y] points")
            boxes.append(box)
        return cls(PageSize.from_dict(page), boxes)

    def to_dict(self) -> dict[str, Any]:
        """The boxes as the boxes.json artefact."""
        return {"page": self.page.to_dict(), "boxes": [list(box) for box in self.boxes]}


def _is_point(point: Any) -> bool:
    """Whether a value is one [x, y] point of a polygon."""
    return isinstance(point, list) and len(point) == 2 and all(isinstance(c, (int, float)) for c in point)
