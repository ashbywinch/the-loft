"""Eval for the elicitation assessment — run against the real model.

Not part of `make test` (tests never hit the network): this needs a network
and a configured key (OPENAI_API_KEY / OPENCODE_API_KEY / opencode auth.json).
Run with `loft eval-memory` (tools/cli.py).

The flows run the real assessment and hand back its record
(`tools/assessment.py` Assessment) — the conditions read that object, never a
bare dict.

The cases cover the family's own stories AND a fictional family (the
Kowalskis of Gdańsk), so the assessment cannot be tuned to one household's
data: the fictional cases assert the model never over-matches to this
family's cast/places, and the adversarial case pins the about-vs-mention
rule. The dob cases pin the age/date behaviour (docs/CONTRIBUTIONS.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import override

from pipeline.model.ai_client import AIClient
from tools.anchor import Anchor
from tools.assessment import Assessment
from tools.assessment_fact import AssessmentFact
from tools.memory import BUCKETS, KINDS, MAX_QUESTIONS, MAX_SUGGESTIONS, Knowledge, assess

REPO = Path(__file__).resolve().parent.parent

AssertFn = Callable[[Assessment], list[str]]


def load_projection() -> Knowledge:
    """The published projection as the standing knowledge the real flows
    assess against — the same records the server loads."""
    data = REPO / "app" / "data"
    return Knowledge.from_projection(
        people=json.loads((data / "people.json").read_text(encoding="utf-8"))["people"],
        places=json.loads((data / "places.json").read_text(encoding="utf-8"))["places"],
        themes=json.loads((data / "themes.json").read_text(encoding="utf-8"))["themes"],
        items=json.loads((data / "index.json").read_text(encoding="utf-8"))["items"],
    )


# The elicitation speaks the family's language, never the process's — the
# hired genealogist's voice (PRD: "the assistant reads as a hired
# genealogist, not a computer"; user: "make sure the
# requirement is in all relevant evals").
_PROCESS_JARGON = (
    "session",
    "interview",
    "elicitation",
    "draft",
    "the system",
    "the app",
    "question 1",
    "input",
)


def _persona_errors(result: Assessment) -> list[str]:
    return [
        f"question echoes the process ('{word}'): {q.text[:80]}"
        for q in result.questions
        for word in _PROCESS_JARGON
        if word in q.text.lower()
    ]


def contract_errors(result: Assessment) -> list[str]:
    errors: list[str] = []
    errors.extend(_persona_errors(result))
    if not result.title.strip():
        errors.append("missing title")
    # three distinct conditional validation messages per iteration — a comprehension
    # would need a None-sentinel tuple, which is harder to read than the loop
    # lucidlint: ignore loop-pipeline three conditional messages per iteration, sentinel-tuple comprehension
    for ex in result.extractions:
        if ex.kind not in KINDS:
            errors.append(f"extraction kind not in {KINDS}: {ex!r}")
        if ex.bucket not in BUCKETS:
            errors.append(f"extraction bucket not in {BUCKETS}: {ex!r}")
        if not (ex.match is None or isinstance(ex.match, str)):
            errors.append(f"extraction match must be str|null: {ex!r}")
    if len(result.questions) > MAX_QUESTIONS:
        errors.append(f"more than {MAX_QUESTIONS} questions")
    # two distinct conditional validation messages per iteration plus a derived local
    # (suggestions) — a comprehension would need a None-sentinel tuple
    # lucidlint: ignore loop-pipeline two conditional messages per iteration plus a derived local
    for q in result.questions:
        if q.skippable is not True:
            errors.append(f"question not skippable: {q!r}")
        suggestions = q.suggestions
        if len(suggestions) > MAX_SUGGESTIONS or not all(isinstance(s, str) for s in suggestions):
            errors.append(f"bad suggestions: {suggestions!r}")
    return errors


def _matches(result: Assessment) -> list[str]:
    return [match for ex in result.extractions if (match := ex.match)]


def _extraction_names(result: Assessment) -> list[str]:
    return [ex.name for ex in result.extractions]


def _question_texts(result: Assessment) -> str:
    return " ".join(q.text for q in result.questions).lower()


def _facts_of_kind(result: Assessment, kind: str) -> list[AssessmentFact]:
    return [f for f in result.facts if f.kind == kind]


def _expect_linked(expected: set[str], result: Assessment, message: str) -> list[str]:
    """The common link assertion: at least one expected id must be matched.
    Empty means the condition holds."""
    if any(m in expected for m in _matches(result)):
        return []
    return [message]


def _expect_not_linked(disallowed: str, result: Assessment, message: str) -> list[str]:
    """The mention-vs-link guard: the disallowed id must NOT be matched.
    Empty means the condition holds."""
    if disallowed in _matches(result):
        return [message]
    return []


# date-seeking phrasing ("when you moved" inside another question is not one)
_DATE_ASK = (
    "what year",
    "which year",
    "in what year",
    "in which year",
    "date of birth",
    "born",
    "how old",
    "your age",
    "what date",
    "when did",
    "when was",
    "when do",
    "when were",
)


def _real_knowledge_with_dob() -> Knowledge:
    """Fictional narrator for the dob cases — the rule must not depend on
    which real people happen to be in the projection (no person is
    special-cased in code)."""
    return Knowledge.from_projection(
        people=[
            {
                "id": "p-marek",
                "name": "Marek Kowalski",
                "aliases": ["Marek"],
                # the projection carries a dob as a dated fact ({date, precision}),
                # never a bare phrase — the record validates the shape
                "dob": {"date": "1982-05-01", "precision": "exact"},
            }
        ],
        places=[],
        themes=[],
        items=[],
    )


# ---------------------------------------------------------------------------
# Cases: the family's own stories and a fictional family
# ---------------------------------------------------------------------------


class MemoryFlow:
    """One named memory-capture scenario — the anchor, the narrator, the
    account. The session fixture runs each flow ONCE (the assess stage —
    the production call self-corrects internally, so the eval runs it
    exactly once); the condition tests verify the single output against
    the flow's ``assert_`` and the shared contract (user:
    name the flows, cache the runs, independent tests)."""

    name = ""
    anchor: Anchor = Anchor()
    who = ""
    account = ""
    knowledge: Knowledge | None = None  # None = the real archive's projection

    @staticmethod
    def assert_(result: Assessment) -> list[str]:
        """The flow's conditions on the output — empty means they all hold."""
        raise NotImplementedError


