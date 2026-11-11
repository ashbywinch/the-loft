"""The real-model evals as pytest tests (user: "name all the
flows that the tests do… and have a fixture that caches the results of
running the flow. Then the individual tests can remain independent and not
be aware that they share flow outputs. They just verify the output against
their condition").

The eval suite splits by marker: the review evals carry
``eval`` — ``pytest -m eval`` (``make evals``) runs them; the memory
evals read the archive's projection (``app/data``) and carry ``archive``
like the data checks, running locally in ``make verify`` and skipping in
CI, whose checkout has no archive. Both are skipped by default
(``addopts -m 'not eval and not archive'``, so ``make test`` never runs
them) and selected per suite with the framework's machinery: ``-m
eval_review`` one suite, ``-k "arc"`` one flow, and ``make eval-changed``
selects ``(eval or archive) and (…)`` so a change to the memory module
still runs the memory evals. Each flow
runs ONCE — the session fixtures cache the outputs — and the condition
tests verify one condition against the cached output, unaware they share
the runs. A failure is a failure to fix, never a re-run
(testing-standards: evals are never flaky).

The transcription-fidelity eval was removed — the transcription backend
is the vision model, not the local HTR path (user).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import pipeline.evals.eval_review as review_evals
import tools.eval_memory as memory_evals
from pipeline.identification import Identification
from pipeline.identify import identify
from pipeline.model.ai_client import AIClient, AIClientError
from tools.assessment import Assessment
from tools.memory import Assessor, Knowledge
from tools.records import Item, Person
from tools.review_verdict import ReviewVerdict


@pytest.fixture(scope="session")
def client() -> AIClient:
    try:
        return AIClient(max_tokens=Assessor.ASSESS_MAX_TOKENS)
    except AIClientError as e:
        # fail loudly, never a silent skip: an eval that cannot run must say
        # so — a skip would green a suite that never ran
        pytest.fail(f"no API key — the eval cannot run: {e}")


@pytest.fixture(scope="session")
def default_knowledge() -> Knowledge:
    return memory_evals.load_projection()


# -- the review flows: one run per flow, every condition a separate test --


@pytest.fixture(scope="session")
def review_outputs(client: AIClient) -> dict[str, ReviewVerdict]:
    """Run every review flow ONCE and cache the outputs — the condition
    tests are independent and unaware they share the runs."""
    return {f.name: review_evals.run_flow(client, f) for f in review_evals.FLOWS}


@pytest.mark.eval
@pytest.mark.eval_review
@pytest.mark.parametrize("flow", review_evals.FLOWS, ids=lambda f: f.name)
@pytest.mark.parametrize("condition", review_evals.REVIEW_CONDITIONS, ids=lambda c: c[0])
def test_review_condition(
    review_outputs: dict[str, ReviewVerdict],
    flow: review_evals.ReviewFlow,
    condition: tuple[str, Any],
) -> None:
    name, check = condition
    run = review_evals.ReviewRun(flow, review_outputs[flow.name])
    error = check(run)
    assert error is None, f"[{name}] {error}"


@pytest.fixture(scope="session")
def arc_outputs(client: AIClient) -> review_evals.ArcRun:
    return review_evals.run_arc(client)


@pytest.mark.eval
@pytest.mark.eval_review
def test_arc_lead_followed(arc_outputs: review_evals.ArcRun) -> None:
    assert review_evals.condition_arc_lead(arc_outputs) is None


@pytest.mark.eval
@pytest.mark.eval_review
def test_arc_no_repeat(arc_outputs: review_evals.ArcRun) -> None:
    assert review_evals.condition_arc_no_repeat(arc_outputs) is None


@pytest.fixture(scope="session")
def caching_outputs(client: AIClient) -> review_evals.CachingRun:
    return review_evals.run_caching(client)


@pytest.mark.eval
@pytest.mark.eval_review
def test_caching_prefix(caching_outputs: review_evals.CachingRun) -> None:
    assert review_evals.condition_caching_prefix(caching_outputs) is None


# -- the memory flows -------------------------------------------------------


@pytest.fixture(scope="session")
def memory_outputs(client: AIClient, default_knowledge: Knowledge) -> dict[str, Assessment]:
    """Run every memory flow ONCE — the assess stage — and cache the
    outputs; the condition tests share the runs. A `-k` selection still pays
    for all of them (measured: 14 minutes for one flow's assertions), so the
    unit of iteration is the suite's prompt, not the single test. An identical
    repeat run is not served from a cache either (measured: two runs of the
    same requests took 14 and 19 minutes), so a repeat re-samples the model."""
    return {f.name: memory_evals.run_flow(client, f, default_knowledge) for f in memory_evals.MemoryFlow.ALL}


@pytest.mark.eval
@pytest.mark.archive
@pytest.mark.eval_memory
@pytest.mark.skipif(
    not (Path("app/data/people.json")).exists(),
    reason="projection not built — run `loft publish` (the memory evals read the archive's projection)",
)
@pytest.mark.parametrize("flow", memory_evals.MemoryFlow.ALL, ids=lambda f: f.name)
def test_memory_contract(memory_outputs: dict[str, Assessment], flow: memory_evals.MemoryFlow) -> None:
    errors = memory_evals.condition_contract(memory_outputs[flow.name])
    assert not errors, "\n".join(errors)


@pytest.mark.eval
@pytest.mark.archive
@pytest.mark.eval_memory
@pytest.mark.skipif(
    not (Path("app/data/people.json")).exists(),
    reason="projection not built — run `loft publish` (the memory evals read the archive's projection)",
)
@pytest.mark.parametrize("flow", memory_evals.MemoryFlow.ALL, ids=lambda f: f.name)
def test_memory_flow_conditions(memory_outputs: dict[str, Assessment], flow: memory_evals.MemoryFlow) -> None:
    errors = flow.assert_(memory_outputs[flow.name])
    assert not errors, "\n".join(errors)


# -- the identification flow (stage 7) --------------------------------------

# a fictional letter (never real content) naming a family member the
# knowledge holds, a stranger, a bare kinship term, and a place
IDENTIFICATION_LETTER = (
    "My dear Fern,\n\n"
    "We came down to Seascale again this summer — Owen Pryce drove us over. "
    "Mum was too tired to come, so it was just the three of us on the sands.\n\n"
    "Your loving sister,\nHarriet"
)


@pytest.fixture(scope="session")
def identification_output(client: AIClient) -> Identification:
    """Run the stage-7 pass ONCE and cache it — the condition tests share
    this one reading (evals run once; a failed condition is fixed in the
    prompt, never re-sampled)."""
    item = Item.from_dict(
        {
            "id": "doc-1971-05-01",
            "type": "document",
            "title": "A letter from Harriet",
            "date": "1971-05-01",
            "date_precision": "exact",
            "status": "catalogued",
            "assets": [],
            "people": [],
            "places": [],
            "themes": [],
        }
    )
    knowledge = Knowledge(
        people=(Person.from_dict({"id": "p-fern", "name": "Fern", "aliases": ["mamie"]}),),
        places=(),
    )
    return identify(client, item=item, text=IDENTIFICATION_LETTER, knowledge=knowledge)


@pytest.mark.eval
def test_identification_names_the_letters_people(identification_output: Identification) -> None:
    """The reader finds the letter's people, not just the salutation."""
    names = {person.name for person in identification_output.people}
    assert {"Fern", "Owen Pryce"} <= names, f"people read: {sorted(names)}"


@pytest.mark.eval
def test_identification_links_a_known_name_and_never_mints_it_again(identification_output: Identification) -> None:
    """A name the archive holds links to its record; the pass never creates a
    second record for it."""
    fern = [person for person in identification_output.people if person.name == "Fern"]
    assert [person.id for person in fern] == ["p-fern"], fern


@pytest.mark.eval
def test_identification_proposes_a_stranger_with_the_documents_words(identification_output: Identification) -> None:
    """A stranger is proposed, never asserted, and the proposal carries the
    document's own words as its evidence."""
    owen = next((person for person in identification_output.people if person.name == "Owen Pryce"), None)
    assert owen is not None, [person.name for person in identification_output.people]
    assert owen.status == "proposed"
    assert owen.basis is not None and owen.basis["text"] in IDENTIFICATION_LETTER


@pytest.mark.eval
def test_identification_finds_the_place(identification_output: Identification) -> None:
    assert [place.name for place in identification_output.places] == ["Seascale"]


@pytest.mark.eval
def test_identification_never_matches_a_bare_kinship_term(identification_output: Identification) -> None:
    """The family's word "Mum" is never a record match, whatever the alias."""
    for person in identification_output.people:
        if person.name == "Mum":
            assert person.id != "p-fern", "a kinship term resolved to the standing record"


@pytest.mark.eval
def test_identification_asserts_nothing(identification_output: Identification) -> None:
    """Nothing the machine reads is confirmed: each freshly minted record is a
    proposal, and every mention the document gains is proposed. A matched
    standing record keeps its own status (it was not the pass's to change)."""
    standing = {"p-fern"}
    minted = [person for person in identification_output.people if person.id not in standing]
    assert minted and all(person.status == "proposed" for person in minted)
    assert all(place.status == "proposed" for place in identification_output.places)
    assert all(ref.status == "proposed" for ref in identification_output.people_refs())
