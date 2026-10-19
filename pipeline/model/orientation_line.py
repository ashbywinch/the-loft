"""One line the orientation report located: its box and its direction.

The located line is the report's record (``{"index", "text", "box",
"degrees"}``), keyed to the line numbers of the transcription the model was
given — the layout's multi-direction assembly anchors on it. The line's own
text rides only when the report carries one: a no-known-text report holds
the model's re-reading of the line, a known-text report locates the text it
was given.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BOX_COORDINATE_COUNT = 4  # a box is [x0, y0, x1, y1]

# The directions a line of text may read at: upright, and the three quarter
# turns. A model answer outside the set is not a located line.
READING_DEGREES = (0, 90, 180, 270)


@dataclass(frozen=True)
class OrientationLine:
    """One located line: the transcription line's number, its box in
    NORMALIZED 0-1000 units (the numbers the model sent, verbatim), the
    degrees it reads at, and the line's own text when the report has one."""

    index: int
    box: list[float]
    degrees: int
    text: str | None = None

    @classmethod
    def of(cls, raw: Any, position: int, *, keep_text: bool = True) -> OrientationLine | None:
        """The located line one report entry holds — None when it carries no
        usable box or direction (the model's list is free-form: an unusable
        entry is dropped, never fatal). The line's number is the entry's own
        index, or its position in the list when the model omitted one.

        ``keep_text=False`` parses a fresh MODEL answer: the line's own text
        is left behind there, because the layout anchors on the transcription
        the model was given and a report's own re-reading varies between
        calls."""
        if not isinstance(raw, dict):
            return None
        box = raw.get("box")
        if not (isinstance(box, list) and len(box) == BOX_COORDINATE_COUNT):
            return None
        if raw.get("degrees") not in READING_DEGREES:
            return None
        index = raw.get("index")
        text = raw.get("text")
        return cls(
            int(index) if isinstance(index, int) else position,
            list(box),
            int(raw["degrees"]),
            str(text) if keep_text and isinstance(text, str) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """The located line as its report record (the text rides only when
        the line has one)."""
        out: dict[str, Any] = {"index": self.index, "box": self.box, "degrees": self.degrees}
        if self.text is not None:
            out["text"] = self.text
        return out
