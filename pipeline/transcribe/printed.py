"""A PRINTED page read in one call: the VLM's transcription, no rows.

The row pipeline measures the writing's geometry because handwriting has to be
grouped before it can be read; printed text needs none of that — the page is
already lines, and grouping it only invents work (and the ink measurer is tuned
for handwriting, so printed columns defeat it). So a printed pile's read stage
is one vision call per page: verbatim, the page's own line structure, nothing
tidied. The result is the page's draft transcription — the same `<page>.txt`
the reading stage writes, so the review surface consumes it unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.model.config import ModelConfig
from pipeline.model.transcription import Transcription
from pipeline.model.vlm import VlmPrompts, transcribe_image_vlm
from pipeline.model.vlm_answer import VlmAnswer


def printed_prompt() -> str:
    """The user message's instruction for a printed page: the house reading
    rules and the plain-text format, aimed at print."""
    note = (
        "This page is PRINTED text (a newspaper, a form, a typed record), not handwriting. "
        "Read it column by column in the page's reading order; keep every printed line on "
        "its own line, and keep the page's headings, labels and marginal notes."
    )
    return f"{note}\n\n{VlmPrompts.FORMAT_PLAIN}"


def _as_lines(answer: str) -> str:
    """The answer as the page's text. The call asks for plain text; a model
    that answers the JSON format anyway is read by the transcription record's
    own parser, and an answer that is neither stays as it came."""
    text = answer.strip()
    if not text.startswith("{"):
        return text
    try:
        return Transcription.from_payload(json.loads(text), text).text
    except json.JSONDecodeError:
        return text  # not JSON after all — the answer IS the transcription


def printed_transcript(image: Path, *, model: str = ModelConfig.VISION_MODEL) -> tuple[str, VlmAnswer]:
    """One printed page transcribed: the page's text and the call's cost."""
    answer = transcribe_image_vlm(image, model=model, system=VlmPrompts.SYSTEM, user_text=printed_prompt())
    return _as_lines(answer.answer), answer


def structured_prompt() -> str:
    """The user message's instruction for a FORM page: keep the pairing of
    label and value, as a markdown table — a form read as prose loses its
    meaning (docs/PLAN/page-categories.md)."""
    note = (
        "This page is a FORM: printed fields with values filled in (typed or "
        "handwritten). Read it as STRUCTURE, not prose: every label with the value "
        "that belongs to it, one row per field, as a markdown table with the "
        'heading "| Field | Value |". Keep the form\'s own wording for the labels, '
        "its own spelling for the values, and an empty cell where a field is blank. "
        "Keep rows, columns and any marginal note as separate rows of the table. "
        "Fix nothing, summarise nothing, invent nothing."
    )
    return f"{note}\n\n{VlmPrompts.FORMAT_PLAIN}"


def structured_transcript(image: Path, *, model: str = ModelConfig.VISION_MODEL) -> tuple[str, VlmAnswer]:
    """One form page read as structure: the table text and the call's cost."""
    answer = transcribe_image_vlm(image, model=model, system=VlmPrompts.SYSTEM, user_text=structured_prompt())
    return _as_lines(answer.answer), answer
