"""The pipeline's JSON contracts, typed per stage.

Every JSON file the row machinery reads is described here as a TypedDict
with a stage-specific name, plus a strict loader. A loader rejects a file
that is not exactly its own stage: a raw word record (with the detector's
`line`/`baseline`/`waistline` fields) cannot be passed where an
adjudicated word record belongs — the loader says which stage it found
and which stage the caller asked for. This is the interchange boundary:
nothing in the row stage should reach past it.

Stages, in order:

- `Words` — the detector's words.json: the measured writing
  shapes (line/baseline/waistline per record). Stage: detection.
- `PageBoxes` — the detector's boxes.json: the composed boxes plus
  the page size. Stage: detection.
- `Strokes` — the reviewer's traced strokes. Stage: detection input.
- `Rows` — the adjudicated rows: each row's words' boxes inline
  (self-contained; no index into any words file) plus the row's band.
  Stage: rows.
- `UserRowAdjustments` — the reviewer's drawn row adjustments, normalised.
  Stage: rows input.
- `Document` — the document artefact: its pages, its writing line by line,
  and its state (the draft the pipeline proposed, or the record the review
  gate agreed). Stages: proposed transcripts, agreed transcripts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, NotRequired, TypedDict

from document.transcript import KINDS


class PageSize(TypedDict):
    width: int
    height: int


class Word(TypedDict):
    """A word: the box in page pixels, with the measurements the
    detector made of it (its text line, baseline and waistline) when it
    has them. One type — the words artifact always carries the measures;
    a row's inline word_boxes carry the box alone."""

    x0: float
    y0: float
    x1: float
    y1: float
    line: NotRequired[int]
    baseline: NotRequired[float]
    waistline: NotRequired[float]


class Words(TypedDict):
    """Detector stage: the words.json written by `pipeline.detect.reader`."""

    words: list[Word]


class Boxes(TypedDict):
    """Detector stage: the boxes.json written by `pipeline.detect.reader` — each
    box a polygon of [x, y] points, page px."""

    page: PageSize
    boxes: list[list[list[float]]]


class UserRowAdjustments(TypedDict):
    """Rows-input stage: the reviewer's drawn row indications, one line
    of normalised (0..1) x/y points per polyline."""

    lines: list[list[tuple[float, float]]]


class Traces(TypedDict):
    """Detection-input stage: the reviewer's drawn traces, one line of
    normalised points per polyline."""

    strokes: list[list[tuple[float, float]]]


class Row(TypedDict):
    """One adjudicated row: its identity, kind, display number, the words
    (boxes inline — a row never references another file's word ids), the
    band (the exact union of the words' boxes, page px), the row's own text,
    and its R7 trust stage ("raw" | "guess" | "confirmed" | "" unread)."""

    id: str
    kind: str
    number: int
    word_boxes: list[Word]
    band: Word
    text: str
    stage: str


class Rows(TypedDict):
    """Rows stage: the adjudicated rows.json, the row contract."""

    rows: list[Row]


# the Document's states: the draft the pipeline proposed and the review gate
# has not agreed ("review" — the pipeline's word for the plan's draft state),
# the reviewer's agreement, and the reviewer's rejection of the grouping
DOCUMENT_STATUSES = ("review", "confirmed", "rejected")


class DocumentLine(TypedDict):
    """One line of a Document's writing, in reading order: what it says, where
    it sits on its page, and what it is — body writing, an injection (naming
    the line it follows, `KINDS`), or marginalia.

    `box` is the line's box on its page, page pixels ([x0, y0, x1, y1]), or
    None when no geometry anchors it; `box_source` says how the box was
    found ("reader" for a reading's own line). `words` are the line's word
    boxes, inline like a row's (a line never references another file's word
    ids). `conf` is the anchor's confidence where a reading scored one.
    """

    index: int
    page: str
    text: str
    box: list[float] | None
    orientation: int
    box_source: str
    words: list[Word]
    kind: str
    conf: NotRequired[float]
    injection_after: NotRequired[int]


class Document(TypedDict):
    """The Document artefact (stages 5 and 6): the document's pages, its
    writing line by line, and its state — the draft the pipeline proposes and
    the record the review gate agreed are ONE type; the status is the state
    (docs/PLAN/pipeline-stages-plan.md: draft is a state, not a second type).

    `pages` and the boundary evidence the grouping scored (`greeting`,
    `signoff`) are what opened the document; `lines` is its writing, empty
    until the transcription stage fills it; `status` is absent on a draft
    entry (the pipeline's `boundaries.json`), "review" once served, and the
    reviewer's decision once the gate has run.
    """

    pages: list[str]
    greeting: str | None
    signoff: str | None
    status: NotRequired[str]
    lines: NotRequired[list[DocumentLine]]


