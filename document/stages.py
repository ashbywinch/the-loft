"""The pipeline's stages — the one vocabulary (docs/PLAN/pipeline-stages-plan.md, DR1).

A developer opening the repo without context reads the stage list here: every
stage an image passes through, in order, with the object it makes, the artefact
that carries it, and whether a human decides anything at that stage. The PRD
numbers them 0–8 (`docs/PRD/pipeline-stages-spec.md` UR1): orient first, then the
eight stages of the writing.

| # | stage | makes | artefact | human |
|---|---|---|---|---|
| 0 | orient | Page | `oriented/<page>` | no |
| 1 | marks | Marks | in memory — nothing persisted | no |
| 2 | words | Words | `<page>.words.json` | no |
| 3 | rows | Rows | `<page>.rows.json` | no |
| 4 | rows_adjusted | Rows | the drawn lines + the corrected rows | yes |
| 5 | transcripts_proposed | Document (draft) | the draft Document | no |
| 6 | transcripts_agreed | Document (agreed) | `ocr-confirmed/<doc>.txt` + the registry record | yes |
| 7 | entities_proposed | Person, Relationship, Place, Theme, Org | the identity tables (proposed records) | no |
| 8 | entities_agreed | the same, agreed | the identity tables (agreed records) | yes |

The objects are the model's (`document/` — `Word`, `Row`, `Marks`, the
`Document`; the identity records are `tools/records.py`'s). This module names
them, it does not define them: a stage's `schemas` lists the classes whose own
wire carries its artefact (`Words`, `Rows`, `RowAdjustments`, `Document`), and
a test resolves every name.

A page's progress through the stages is a `PageStatus` — the scan pickup's
`new -> oriented -> marks -> words -> rows_draft -> rows_pending`. The statuses
the later stages would carry are deliberately absent: nothing writes them yet
(the portal's remaining doors are the plan's step 5).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


@dataclass(frozen=True)
class StageFacts:
    """What one stage is: the PRD's number for it, its name, the object it
    makes, the artefact that carries that object, the wire contracts of the
    artefact (the model's classes — `Words`, `Rows`, `RowAdjustments`,
    `Document`), and whether a human decides here."""

    number: int
    label: str
    produces: str
    artefact: str | None
    schemas: tuple[str, ...]
    human: bool


class Stage(Enum):
    """The stages an image passes through, in the PRD's order (0–8)."""

    ORIENT = StageFacts(number=0, label="orient", produces="Page", artefact="oriented/<page>", schemas=(), human=False)
    MARKS = StageFacts(number=1, label="marks", produces="Marks", artefact=None, schemas=(), human=False)
    WORDS = StageFacts(
        number=2, label="words", produces="Words", artefact="<page>.words.json", schemas=("Words",), human=False
    )
    ROWS = StageFacts(
        number=3, label="rows", produces="Rows", artefact="<page>.rows.json", schemas=("Rows",), human=False
    )
    ROWS_ADJUSTED = StageFacts(
        number=4,
        label="rows_adjusted",
        produces="Rows",
        artefact="<page>.row-adjustments.json + <page>.rows-adjusted.json",
        schemas=("RowAdjustments", "Rows"),
        human=True,
    )
    TRANSCRIPTS_PROPOSED = StageFacts(
        number=5,
        label="transcripts_proposed",
        produces="Document",
        artefact="the draft Document",
        schemas=("Document",),
        human=False,
    )
    TRANSCRIPTS_AGREED = StageFacts(
        number=6,
        label="transcripts_agreed",
        produces="Document",
        artefact="ocr-confirmed/<doc>.txt + the registry record",
        schemas=("Document",),
        human=True,
    )
    ENTITIES_PROPOSED = StageFacts(
        number=7,
        label="entities_proposed",
        produces="Person, Relationship, Place, Theme, Org",
        artefact="the identity tables",
        schemas=(),
        human=False,
    )
    ENTITIES_AGREED = StageFacts(
        number=8,
        label="entities_agreed",
        produces="Person, Relationship, Place, Theme, Org",
        artefact="the identity tables",
        schemas=(),
        human=True,
    )

    @property
    def facts(self) -> StageFacts:
        """What this stage is — its number, name, object, artefact, contracts
        and human flag."""
        return self.value

    @property
    def status(self) -> PageStatus | None:
        """The status a page reaches when this stage completes — `None` for a
        stage whose status is not named yet (the marks are in memory; the
        transcript and entity stages' statuses are unbuilt)."""
        return _STATUS_OF_STAGE.get(self)

    @classmethod
    def of(cls, label: str) -> Stage:
        """The stage named `label` — a stored or requested stage name is
        validated against the vocabulary here, never matched ad hoc."""
        for stage in cls:
            if stage.facts.label == label:
                return stage
        raise ValueError(f"no stage named {label!r}: {[stage.facts.label for stage in cls]}")


class PageStatus(Enum):
    """Where a page has got to: the completion of one stage, or the page
    waiting on the person who checks the rows.

    `rows_draft` is the transient status while the draft rows are written;
    `rows_pending` is the page in the "Check the rows" queue (the plan's scan
    pickup). A page leaves `rows_pending` when the user's row check is
    recorded — adjusted or confirmed, the same thing to the queue."""

    NEW = "new"
    ORIENTED = "oriented"
    MARKS = "marks"
    WORDS = "words"
    ROWS_DRAFT = "rows_draft"
    ROWS_PENDING = "rows_pending"

    @property
    def stage(self) -> Stage | None:
        """The stage this status is the completion of (`None` for `new`, a page
        no machine stage has touched)."""
        return _STAGE_OF_STATUS.get(self)

    @property
    def awaiting_human(self) -> bool:
        """True when the page is waiting on a person — the row check's queue."""
        stage = self.stage
        return stage is not None and stage.facts.human

    @classmethod
    def of(cls, status: str) -> PageStatus:
        """The status named `status` — a stored page status is validated
        against the vocabulary here, never matched ad hoc."""
        for known in cls:
            if known.value == status:
                return known
        raise ValueError(f"no page status named {status!r}: {[known.value for known in cls]}")


# the stage each status is the completion of — one table, so the two
# vocabularies cannot drift apart unremarked (a test pins every status)
_STAGE_OF_STATUS: Mapping[PageStatus, Stage] = MappingProxyType(
    {
        PageStatus.ORIENTED: Stage.ORIENT,
        PageStatus.MARKS: Stage.MARKS,
        PageStatus.WORDS: Stage.WORDS,
        PageStatus.ROWS_DRAFT: Stage.ROWS,
        PageStatus.ROWS_PENDING: Stage.ROWS_ADJUSTED,
    }
)
_STATUS_OF_STAGE: Mapping[Stage, PageStatus] = MappingProxyType(
    {stage: status for status, stage in _STAGE_OF_STATUS.items()}
)
