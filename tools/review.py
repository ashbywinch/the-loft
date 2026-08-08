"""The import review (2026-08-08, user): the pending people are confirmed
in the chat, not a form — and the kinship is specific, not a bare
"cousin". ``resolve_relation`` maps the narrator's answer to "in what way
is she family?" to one term from the closed kinship vocabulary, anchored
in the known family ("She's my mum's cousin on Fern's side" -> first cousin
once removed). An exact vocabulary term is deterministic; free text goes
through the model with a bounded redo on violation — the review never
records an unvalidated kinship (the vocabulary is the invariant).
"""

from __future__ import annotations

from typing import Any, Protocol

from tools.ai_client import AIClientError, json_object
from tools.memory import ElicitationError, Knowledge

# The closed kinship vocabulary — every term is specific; a bare "cousin"
# is never enough (user, 2026-08-08). Terms are lower-case, narrator-relative.
RELATION_TERMS = frozenset(
    {
        "wife",
        "husband",
        "partner",
        "ex-wife",
        "ex-husband",
        "fiancée",
        "fiancé",
        "mother",
        "father",
        "stepmother",
        "stepfather",
        "adoptive mother",
        "adoptive father",
        "godmother",
        "godfather",
        "daughter",
        "son",
        "stepdaughter",
        "stepson",
        "goddaughter",
        "godson",
        "adopted daughter",
        "adopted son",
        "sister",
        "brother",
        "half-sister",
        "half-brother",
        "stepsister",
        "stepbrother",
        "grandmother",
        "grandfather",
        "great-grandmother",
        "great-grandfather",
        "great-great-grandmother",
        "great-great-grandfather",
        "granddaughter",
        "grandson",
        "great-granddaughter",
        "great-grandson",
        "aunt",
        "uncle",
        "great-aunt",
        "great-uncle",
        "great-great-aunt",
        "great-great-uncle",
        "niece",
        "nephew",
        "great-niece",
        "great-nephew",
        "first cousin",
        "first cousin once removed",
        "first cousin twice removed",
        "second cousin",
        "second cousin once removed",
        "second cousin twice removed",
        "third cousin",
        "cousin-in-law",
        "mother-in-law",
        "father-in-law",
        "sister-in-law",
        "brother-in-law",
        "daughter-in-law",
        "son-in-law",
    }
)

MAX_RESOLVE_ATTEMPTS = 2

_RELATION_SYSTEM_PROMPT = """You resolve how a narrator describes a person's kinship into ONE precise term.

The narrator is confirming a person from a family-archive import. They answered
the question "in what way is this person family?" in their own words — e.g.
"She's my mum's cousin on Fern's side", "he was my grandmother's brother",
"her father's aunt". Work out the precise kinship term RELATIVE TO THE NARRATOR
and return ONLY JSON: {"term": "<one vocabulary term>", "note": "<one short
sentence: how you derived it, naming the anchor person>"}.

Rules:
- The term MUST be one of the vocabulary terms below, verbatim and lower-case.
- When the words route through another person ("mum's cousin"), find that
  person in the family facts and count the generations: a parent's first
  cousin is "first cousin once removed"; a grandparent's sibling is
  "great-uncle"/"great-aunt"; a sibling's child is "niece"/"nephew".
- "On X's side" / "via X" tells you which branch — use it for the note, and
  to choose between terms when the family facts resolve it.
- Never guess a person's identity from the words alone — only the family
  facts name people.
- When the words are ambiguous, pick the closest vocabulary term and say the
  ambiguity in the note.

Vocabulary: %s"""


class _Chat(Protocol):
    def chat(self, system: str, user: str) -> str: ...


def resolve_relation(
    client: _Chat,
    *,
    text: str,
    person: dict[str, Any],
    knowledge: Knowledge,
    who: str,
) -> dict[str, str]:
    """The narrator's answer to "in what way is she family?" -> {term, note}.

    An exact vocabulary term returns immediately without the model; free
    text goes through the model and the returned term is validated against
    the vocabulary — a violation feeds back for one corrective redo, then
    fails loudly (the review never records an unvalidated kinship).
    """
    text = str(text or "").strip()
    if not text:
        raise ElicitationError("no relation given")
    exact = text.lower().strip(".,!? ")
    if exact in RELATION_TERMS:
        return {"term": exact, "note": ""}

    user = "\n\n".join(
        [
            f"Narrator: {who or 'unknown'}",
            f"The person being confirmed: {person.get('name')} — import record: '{person.get('relation', '')}'",
            "The narrator's answer:\n" + text,
            "Known family:\n" + knowledge.render(),
        ]
    )
    prompt = _RELATION_SYSTEM_PROMPT % ", ".join(sorted(RELATION_TERMS))
    for attempt in range(MAX_RESOLVE_ATTEMPTS):
        try:
            raw = client.chat(prompt, user)
            parsed = json_object(raw)
        except AIClientError as e:
            raise ElicitationError(f"relation resolution failed: {e}") from e
        term = str(parsed.get("term", "")).strip().lower()
        note = str(parsed.get("note", "")).strip()
        if term in RELATION_TERMS:
            return {"term": term, "note": note}
        if attempt >= MAX_RESOLVE_ATTEMPTS - 1:
            raise ElicitationError(f"the model returned an unknown relation term: {term!r}")
        user = user + f"\n\n'{term}' is not in the vocabulary. Re-respond with ONLY a vocabulary term."
    raise ElicitationError("relation resolution failed")  # pragma: no cover