def _validate(path: Path, data: Any, key: str, expect: str) -> None:
    if not isinstance(data, dict) or key not in data:
        raise ValueError(f"{path}: not a {expect} (no top-level '{key}')")
    rows = data[key]
    if not isinstance(rows, list):
        raise ValueError(f"{path}: '{key}' is not a list — not a {expect}")


def _expect_fields(record: Any, path: Path, what: str, required: set[str], allowed: set[str]) -> None:
    if not isinstance(record, dict):
        raise ValueError(f"{path}: a {what} record is not an object")
    missing = required - set(record)
    if missing:
        raise ValueError(f"{path}: {what} record missing {sorted(missing)}")
    extra = set(record) - allowed
    if extra:
        raise ValueError(
            f"{path}: {what} record has detector-stage fields {sorted(extra)} — "
            f"this is the row stage; a raw words file belongs to the detector stage"
        )


def load_words(path: Path) -> Words:
    """The detector's words.json, validated as the raw stage."""
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate(path=path, data=data, key="words", expect="Words")
    for i, record in enumerate(data["words"]):
        if not isinstance(record, dict):
            raise ValueError(f"{path}: words[{i}] is not a record")
        missing = {"x0", "y0", "x1", "y1", "line", "baseline", "waistline"} - set(record)
        if missing:
            raise ValueError(f"{path}: words[{i}] missing {sorted(missing)} — not a raw word record")
    return data  # type: ignore[return-value]  # validated field-by-field above; the checker cannot narrow json.loads


# the per-row trust stages, in trust order (MULTI-DOC-IMPORT-PRD R7): the
# machine's raw attempt, the system's corrected guess, the user's confirmation
# — plus "" for a row no reading has filled yet
ROW_STAGES = ("", "raw", "guess", "confirmed")


def load_rows(path: Path) -> Rows:
    """The adjudicated rows.json, validated as the rows stage."""
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate(path=path, data=data, key="rows", expect="Rows")
    for i, record in enumerate(data["rows"]):
        if not isinstance(record, dict):
            raise ValueError(f"{path}: rows[{i}] is not a record")
        missing = {"id", "kind", "number", "word_boxes", "band"} - set(record)
        if missing:
            raise ValueError(f"{path}: rows[{i}] missing {sorted(missing)}")
        # text and stage are the row's reading and its trust; a row file from
        # before a reading ran carries neither, which reads as unread ("")
        if "stage" in record and record["stage"] not in ROW_STAGES:
            raise ValueError(f"{path}: rows[{i}].stage {record['stage']!r} is not one of {sorted(ROW_STAGES)}")
        if "text" in record and not isinstance(record["text"], str):
            raise ValueError(f"{path}: rows[{i}].text is not a string")
        for j, box in enumerate(record["word_boxes"]):
            _expect_fields(box, path, f"rows[{i}].word_boxes[{j}]", {"x0", "y0", "x1", "y1"}, {"x0", "y0", "x1", "y1"})
        _expect_fields(record["band"], path, f"rows[{i}].band", {"x0", "y0", "x1", "y1"}, {"x0", "y0", "x1", "y1"})
    return data  # type: ignore[return-value]  # validated field-by-field above; the checker cannot narrow json.loads


def validate_user_row_adjustments(data: Any, *, path: Path | None = None) -> UserRowAdjustments:
    """The reviewer's drawn row lines, validated — ONE rule for the file
    loader and the HTTP boundary (the write seam validates its own input)."""
    label = f"{path}: " if path is not None else ""
    _validate(path=path or Path("<request>"), data=data, key="lines", expect="UserRowAdjustments")
    for i, line in enumerate(data["lines"]):
        if not isinstance(line, list) or not all(
            isinstance(point, list) and len(point) == 2 and all(isinstance(c, (int, float)) for c in point)
            for point in line
        ):
            raise ValueError(f"{label}lines[{i}] — expected a polyline of [x, y] pairs")
    return data  # type: ignore[return-value]  # validated polyline-by-polyline above; the checker cannot narrow json.loads


def load_user_row_adjustments(path: Path) -> UserRowAdjustments:
    """The reviewer's drawn lines, validated."""
    return validate_user_row_adjustments(json.loads(path.read_text(encoding="utf-8")), path=path)


