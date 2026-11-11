"""One entity a document's text names, as the identification pass proposes it.

The mention is the model's claim — the kind (person/place), the name the
document used, the standing record it matched (or null), and the document's
own words that name it — and its wire form (``{"kind": …, "name": …,
"match": …, "quote": …}``) is this class's dict. The ``quote`` is the
evidence the review shows; a mention without one is still a mention, and the
review can read the text itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.extraction import KINSHIP_TERMS


@dataclass(frozen=True)
class Mention:
    """One entity the document names — its kind, the name, the matched
    record, and the document's own words."""

    _KINDS = ("person", "place")

    _NAME_LIMIT = 80

    kind: str
    name: str
    match: str | None = None
    quote: str = ""

    def __post_init__(self) -> None:
        if self.kind not in Mention._KINDS:
            raise ValueError(f"mention kind {self.kind!r} is not one of {list(Mention._KINDS)}")
        if not self.name.strip():
            raise ValueError("a mention needs a name")
        if len(self.name.strip()) > Mention._NAME_LIMIT:
            raise ValueError(f"mention name is longer than {Mention._NAME_LIMIT} characters: {self.name!r}")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Mention:
        """The mention a wire entry states — a kind outside the vocabulary or
        a missing name makes the entry unusable."""
        kind = raw.get("kind")
        name = raw.get("name")
        if kind not in Mention._KINDS or not isinstance(name, str) or not name.strip():
            raise ValueError(f"mention needs a known kind and a name: {raw!r}")
        match = raw.get("match")
        return cls(
            kind=kind,
            name=name.strip(),
            match=match.strip() if isinstance(match, str) and match.strip() else None,
            quote=str(raw.get("quote", "")).strip(),
        )

    @classmethod
    def from_list(cls, raw: Any) -> tuple[Mention, ...]:
        """The mentions a wire list states — an entry the flow cannot place is
        dropped, never trusted. The list is deduplicated by kind and name
        (case-insensitive): one entity is one mention, so two readings of the
        same name cannot mint two proposals."""
        if not isinstance(raw, list):
            return ()
        seen: set[tuple[str, str]] = set()
        out: list[Mention] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                mention = cls.from_dict(entry)
            except ValueError:
                continue
            key = (mention.kind, mention.name.casefold())
            if key in seen:
                continue
            seen.add(key)
            out.append(mention)
        return tuple(out)

    def to_dict(self) -> dict[str, Any]:
        """The mention as its wire record."""
        return {"kind": self.kind, "name": self.name, "match": self.match, "quote": self.quote}

    def is_kinship_term(self) -> bool:
        """Is the name a bare kinship term — the writer's own relative, never a
        record the archive happens to alias?"""
        return self.kind == "person" and self.name.strip().lower() in KINSHIP_TERMS
