"""An entity a story is about, as the assessment proposes it.

The extraction is the model's claim — the kind (person/place/theme/item), the
name it read in the account, the standing record it matched (or null), the
bucket that decides how the flow treats it, and the reason it gives — and its
wire form (``{"kind": …, "name": …, "match": …, "bucket": …, "reason": …}``) is
this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

KINDS = ("person", "place", "theme", "item")
BUCKETS = ("proposed", "question", "unresolved")

# A bare kinship term names the writer's own relative — never a match to a
# person record merely because that record carries the alias. The code strips
# the match deterministically: writer-relative resolution is a later seam
# (option C), not the model's guess (docs/coding-standards.md — deterministic
# checks beat model judgment).
KINSHIP_TERMS = frozenset(
    {
        "dad",
        "daddy",
        "father",
        "mum",
        "mummy",
        "mom",
        "mother",
        "mam",
        "grandma",
        "granny",
        "gran",
        "nana",
        "nanny",
        "grandad",
        "granddad",
        "grandpa",
        "grandfather",
        "grandmother",
        "aunt",
        "aunty",
        "auntie",
        "uncle",
        "sister",
        "brother",
        "cousin",
    }
)


@dataclass(frozen=True)
class Extraction:
    """One entity the story is about — its kind, the name the account used, the
    record it matched, the bucket, and the model's reason."""

    kind: str
    name: str
    match: str | None = None
    bucket: str = "unresolved"
    reason: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown extraction kind: {self.kind!r}")
        if not self.name.strip():
            raise ValueError("an extraction needs a name")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Extraction:
        """The extraction a wire entry states — its kind and name decide
        whether the entry is usable at all; the bucket and the match are
        validated against the known values."""
        kind = raw.get("kind")
        name = raw.get("name")
        if kind not in KINDS or not isinstance(name, str) or not name.strip():
            raise ValueError(f"extraction needs a known kind and a name: {raw!r}")
        bucket = raw.get("bucket") if raw.get("bucket") in BUCKETS else "unresolved"
        match = raw.get("match") if isinstance(raw.get("match"), str) else None
        return cls(kind=kind, name=name.strip(), match=match, bucket=bucket, reason=str(raw.get("reason", "")))

    @classmethod
    def from_list(cls, raw: Any) -> tuple[Extraction, ...]:
        """The extractions a wire list states — an entry the flow cannot place
        is dropped, never trusted (the model's junk and a hand-made request's
        both end here)."""
        if not isinstance(raw, list):
            return ()
        out: list[Extraction] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                out.append(cls.from_dict(entry))
            except ValueError:
                continue
        return tuple(out)

    def to_dict(self) -> dict[str, Any]:
        """The extraction as its wire record."""
        return {
            "kind": self.kind,
            "name": self.name,
            "match": self.match,
            "bucket": self.bucket,
            "reason": self.reason,
        }

    def is_kinship_term(self) -> bool:
        """Is the name a bare kinship term — the writer's own relative, never a
        record the archive happens to alias?"""
        return self.kind == "person" and self.name.strip().lower() in KINSHIP_TERMS

    def is_new_item(self) -> bool:
        """A specific artifact the story names that is not in the catalog — the
        one that deserves a "tell me more" question."""
        return self.kind == "item" and not self.match

    def unmatched(self) -> Extraction:
        """The same extraction with no match — the kinship strip: the term
        survives so the unnamed relative can be proposed for the writer to
        identify."""
        return replace(self, match=None)
