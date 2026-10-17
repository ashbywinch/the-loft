"""The Document artefact's contract (document/schemas.py): the draft the
pipeline proposes and the record the review gate agreed are one shape, its
lines carry the writing and what each line is, and an injection names the line
it follows.

The artefact's fields are the pipeline's handoff — the registry's boundaries
and the served payloads are this shape, so the loader is the one rule they
share."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from document.schemas import load_documents, validate_document

DRAFT: dict[str, Any] = {
    "pages": ["page-01.jpg", "page-02.jpg"],
    "greeting": "Dear Mum",
    "signoff": None,
}

LINE: dict[str, Any] = {
    "index": 0,
    "page": "page-01.jpg",
    "text": "Dear Mum",
    "box": [120.0, 340.0, 900.0, 410.0],
    "orientation": 0,
    "box_source": "reader",
    "words": [{"x0": 120.0, "y0": 340.0, "x1": 400.0, "y1": 410.0}],
    "kind": "body",
}


def _line(**overrides: Any) -> dict[str, Any]:
    return {**LINE, **overrides}


def test_a_draft_document_validates() -> None:
    """The pipeline's boundaries entry: the pages and the model's boundary
    evidence — no status (a draft), no lines (nothing transcribed yet)."""
    assert validate_document(DRAFT) == DRAFT


def test_the_agreed_state_is_the_same_shape() -> None:
    """One type, the status is the state (the plan: draft is a state, not a
    second type) — a confirmed document with its lines validates as one."""
    confirmed = {**DRAFT, "status": "confirmed", "lines": [_line()]}
    assert validate_document(confirmed)["status"] == "confirmed"


def test_a_line_carries_its_writing_its_box_and_its_kind() -> None:
    document = {**DRAFT, "lines": [_line(), _line(index=1, kind="injection", injection_after=0)]}
    assert len(validate_document(document)["lines"]) == 2


def test_a_line_without_a_box_is_unanchored_not_invalid() -> None:
    assert validate_document({**DRAFT, "lines": [_line(box=None)]})


def test_an_injection_must_name_the_line_it_follows() -> None:
    with pytest.raises(ValueError, match="an injection names the line it follows"):
        validate_document({**DRAFT, "lines": [_line(kind="injection")]})


def test_body_writing_carries_no_injection_point() -> None:
    with pytest.raises(ValueError, match="an injection names the line it follows"):
        validate_document({**DRAFT, "lines": [_line(injection_after=0)]})


def test_an_unknown_line_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="is not one of"):
        validate_document({**DRAFT, "lines": [_line(kind="rule")]})


def test_an_unknown_status_is_refused() -> None:
    with pytest.raises(ValueError, match="status 'maybe' is not one of"):
        validate_document({**DRAFT, "status": "maybe"})


def test_a_document_needs_its_pages() -> None:
    with pytest.raises(ValueError, match="pages — expected a non-empty list"):
        validate_document({**DRAFT, "pages": []})
    with pytest.raises(ValueError, match="pages — every page must be a name"):
        validate_document({**DRAFT, "pages": [""]})


def test_a_document_missing_its_boundary_evidence_is_refused() -> None:
    with pytest.raises(ValueError, match="missing"):
        validate_document({"pages": ["page-01.jpg"]})


def test_a_line_missing_a_field_is_refused() -> None:
    bare = _line()
    del bare["kind"]
    with pytest.raises(ValueError, match=r"lines\[0\] — expected a document line with"):
        validate_document({**DRAFT, "lines": [bare]})


def test_a_line_whose_box_is_not_four_numbers_is_refused() -> None:
    with pytest.raises(ValueError, match=r"lines\[0\]\.box"):
        validate_document({**DRAFT, "lines": [_line(box=[1.0, 2.0])]})


def test_the_artefact_loads_as_the_list_of_documents(tmp_path: Path) -> None:
    path = tmp_path / "boundaries.json"
    path.write_text(json.dumps([DRAFT]), encoding="utf-8")
    assert load_documents(path) == [DRAFT]


def test_a_file_that_is_not_the_document_list_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "boundaries.json"
    path.write_text(json.dumps({"documents": [DRAFT]}), encoding="utf-8")
    with pytest.raises(ValueError, match="not a Document list"):
        load_documents(path)
