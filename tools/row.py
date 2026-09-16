"""One line of writing: its words (indices into the page's) and its kind."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Row:
    """One line of writing: its words (indices into the page's) and its kind."""

    words: list[int] = field(default_factory=list)
    kind: str = "writing"  # "writing" or "interjection"

    _centres: float | None = field(default=None, init=False, repr=False)

    @property
    def centre(self) -> float:
        if self._centres is None:
            raise ValueError("Row has no centre until the page measures it")
        return self._centres
