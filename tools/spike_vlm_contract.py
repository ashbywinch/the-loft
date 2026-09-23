"""Schema v1 of the VLM word-segmentation spike (milestone 3,
docs/PLAN/vlm-word-segmentation-spike.md).

The JSON contract: the VLM returns {"segments": [{id, type, transcript?,
word_ids, injection_point?}]} over the numbered render. This module validates
it deterministically — a garbage response is a loud failure, never a silent
merge (the plan's reconciliation), and it builds the prompt from the segment
definition the user pointed to (L3 as amended 2026-09-09: a segment is a
logically consecutive run of writing).

Pure: no model call, no network, no image — the numbered render is the
caller's; here live the words of the contract.
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
class SegmentAnswer:
    """One validated segment the VLM returned: its words, type, transcript
    and injection point, in the render's id space (the numbered boxes)."""

    id: str
    type: str
    transcript: str
    word_ids: tuple[int, ...]
    injection_after: int | None


def parse_answer(text: str) -> list[dict[str, Any]]:
    """The model's JSON answer (fence-tolerant) as the segments list."""
    stripped = text.strip()
    if stripped.startswith(_FENCE):
        lines = stripped.splitlines()
        lines = lines[1:] if lines[0].strip().startswith(_FENCE) else lines
        stripped = "\n".join(line for line in lines if not line.strip().startswith(_FENCE)).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ContractError(f"the answer is not JSON: {text[:200]!r}") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("segments"), list):
        raise ContractError(f"the answer has no segments list: {text[:200]!r}")
    return parsed["segments"]


def validate_segments(raw_segments: list[dict[str, Any]], universe: int) -> list[SegmentAnswer]:
    """The structural contract, every rule both ways:
    - the type is one of body/injection/marginalia/rule;
    - word_ids are ints in 1..N, unique within the segment;
    - injection REQUIRES injection_point.after (a word id); every other type
      FORBIDS injection_point;
    - transcripts are strings; a rule may omit its transcript."""
    if not raw_segments:
        raise ContractError("no segments in the answer")
    answers: list[SegmentAnswer] = []
    seen_ids: set[str] = set()
    for entry in raw_segments:
        segment_id = entry.get("id")
        if not isinstance(segment_id, str) or not segment_id:
            raise ContractError(f"a segment has no id: {entry!r}")
        if segment_id in seen_ids:
            raise ContractError(f"duplicate segment id: {segment_id!r}")
        seen_ids.add(segment_id)

        kind = entry.get("type")
        if kind not in VALID_TYPES:
            raise ContractError(f"{segment_id}: unknown type {kind!r} (not {VALID_TYPES})")
        assert isinstance(kind, str)

        raw_ids = entry.get("word_ids")
        if not isinstance(raw_ids, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in raw_ids):
            raise ContractError(f"{segment_id}: word_ids must be a list of ints, got {raw_ids!r}")
        if not all(1 <= v <= universe for v in raw_ids):
            raise ContractError(f"{segment_id}: a word id outside 1..{universe}")
        if len(raw_ids) != len(set(raw_ids)):
            raise ContractError(f"{segment_id}: duplicate word ids {raw_ids!r}")
        word_ids = tuple(raw_ids)

        point = entry.get("injection_point")
        after: int | None = None
        if kind == "injection":
            if not isinstance(point, dict):
                raise ContractError(f"{segment_id}: an injection REQUIRES injection_point")
            candidate = point.get("after")
            if not isinstance(candidate, int) or isinstance(candidate, bool) or not 1 <= candidate <= universe:
                raise ContractError(
                    f"{segment_id}: injection_point.after must be a word id in 1..{universe}, got {candidate!r}"
                )
            after = candidate
        elif point is not None:
            raise ContractError(f"{segment_id}: only an injection may carry injection_point ({point!r})")

        transcript = entry.get("transcript")
        if kind == "rule":
            if transcript is not None and not isinstance(transcript, str):
                raise ContractError(f"{segment_id}: a rule's transcript, when present, is a string")
            transcript_text = transcript if isinstance(transcript, str) else ""
        else:
            if not isinstance(transcript, str) or not transcript:
                raise ContractError(f"{segment_id}: missing transcript")
            transcript_text = transcript

        answers.append(
            SegmentAnswer(
                id=segment_id,
                type=kind,
                transcript=transcript_text,
                word_ids=word_ids,
                injection_after=after,
            )
        )
    return answers


def reconcile(answers: list[SegmentAnswer], universe: int) -> tuple[dict[int, str], list[str]]:
    """Every rendered word in exactly one non-rule segment: set equality minus
    the rule ids (the plan's reconciliation). Returns (assignment, problems)
    — a perfect answer has no problems; a gap or a double is a visible
    failure, never a silent merge."""
    assigned: dict[int, str] = {}
    problems: list[str] = []
    rule_ids: set[int] = set()
    for answer in answers:
        for word_id in answer.word_ids:
            if answer.type == "rule":
                rule_ids.add(word_id)
                continue
            if word_id in assigned:
                problems.append(f"word {word_id} in both {assigned[word_id]} and {answer.id}")
            else:
                assigned[word_id] = answer.id
    missing = sorted(set(range(1, universe + 1)) - set(assigned) - rule_ids)
    if missing:
        problems.append(f"unassigned words: {missing[:20]}{'...' if len(missing) > 20 else ''}")
    return assigned, problems


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