class RealBoatsLinksFlow(MemoryFlow):
    name = "real-boats-links-the-artifacts"
    anchor = Anchor(kind="place", id="pl-farndale-wharf", name="Iron Wharf, Farndale")
    who = "Alex"
    account = "The boats were built on Iron Wharf — Sunlight first in 1980. The yard had a slipway into the creek."

    @override
    @staticmethod
    def assert_(result: Assessment) -> list[str]:
        return _expect_linked(
            {"t-the-boats", "object-sunlight"},
            result,
            "the boats/Sunlight were not linked — expected a theme or artifact extraction",
        )


class RealSheppeyFlow(MemoryFlow):
    name = "real-sheppey-extracts-about-entities"
    anchor = Anchor(kind="place", id="pl-seagate", name="Seagate")
    who = "Alex"
    account = (
        "We used to sail around the Isle of Seagate and under the old ford, not the new one. "
        "Dad built the boats on Iron Wharf and Mum came along sometimes."
    )

    @override
    @staticmethod
    def assert_(result: Assessment) -> list[str]:
        return _expect_linked(
            {"pl-seagate", "pl-farndale-wharf", "p-owen", "p-nora", "t-the-boats"},
            result,
            "no about-entity from the story was matched",
        )


class FictionalNoOvermatchFlow(MemoryFlow):
    name = "fictional-family-no-overmatch"
    knowledge = Knowledge.from_projection(
        people=[
            {"id": "p-helena", "name": "Helena Kowalski", "aliases": ["Grandma", "Babcia"]},
            {"id": "p-jan", "name": "Jan Kowalski", "aliases": ["Janek"]},
        ],
        places=[{"id": "pl-gdansk", "name": "Gdańsk"}, {"id": "pl-dluga", "name": "Ulica Długa"}],
        themes=[],
        items=[],
    )
    anchor = Anchor(kind="place", id="pl-gdansk", name="Gdańsk")
    who = "Marek"
    account = (
        "Grandma Helena ran a bakery on Ulica Długa in Gdańsk. We used to visit after school and she "
        "always gave us fresh poppy-seed cake. Janek helped behind the counter."
    )

    @override
    @staticmethod
    def assert_(result: Assessment) -> list[str]:
        names = _extraction_names(result)
        if any(p in n for n in names for p in ("Helena", "Janek", "Jan")) and any(
            p in n for n in names for p in ("Gdańsk", "Długa", "Ulica")
        ):
            return []
        return [f"expected the fictional people and places extracted, got {names}"]


class FictionalMentionNotLinkFlow(MemoryFlow):
    name = "fictional-mention-is-not-a-link"
    anchor = Anchor(kind="theme", id="t-the-boats", name="The boats")
    who = "Marek"
    account = (
        "Aunt Nora from next door brought her famous plum cake to our wedding. It rained, but "
        "nobody minded, and Dad played the accordion all evening."
    )

    @override
    @staticmethod
    def assert_(result: Assessment) -> list[str]:
        return _expect_not_linked(
            disallowed="p-nora",
            result=result,
            message='"Nora" in a fictional story matched p-nora — about ≠ mention',
        )


class KinshipTermNotAliasFlow(MemoryFlow):
    name = "kinship-term-not-an-archive-alias"
    knowledge = Knowledge.from_projection(
        people=[
            {"id": "p-marek", "name": "Marek Kowalski", "aliases": ["Marek"]},
            {"id": "p-otto", "name": "Otto Nowak", "aliases": ["Dad"]},
        ],
        places=[],
        themes=[],
        items=[],
    )
    anchor = Anchor(kind="theme", id="t-kowalski-house", name="The house")
    who = "Marek"
    account = "Dad came with me to see the house we wanted to buy. He said nothing, which is his way."

    @override
    @staticmethod
    def assert_(result: Assessment) -> list[str]:
        return _expect_not_linked(
            disallowed="p-otto",
            result=result,
            message=(
                "'Dad' defaulted to p-otto — a kinship term is the writer's own "
                "relative, never an archive-wide alias (2026-08-05)"
            ),
        )


