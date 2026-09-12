"""Schema v1 of the VLM segment answer (tools/spike_vlm_contract.py).

The contract, pinned: types are closed; word ids stay in the render universe
and unique within a segment; an injection REQUIRES its point and everything
else FORBIDS one; reconciliation is set equality minus rules — a gap or a
double assignment is a visible failure, never a silent merge.
"""

from __future__ import annotations

import pytest

from tools.spike_vlm_contract import (
    SYSTEM_PROMPT,
    ContractError,
    SegmentAnswer,
    parse_answer,
    reconcile,
    user_prompt,
    validate_segments,
)

UNIVERSE = 345

BODY = {"id": "seg-1", "type": "body", "transcript": "A picture of life in Music College.", "word_ids": [1, 2, 3]}
INJECTION = {
    "id": "seg-2",
    "type": "injection",
    "transcript": "my dear",
    "injection_point": {"after": 7},
    "word_ids": [9, 10],
}
MARGINALIA = {"id": "seg-3", "type": "marginalia", "transcript": "Send this first", "word_ids": [15]}
RULE = {"id": "seg-4", "type": "rule", "word_ids": [12]}


def test_a_clean_answer_parses_and_validates() -> None:
    raw = parse_answer('{"segments": ' + __import__("json").dumps([BODY, INJECTION, MARGINALIA, RULE]) + "} ")
    answers = validate_segments(raw, UNIVERSE)
    assert answers[0] == SegmentAnswer("seg-1", "body", "A picture of life in Music College.", (1, 2, 3), None)
    assert answers[1].injection_after == 7
    assert answers[2].type == "marginalia"
    assert answers[3].transcript == ""  # a rule carries none


def test_the_fence_wrap_is_tolerated() -> None:
    text = '```json\n{"segments": ' + __import__("json").dumps([BODY, RULE]) + "}\n```"
    answers = validate_segments(parse_answer(text), UNIVERSE)
    assert len(answers) == 2


def test_garbage_is_a_loud_failure() -> None:
    with pytest.raises(ContractError):
        parse_answer("Lorem ipsum dolor sit amet")
    with pytest.raises(ContractError):
        parse_answer('{"lines": []}')


def test_an_unknown_type_is_rejected() -> None:
    bad = dict(BODY, type="paragraph")
    with pytest.raises(ContractError, match="unknown type"):
        validate_segments([bad], UNIVERSE)


def test_an_injection_requires_its_point() -> None:
    bare = dict(INJECTION)
    del bare["injection_point"]
    with pytest.raises(ContractError, match="REQUIRES injection_point"):
        validate_segments([bare], UNIVERSE)


def test_non_injections_forbid_a_point() -> None:
    with pytest.raises(ContractError, match="only an injection"):
        validate_segments([dict(BODY, injection_point={"after": 1})], UNIVERSE)


def test_word_ids_stay_in_the_universe_and_unique() -> None:
    with pytest.raises(ContractError, match="outside 1"):
        validate_segments([dict(BODY, word_ids=[0])], UNIVERSE)
    with pytest.raises(ContractError, match="outside 1"):
        validate_segments([dict(BODY, word_ids=[UNIVERSE + 1])], UNIVERSE)
    with pytest.raises(ContractError, match="duplicate word ids"):
        validate_segments([dict(BODY, word_ids=[1, 1])], UNIVERSE)


def test_a_body_segment_needs_a_transcript() -> None:
    with pytest.raises(ContractError, match="missing transcript"):
        validate_segments([dict(BODY, transcript=None)], UNIVERSE)


def test_reconciliation_accepts_a_complete_answer() -> None:
    universe = 4
    answers = validate_segments(
        [
            {"id": "s1", "type": "body", "transcript": "ab", "word_ids": [1, 2]},
            {"id": "s2", "type": "rule", "word_ids": [3]},
            {"id": "s3", "type": "marginalia", "transcript": "c", "word_ids": [4]},
        ],
        universe,
    )
    assigned, problems = reconcile(answers, universe)
    assert problems == []
    assert assigned == {1: "s1", 2: "s1", 4: "s3"}


def test_reconciliation_names_gaps_and_doubles() -> None:
    universe = 5
    answers = validate_segments(
        [
            {"id": "s1", "type": "body", "transcript": "ab", "word_ids": [1, 2]},
            {"id": "s2", "type": "body", "transcript": "c", "word_ids": [2]},
        ],
        universe,
    )
    _, problems = reconcile(answers, universe)
    assert any("both" in p for p in problems), problems
    assert any("unassigned" in p and "3" in p for p in problems), problems


def test_the_prompt_names_the_id_space() -> None:
    assert f"1..{UNIVERSE}" in user_prompt(UNIVERSE)
    assert "logically consecutive" in SYSTEM_PROMPT
    assert "injection_point" in SYSTEM_PROMPT
    assert "~~" in SYSTEM_PROMPT and "~word~" in SYSTEM_PROMPT
