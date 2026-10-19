"""The stage vocabulary (docs/PLAN/pipeline-stages-plan.md, DR1): one list
names the stages, in the PRD's order, each with the object it makes, the
artefact that carries it, and whether a human decides there — and the page
statuses name the stage they complete.

The list is the contract a developer reads instead of reconstructing the
pipeline from the chain's code; a stage added, renamed or reordered without
the docs is what these pin."""

from __future__ import annotations

import pytest

from document.boxes import Boxes
from document.document import Document, DocumentLine
from document.page_size import PageSize
from document.row import Row
from document.row_adjustments import RowAdjustments
from document.stages import PageStatus, Stage
from document.words import Words
from pipeline.rows.rows import Rows

# the PRD's stages (docs/PRD/pipeline-stages-spec.md UR1), in order
PRD_STAGES = (
    "orient",
    "marks",
    "words",
    "rows",
    "rows_adjusted",
    "transcripts_proposed",
    "transcripts_agreed",
    "entities_proposed",
    "entities_agreed",
)

# the classes whose own wire carries a stage's artefact — a stage's `schemas`
# may only name these. Each one owns its `from_dict`/`to_dict`, so there is no
# bag of contracts beside them to look the names up in.
CONTRACTS = {
    contract.__name__ for contract in (Boxes, Document, DocumentLine, PageSize, Row, RowAdjustments, Rows, Words)
}


def test_the_stages_are_the_prds_list_in_order() -> None:
    assert [stage.facts.label for stage in Stage] == list(PRD_STAGES)


def test_the_stages_are_numbered_as_the_prd_numbers_them() -> None:
    """UR1 numbers them 0–8: orient, then the eight stages of the writing."""
    assert [stage.facts.number for stage in Stage] == list(range(len(PRD_STAGES)))


def test_the_human_stages_are_the_users_decisions() -> None:
    """UR1: the user fixes the rows (4), agrees the transcripts (6) and agrees
    the entities (8). Every other stage is the machine's — a human flag that
    drifts here silently reclassifies a stage."""
    assert [stage.facts.label for stage in Stage if stage.facts.human] == [
        "rows_adjusted",
        "transcripts_agreed",
        "entities_agreed",
    ]


def test_every_named_contract_is_a_document_schema() -> None:
    """A stage's `schemas` names the classes that carry its artefact's wire; a
    name that is not one of the model's contract classes is a typo, not a
    seam."""
    named = {name for stage in Stage for name in stage.facts.schemas}
    assert named, "the vocabulary names no contracts at all"
    assert named <= CONTRACTS, f"not the model's wire contracts: {sorted(named - CONTRACTS)}"


def test_every_stage_says_what_it_makes() -> None:
    """The artefact is prose (a file name shape, or the table a stage writes);
    only the marks stage has none — it is in memory."""
    assert [stage.facts.label for stage in Stage if stage.facts.artefact is None] == ["marks"]
    assert all(stage.facts.produces for stage in Stage)


def test_a_stage_is_found_by_its_label() -> None:
    for stage in Stage:
        assert Stage.of(stage.facts.label) is stage


def test_an_unknown_stage_is_refused() -> None:
    with pytest.raises(ValueError, match="no stage named 'paddle'"):
        Stage.of("paddle")


def test_the_page_statuses_are_the_scan_pickups_sequence() -> None:
    """docs/PLAN/pipeline-stages-plan.md, the scan pickup: a dropped scan
    reaches the row-check queue with no manual step."""
    assert [status.value for status in PageStatus] == [
        "new",
        "oriented",
        "marks",
        "words",
        "rows_draft",
        "rows_pending",
    ]


def test_every_page_status_names_the_stage_it_completes() -> None:
    """`new` is a page no stage has touched; every other status is one stage's
    completion, and the two vocabularies agree in both directions."""
    assert PageStatus.NEW.stage is None
    for status in PageStatus:
        stage = status.stage
        if stage is None:
            assert status is PageStatus.NEW
            continue
        assert stage.status is status, f"{status.value} and {stage.facts.label} disagree"


def test_the_draft_rows_are_written_before_the_page_waits_on_the_user() -> None:
    """The plan's two rows statuses: `rows_draft` is the transient status while
    the draft rows are written; `rows_pending` is the page in the "Check the
    rows" queue — the one status a person holds up."""
    assert Stage.ROWS.status is PageStatus.ROWS_DRAFT
    assert PageStatus.ROWS_PENDING.stage is Stage.ROWS_ADJUSTED
    assert [status.value for status in PageStatus if status.awaiting_human] == ["rows_pending"]


def test_a_stored_page_status_is_validated_against_the_vocabulary() -> None:
    assert PageStatus.of("rows_pending") is PageStatus.ROWS_PENDING
    with pytest.raises(ValueError, match="no page status named 'transcribing'"):
        PageStatus.of("transcribing")