class AgeWithKnownDobNotAskedFlow(MemoryFlow):
    name = "age-with-known-dob-is-not-asked"
    knowledge = _real_knowledge_with_dob()
    anchor = Anchor(kind="item", id="letter-1990-03-01", name="A letter")
    who = "Marek"
    account = "I was eight when we moved to the new house."

    @override
    @staticmethod
    def assert_(result: Assessment) -> list[str]:
        if not any(w in _question_texts(result) for w in _DATE_ASK):
            return []
        return [f"asked for a date despite a known dob + given age: {_question_texts(result)}"]


class AgeWithoutDobAsksFlow(MemoryFlow):
    name = "age-without-dob-asks-politely"
    knowledge = Knowledge.from_projection(
        people=[{"id": "p-marek", "name": "Marek Kowalski", "aliases": ["Marek"]}],
        places=[],
        themes=[],
        items=[],
    )
    anchor = Anchor(kind="item", id="letter-1990-03-01", name="A letter")
    who = "Marek"
    account = "I was eight when we moved to the new house."

    @override
    @staticmethod
    def assert_(result: Assessment) -> list[str]:
        if any(w in _question_texts(result) for w in _DATE_ASK):
            return []
        return ["no date question asked despite an unknown dob and only an age given"]


class DobStatedAssertedFlow(MemoryFlow):
    name = "dob-stated-in-account-is-asserted"
    knowledge = Knowledge.from_projection(
        people=[{"id": "p-marek", "name": "Marek Kowalski", "aliases": ["Marek"]}],
        places=[],
        themes=[],
        items=[],
    )
    anchor = Anchor(kind="item", id="letter-1990-03-01", name="A letter")
    who = "Marek"
    account = "I was eight when we moved. My DOB is 15/09/1981."

    @override
    @staticmethod
    def assert_(result: Assessment) -> list[str]:
        if _facts_of_kind(result, "dob") and not any(w in _question_texts(result) for w in _DATE_ASK):
            return []
        return ["expected an asserted dob fact and no date question when dob + age are computable"]


class NewNarratorConnectionFlow(MemoryFlow):
    name = "new-narrator-connection-asked"
    knowledge = Knowledge.from_projection(
        people=[{"id": "p-helena", "name": "Helena Kowalski", "aliases": ["Grandma", "Babcia"]}],
        places=[],
        themes=[],
        items=[],
    )
    anchor = Anchor(kind="theme", id="t-kowalski-wedding", name="The wedding")
    who = "Zofia Kowalski"
    account = "The wedding was lovely, the cake was poppy seed."

    @override
    @staticmethod
    def assert_(result: Assessment) -> list[str]:
        if any(w in _question_texts(result) for w in ("connect", "related", "relationship", "family")):
            return []
        return ["no question asks how the new narrator is connected to the family"]


class NewArtifactAskedFlow(MemoryFlow):
    name = "new-artifact-asked-about"
    knowledge = Knowledge.from_projection(
        people=[{"id": "p-marek", "name": "Marek Kowalski", "aliases": ["Marek"]}],
        places=[],
        themes=[],
        items=[],
    )
    anchor = Anchor(kind="theme", id="t-kowalski-boats", name="The boats")
    who = "Marek"
    account = "We sailed on the Kasia, a little yacht Dad rebuilt in the garden."

    @override
    @staticmethod
    def assert_(result: Assessment) -> list[str]:
        if "kasia" in _question_texts(result):
            return []
        return ["no 'tell me more' question about the newly named artifact (Kasia)"]


FLOWS: tuple[MemoryFlow, ...] = (
    RealBoatsLinksFlow(),
    RealSheppeyFlow(),
    FictionalNoOvermatchFlow(),
    FictionalMentionNotLinkFlow(),
    KinshipTermNotAliasFlow(),
    AgeWithKnownDobNotAskedFlow(),
    AgeWithoutDobAsksFlow(),
    DobStatedAssertedFlow(),
    NewNarratorConnectionFlow(),
    NewArtifactAskedFlow(),
)


def run_flow(
    client: AIClient,
    flow: MemoryFlow,
    default_knowledge: Knowledge,
) -> Assessment:
    """Run the flow ONCE — the assess stage, exactly once (the production
    call self-corrects internally, so the eval must not repeat it). The
    condition tests verify the single output."""
    return assess(
        client,
        anchor=flow.anchor,
        who=flow.who,
        account=flow.account,
        knowledge=flow.knowledge or default_knowledge,
    )


def condition_contract(result: Assessment) -> list[str]:
    """The shared elicitation contract — every flow's output must satisfy
    it (the skippability of questions, the persona guard)."""
    return contract_errors(result)
