"""The interpreter model's answer to one pending date fact.

The narrator answered a date question in their own words; the model asserts the
value and precision the answer states, and the library validates both
(docs/coding-standards.md: the model asserts, the library parses). The answer is
matched to its fact by the verbatim text, so the text is the record's key, and
its wire form (``{"text": …, "value": …, "precision": …}``) is this class's
dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.dated_fact import DatedFact
from tools.parsed_phrase import asserted_date


@dataclass(frozen=True)
class FactAnswer:
    """One answer — the words the narrator used and the date the model read in
    them, before the library validated it."""

    text: str
    value: str | None = None
    precision: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("an answer needs the words it answered with")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FactAnswer:
        """The answer a wire entry states — an answer without the verbatim text
        has nothing to match its fact by, so it is no answer."""
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"answer needs the words it answered with: {raw!r}")
        value = raw.get("value")
        precision = raw.get("precision")
        return cls(
            text=text.strip(),
            value=value if isinstance(value, str) else None,
            precision=precision if isinstance(precision, str) else None,
        )

    @classmethod
    def from_list(cls, raw: Any) -> tuple[FactAnswer, ...]:
        """The answers a wire list states — entries without a verbatim text are
        dropped."""
        if not isinstance(raw, list):
            return ()
        out: list[FactAnswer] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                out.append(cls.from_dict(entry))
            except ValueError:
                continue
        return tuple(out)

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {"text": self.text, "value": self.value, "precision": self.precision}

    def dated(self) -> DatedFact | None:
        """The date the answer states, validated by the real parser — None when
        the parser cannot make sense of it (a person's word resolves it)."""
        return asserted_date(self.value, self.precision)
