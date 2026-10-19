"""One row's transcript: the rows the model's answer covered, what the writing
is, what it says, and where it injects.

The page is read by showing the model the page with its rows numbered — one
number per row — and asking for the writing of each numbered row. The answer is
a list of segments, and this is one of them; its wire is that answer's own JSON
object: ``rows``, ``type``, ``transcript``, and ``injection_after`` where the
segment injects after a row (the key is absent otherwise). ``rows`` are the
numbered rows this transcript covers (a body row is one; a small aside may be
several), and ``text`` is "" when the model could not read them.

`from_dict` is the whole contract — a segment that is not an object, names no
rows, names a row outside the page or twice, carries a type outside the
vocabulary, carries no transcript, or names an injection point where there is
no injection is refused, never half-read. The reading's own row number is the
context `from_dict` needs: `index` is the segment's place in the answer (so a
refusal names WHICH segment) and `rows` is the highest row number the answer
was asked about (so a refusal can say a row is outside the page).

An EMPTY transcript is the model saying it cannot read that row. That is a fact
about the page, not a malformed answer: it is recorded as unread (no text, and
nothing unconfirmed is treated as the document's words) and the reviewer is
shown the row. A row ABSENT from the answer is still a refusal — that is a
partial read pretending to be a whole one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

KINDS = ("body", "injection", "marginalia")
"""What a segment of writing can be. `rule` is absent on purpose: a rule is a
detector artefact, not writing, and it carries no transcript."""


@dataclass(frozen=True)
class RowTranscript:
    """One row's transcript: what it says, what it is, and where it injects.

    `rows` are the numbered rows this transcript covers (a body row is one; a
    small aside may be several). `injection_after` is the row number an
    injection follows — the two are set together, always.
    """

    rows: tuple[int, ...]
    text: str  # "" when the model could not read the row: unread, never text
    kind: str
    injection_after: int | None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, index: int, rows: int) -> RowTranscript:
        """The transcript a model answer's record describes, read against the
        answer it came in (`index`) and the page it answers about (`rows`, the
        highest row number that was numbered)."""
        if not isinstance(raw, dict):
            raise ValueError(f"transcript {index} is not an object: {raw!r}")
        numbers = raw.get("rows")
        if not isinstance(numbers, list) or not numbers:
            raise ValueError(f"transcript {index} names no rows: {raw!r}")
        if any(not isinstance(number, int) or not 1 <= number <= rows for number in numbers):
            raise ValueError(f"transcript {index} names a row outside 1..{rows}: {numbers!r}")
        if len(set(numbers)) != len(numbers):
            raise ValueError(f"transcript {index} repeats a row: {numbers!r}")
        kind = raw.get("type")
        if kind not in KINDS:
            raise ValueError(f"reading {index}: unknown type {kind!r} (not {KINDS})")
        text = raw.get("transcript")
        if not isinstance(text, str):
            raise ValueError(f"transcript {index} has no transcript: {raw!r}")
        return cls(
            rows=tuple(numbers),
            text=text.strip(),
            kind=kind,
            injection_after=_injection_after(raw.get("injection_after"), kind, index=index, rows=rows),
        )

    def to_dict(self) -> dict[str, Any]:
        """The transcript as the answer's own record — the keys in the order the
        answer writes them, and no injection point on writing that injects
        nowhere."""
        out: dict[str, Any] = {"rows": list(self.rows), "type": self.kind, "transcript": self.text}
        if self.injection_after is not None:
            out["injection_after"] = self.injection_after
        return out


def _injection_after(after: Any, kind: str, *, index: int, rows: int) -> int | None:
    """The row an injection injects after: required for an injection, and
    forbidden on writing that injects nowhere."""
    if kind == "injection":
        if not isinstance(after, int) or not 1 <= after <= rows:
            raise ValueError(f"transcript {index} is an injection without a row to inject after: {after!r}")
        return after
    if after is not None:
        raise ValueError(f"transcript {index} is {kind!r} and must carry no injection point: {after!r}")
    return None
