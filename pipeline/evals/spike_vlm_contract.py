"""Schema v1 of the VLM word-segmentation spike (milestone 3,
docs/PLAN/vlm-word-segmentation-spike.md).

The JSON contract: the VLM returns {"segments": [{id, type, transcript?,
word_ids, injection_point?}]} over the numbered render. This module validates
it deterministically — a garbage response is a loud failure, never a silent
merge (the plan's reconciliation), and it builds the prompt from the segment
definition the user pointed to (L3: a segment is a logically consecutive
run of writing).

Pure: no model call, no network, no image — the numbered render is the
caller's; here live the words of the contract, and the `Segment` record that
owns this wire.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

VALID_TYPES = ("body", "injection", "marginalia", "rule")

_FENCE = "```"  # the markdown fence the model sometimes wraps its JSON in


class ContractError(ValueError):
    """The VLM's answer violates the schema — fail loudly, never merge."""


@dataclass(frozen=True)
class Segment:
    """One segment of the VLM's answer, judged against the render's numbered
    boxes: the id, the type, the word ids it read, its transcript (None for a
    rule that states none) and the word an injection lands after.

    The class owns the contract's wire record — ``{"id", "type", "word_ids",
    "transcript"?, "injection_point": {"after": <word id>}?}``: ``from_dict``
    reads it and is the whole per-segment contract (every rule both ways),
    ``to_dict`` writes it back.
    """

    id: str
    type: str
    transcript: str | None
    word_ids: tuple[int, ...]
    injection_after: int | None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], universe: int) -> Segment:
        """One wire record as a segment, or a loud refusal naming what is wrong
        with it. ``universe`` is the render's word count: the id space every
        word id and every injection point must land in."""
        segment_id = raw.get("id")
        if not isinstance(segment_id, str) or not segment_id:
            raise ContractError(f"a segment has no id: {raw!r}")
        kind = raw.get("type")
        if kind not in VALID_TYPES:
            raise ContractError(f"{segment_id}: unknown type {kind!r} (not {VALID_TYPES})")
        return cls(
            id=segment_id,
            type=kind,
            transcript=_transcript(segment_id, kind, raw.get("transcript")),
            word_ids=_word_ids(segment_id, raw.get("word_ids"), universe),
            injection_after=_injection_point(segment_id, kind, raw.get("injection_point"), universe),
        )

    def to_dict(self) -> dict[str, Any]:
        """The segment as the contract's wire record — the keys the model sent,
        and only those."""
        out: dict[str, Any] = {"id": self.id, "type": self.type}
        if self.transcript is not None:
            out["transcript"] = self.transcript
        out["word_ids"] = list(self.word_ids)
        if self.injection_after is not None:
            out["injection_point"] = {"after": self.injection_after}
        return out


def _word_ids(segment_id: str, raw_ids: Any, universe: int) -> tuple[int, ...]:
    """The word ids a segment read, or a refusal naming what is wrong with
    them: not a list of ints, one outside the render, one twice."""
    if not isinstance(raw_ids, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in raw_ids):
        raise ContractError(f"{segment_id}: word_ids must be a list of ints, got {raw_ids!r}")
    if not all(1 <= v <= universe for v in raw_ids):
        raise ContractError(f"{segment_id}: a word id outside 1..{universe}")
    if len(raw_ids) != len(set(raw_ids)):
        raise ContractError(f"{segment_id}: duplicate word ids {raw_ids!r}")
    return tuple(raw_ids)


def _injection_point(segment_id: str, kind: str, raw_point: Any, universe: int) -> int | None:
    """The injection's required point (the word id the injection lands after),
    or None for non-injections — which FORBID the field outright."""
    if kind == "injection":
        if not isinstance(raw_point, dict):
            raise ContractError(f"{segment_id}: an injection REQUIRES injection_point")
        candidate = raw_point.get("after")
        if not isinstance(candidate, int) or isinstance(candidate, bool) or not 1 <= candidate <= universe:
            raise ContractError(
                f"{segment_id}: injection_point.after must be a word id in 1..{universe}, got {candidate!r}"
            )
        return candidate
    if raw_point is not None:
        raise ContractError(f"{segment_id}: only an injection may carry injection_point ({raw_point!r})")
    return None


def _transcript(segment_id: str, kind: str, raw_transcript: Any) -> str | None:
    """The segment's transcript: a rule may state none (None — the wire omits
    the key); every other type must state a non-empty one."""
    if kind == "rule":
        if raw_transcript is not None and not isinstance(raw_transcript, str):
            raise ContractError(f"{segment_id}: a rule's transcript, when present, is a string")
        return raw_transcript if isinstance(raw_transcript, str) else None
    if not isinstance(raw_transcript, str) or not raw_transcript:
        raise ContractError(f"{segment_id}: missing transcript")
    return raw_transcript