def load_boxes(path: Path) -> Boxes:
    """The detector's boxes.json, validated (page size + box polygons)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate(path=path, data=data, key="boxes", expect="PageBoxes")
    if not isinstance(data.get("page"), dict) or not {"width", "height"} <= set(data["page"]):
        raise ValueError(f"{path}: no page size — not a PageBoxes")
    for i, box in enumerate(data["boxes"]):
        if (
            not isinstance(box, list)
            or len(box) < 1
            or not all(isinstance(p, list) and len(p) == 2 and all(isinstance(c, (int, float)) for c in p) for p in box)
        ):
            raise ValueError(f"{path}: boxes[{i}] — expected a polygon of [x, y] points")
    return data  # type: ignore[return-value]  # validated page-and-polygons above; the checker cannot narrow json.loads


def validate_document(record: Any, *, path: Path | None = None) -> Document:
    """One document record, validated — ONE rule for the file loader, the
    registry's boundaries and the served payloads (the write seam validates
    its own input)."""
    label = f"{path}: " if path is not None else ""
    _expect_fields(
        record, path or Path("<document>"), "document", {"pages", "greeting", "signoff"}, set(Document.__annotations__)
    )
    _validate_pages(record["pages"], label)
    for field in ("greeting", "signoff"):
        if record[field] is not None and not isinstance(record[field], str):
            raise ValueError(f"{label}{field} — expected a string or None")
    if "status" in record and record["status"] not in DOCUMENT_STATUSES:
        raise ValueError(f"{label}status {record['status']!r} is not one of {list(DOCUMENT_STATUSES)}")
    for i, line in enumerate(record.get("lines") or []):
        _validate_document_line(line, f"{label}lines[{i}]")
    return record  # type: ignore[return-value]  # validated field-by-field above; the checker cannot narrow json.loads


def _validate_pages(pages: Any, label: str) -> None:
    """The document's pages: a non-empty list of page names (they become path
    segments in every reader, so a nameless or non-string page is refused)."""
    if not isinstance(pages, list) or not pages:
        raise ValueError(f"{label}pages — expected a non-empty list of page names")
    if not all(isinstance(page, str) and page for page in pages):
        raise ValueError(f"{label}pages — every page must be a name")


# the document line's typed fields — the required set is derived from this
# table plus the fields with their own checks below, so the two cannot drift
_LINE_FIELD_TYPES: Mapping[str, type] = MappingProxyType(
    {"index": int, "page": str, "text": str, "orientation": int, "box_source": str}
)
_LINE_OTHER_FIELDS = ("box", "words", "kind")  # checked by their own rules, never by bare type


def _validate_document_line(line: Any, label: str) -> None:
    """One document line: its fields' types, its box, its words, and its kind
    with the injection point that kind requires."""
    required = set(_LINE_FIELD_TYPES) | set(_LINE_OTHER_FIELDS)
    if not isinstance(line, dict) or required - set(line):
        raise ValueError(f"{label} — expected a document line with {sorted(required)}")
    for field, expected in _LINE_FIELD_TYPES.items():
        if not isinstance(line[field], expected):
            raise ValueError(f"{label}.{field} — expected {expected.__name__}")
    if not line["page"]:
        raise ValueError(f"{label}.page — expected a page name")
    _validate_line_box(line["box"], label)
    _validate_line_words(line["words"], label)
    _validate_line_kind(line, label)


def _validate_line_box(box: Any, label: str) -> None:
    """The line's box: [x0, y0, x1, y1] in page pixels, or None when no
    geometry anchors the line."""
    if box is None:
        return
    if not isinstance(box, list) or len(box) != 4 or not all(isinstance(c, (int, float)) for c in box):
        raise ValueError(f"{label}.box — expected [x0, y0, x1, y1] or None")


def _validate_line_words(words: Any, label: str) -> None:
    """The line's word boxes, inline — each a word box, never another file's
    word ids."""
    if not isinstance(words, list):
        raise ValueError(f"{label}.words — expected a list of word boxes")
    for j, word in enumerate(words):
        _expect_fields(word, Path(label), f"{label}.words[{j}]", {"x0", "y0", "x1", "y1"}, {"x0", "y0", "x1", "y1"})


def _validate_line_kind(line: dict[str, Any], label: str) -> None:
    """The line's kind, and the injection point that kind requires — an
    injection names the line it follows, and nothing else carries a point."""
    kind = line["kind"]
    if kind not in KINDS:
        raise ValueError(f"{label}.kind {kind!r} is not one of {list(KINDS)}")
    if (kind == "injection") != ("injection_after" in line):
        raise ValueError(
            f"{label} — an injection names the line it follows (injection_after), and nothing else carries one"
        )


def load_documents(path: Path) -> list[Document]:
    """The batch's documents (the boundaries artefact), validated as the
    Document stage — the artefact is the list itself."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: not a Document list — the boundaries artefact is a list of documents")
    return [validate_document(record, path=path) for record in data]
