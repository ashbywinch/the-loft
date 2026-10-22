"""One file an item's sidecar references: a scan, a page image, or a
content file (the story text, the transcription).

The asset is the item's own record of what is filed in its folder — the
kind ("page", "story", "transcription"), the filename, and the caption the
reader shows — and its wire form (``{"kind": …, "file": …, "caption": …}``)
is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Asset:
    """One file of an item — its kind, its filename, its caption."""

    kind: str
    file: str
    caption: str = ""

    def __post_init__(self) -> None:
        if not self.kind.strip() or not self.file.strip():
            raise ValueError(f"asset needs kind and file: {self.kind!r}/{self.file!r}")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Asset:
        """The asset a wire record states."""
        return cls(
            kind=str(raw.get("kind", "")).strip(),
            file=str(raw.get("file", "")).strip(),
            caption=str(raw.get("caption", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """The asset as its wire record."""
        return {"kind": self.kind, "file": self.file, "caption": self.caption}