def _segments_of(answer: str) -> list[Any]:
    """The answer's raw segments, or a refusal: the model sometimes wraps its
    JSON in a markdown fence, and the envelope must be
    ``{"segments": [...]}``."""
    stripped = answer.strip()
    if stripped.startswith(_FENCE):
        lines = stripped.splitlines()
        lines = lines[1:] if lines[0].strip().startswith(_FENCE) else lines
        stripped = "\n".join(line for line in lines if not line.strip().startswith(_FENCE)).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ContractError(f"the answer is not JSON: {answer[:200]!r}") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("segments"), list):
        raise ContractError(f"the answer has no segments list: {answer[:200]!r}")
    return parsed["segments"]


def parse_answer(answer: str, universe: int) -> list[Segment]:
    """The contract's reader: the model's answer as its segments, every one
    judged against the render universe (see ``Segment``). An answer with no
    segments, and an id claimed twice, fail loudly here.

    This module reads its own answer because the wire is the render's WORD-id
    contract; document.transcript's parser speaks the product's ROW contract.
    """
    raw_segments = _segments_of(answer)
    if not raw_segments:
        raise ContractError("no segments in the answer")
    segments: list[Segment] = []
    claimed: set[str] = set()
    for raw in raw_segments:
        segment = Segment.from_dict(raw, universe)
        if segment.id in claimed:
            raise ContractError(f"duplicate segment id: {segment.id!r}")
        claimed.add(segment.id)
        segments.append(segment)
    return segments


@dataclass(frozen=True)
class Reconciliation:
    """The plan's reconciliation: which segment claimed each rendered word, and
    the problems the claims raised. A perfect answer has no problems; a gap or
    a double is a visible failure, never a silent merge."""

    assignment: dict[int, str]
    problems: list[str]


def reconcile(answers: list[Segment], universe: int) -> Reconciliation:
    """Every rendered word in exactly one non-rule segment: set equality minus
    the rule ids (the plan's reconciliation)."""
    assignment: dict[int, str] = {}
    problems: list[str] = []
    rule_ids: set[int] = set()
    for answer in answers:
        for word_id in answer.word_ids:
            if answer.type == "rule":
                rule_ids.add(word_id)
                continue
            if word_id in assignment:
                problems.append(f"word {word_id} in both {assignment[word_id]} and {answer.id}")
            else:
                assignment[word_id] = answer.id
    missing = sorted(set(range(1, universe + 1)) - set(assignment) - rule_ids)
    if missing:
        problems.append(f"unassigned words: {missing[:20]}{'...' if len(missing) > 20 else ''}")
    return Reconciliation(assignment, problems)


_SYSTEM_LINES = (
    "You segment a scanned letter into its segments of writing. The image shows the "
    "letter with every detected word boxed and numbered; the number on a box IS its "
    "word id.",
    "",
    "A segment is the longest run of text that belongs together — a logically "
    "consecutive run of writing. It ends where the writing logically separates: a "
    "line break, a column, a margin annotation, an insertion, a distinct hand. A "
    "paragraph and a 'yours sincerely' after it are never one segment; a body line "
    "and a marginal note are never one segment.",
    "",
    "The segment types:",
    "- body: the running text, one segment per line",
    "- injection: text meant to be inserted into other text (a caret, text squeezed "
    'above a line). The JSON REQUIRES injection_point: {"after": <word id>} — the '
    "word the caret follows.",
    "- marginalia: a note with NO injection point, and the JSON must NOT carry one",
    "- rule: an underline or flourish the detector found — it needs no transcript",
    "",
    "Transcribe each segment verbatim, word by word, reading the boxes. A word the "
    "writer crossed out is transcribed ~~word~~ (double tilde); a word the writer "
    "underlined is ~word~ (single tilde). The markers are content: never drop them, "
    "never type them literally as text.",
    "",
    "Reply with JSON only:",
    '{"segments": [',
    '  {"id": "seg-1", "type": "body", "transcript": "London Opera Centre", "word_ids": [129, 130, 131, 135, 138]},',
    '  {"id": "seg-2", "type": "injection", "transcript": "my dear", '
    '"injection_point": {"after": 147}, "word_ids": [152, 153]},',
    '  {"id": "seg-3", "type": "marginalia", "transcript": "Send this first", "word_ids": [160]},',
    '  {"id": "seg-4", "type": "rule", "word_ids": [151]}',
    "]}",
    "No prose before or after the JSON.",
)

SYSTEM_PROMPT = "\n".join(_SYSTEM_LINES)


def user_prompt(universe: int) -> str:
    """The attempt's user message: the scope of the task in the render's
    numbers, so the model knows the id universe it must cover."""
    return (
        f"The image shows the letter with every detected word boxed and numbered 1..{universe}. "
        "Return every writing segment: its type, its transcript, and the word ids of the boxes it contains."
    )
