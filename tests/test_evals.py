"""The real-model evals as pytest tests (2026-08-10, user: "name all the
flows that the tests do… and have a fixture that caches the results of
running the flow. Then the individual tests can remain independent and not
be aware that they share flow outputs. They just verify the output against
their condition").

Every eval carries the ``eval`` marker — skipped by default (``addopts -m
'not eval'`` in pyproject.toml, so ``make test`` never runs it) and
selected with the framework's own machinery: ``pytest -m eval`` runs
everything, ``-m eval_review`` one suite, ``-k "arc"`` one flow. Each flow
runs ONCE — the session fixtures cache the outputs — and the condition
tests verify one condition against the cached output, unaware they share
the runs. A failure is a failure to fix, never a re-run
(testing-standards: evals are never flaky).
"""

from __future__ import annotations

from typing import Any

import pytest

import tools.eval_memory as memory_evals
import tools.eval_review as review_evals
import tools.eval_transcription as transcription_evals
from tools.ai_client import AIClient, AIClientError


@pytest.fixture(scope="session")
def client() -> AIClient:
    try:
        return AIClient()
    except AIClientError as e:
        # fail loudly, never a silent skip: an eval that cannot run must say
        # so (2026-08-05) — a skip would green a suite that never ran
        pytest.fail(f"no API key — the eval cannot run: {e}")


@pytest.fixture(scope="session")
def default_knowledge() -> dict[str, list[dict[str, Any]]]:
    return memory_evals.load_projection()


# -- the review flows: one run per flow, every condition a separate test --


@pytest.fixture(scope="session")
def review_outputs(client: AIClient) -> dict[str, dict[str, Any]]:
    """Run every review flow ONCE and cache the outputs — the condition
    tests are independent and unaware they share the runs (2026-08-10)."""
    return {f.name: review_evals.run_flow(client, f) for f in review_evals.FLOWS}


@pytest.mark.eval
@pytest.mark.eval_review
@pytest.mark.parametrize("flow", review_evals.FLOWS, ids=lambda f: f.name)
@pytest.mark.parametrize("condition", review_evals.REVIEW_CONDITIONS, ids=lambda c: c[0])
def test_review_condition(
    review_outputs: dict[str, dict[str, Any]],
    flow: review_evals.ReviewFlow,
    condition: tuple[str, Any],
) -> None:
    name, check = condition
    error = check(flow, review_outputs[flow.name])
    assert error is None, f"[{name}] {error}"


@pytest.fixture(scope="session")
def arc_outputs(client: AIClient) -> dict[str, Any]:
    return review_evals.run_arc(client)


@pytest.mark.eval
@pytest.mark.eval_review
def test_arc_lead_followed(arc_outputs: dict[str, Any]) -> None:
    assert review_evals.condition_arc_lead(arc_outputs) is None


@pytest.mark.eval
@pytest.mark.eval_review
def test_arc_no_repeat(arc_outputs: dict[str, Any]) -> None:
    assert review_evals.condition_arc_no_repeat(arc_outputs) is None


@pytest.fixture(scope="session")
def caching_outputs(client: AIClient) -> dict[str, Any]:
    return review_evals.run_caching(client)


@pytest.mark.eval
@pytest.mark.eval_review
def test_caching_prefix(caching_outputs: dict[str, Any]) -> None:
    assert review_evals.condition_caching_prefix(caching_outputs) is None


# -- the memory flows -------------------------------------------------------


@pytest.fixture(scope="session")
def memory_outputs(client: AIClient, default_knowledge: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Run every memory flow ONCE — the assess stage — and cache the
    outputs; the condition tests share the runs (2026-08-10)."""
    return {f.name: memory_evals.run_flow(client, f, default_knowledge) for f in memory_evals.FLOWS}


@pytest.mark.eval
@pytest.mark.eval_memory
@pytest.mark.parametrize("flow", memory_evals.FLOWS, ids=lambda f: f.name)
def test_memory_contract(memory_outputs: dict[str, dict[str, Any]], flow: memory_evals.MemoryFlow) -> None:
    errors = memory_evals.condition_contract(memory_outputs[flow.name])
    assert not errors, "\n".join(errors)


@pytest.mark.eval
@pytest.mark.eval_memory
@pytest.mark.parametrize("flow", memory_evals.FLOWS, ids=lambda f: f.name)
def test_memory_flow_conditions(memory_outputs: dict[str, dict[str, Any]], flow: memory_evals.MemoryFlow) -> None:
    errors = flow.assert_(memory_outputs[flow.name])
    assert not errors, "\n".join(errors)


# -- the transcription flow -------------------------------------------------


@pytest.fixture(scope="session")
def transcription_outputs() -> dict[str, str]:
    return transcription_evals.run_flow()


@pytest.mark.eval
@pytest.mark.eval_transcription
@pytest.mark.parametrize("phrase", transcription_evals.TranscriptionFlow.ground_truth)
@pytest.mark.parametrize("orientation", transcription_evals.TranscriptionFlow.orientations)
def test_transcription_ground_truth(transcription_outputs: dict[str, str], phrase: str, orientation: str) -> None:
    assert transcription_evals.condition_ground_truth(transcription_outputs, phrase, orientation) is None
