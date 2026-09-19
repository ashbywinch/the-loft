"""The pipeline's JSON contracts, typed per stage.

Every JSON file the row machinery reads is described here as a TypedDict
with a stage-specific name, plus a strict loader. A loader rejects a file
that is not exactly its own stage: a raw word record (with the detector's
`line`/`baseline`/`waistline` fields) cannot be passed where an
adjudicated word record belongs — the loader says which stage it found
and which stage the caller asked for. This is the interchange boundary:
nothing in the row stage should reach past it.

Stages, in order:

- `RawWordsFile` — the detector's words.json: the measured writing
  shapes (line/baseline/waistline per record). Stage: detection.
- `PageBoxesFile` — the detector's boxes.json: the composed boxes plus
  the page size. Stage: detection.
- `StrokesFile` — the reviewer's traced strokes. Stage: detection input.
- `RowsFile` — the adjudicated rows: each row's words' boxes inline
  (self-contained; no index into any words file) plus the row's band.
  Stage: rows.
- `UserLinesFile` — the reviewer's drawn row indications, normalised.
  Stage: rows input.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict


class PageSize(TypedDict):
    width: int
    height: int


class RawWord(TypedDict):
    """A detector record: the writing shape's box in page pixels, with
    the measurements the detector made of it (its text line, baseline and
    waistline)."""

    x0: float
    y0: float
    x1: float
    y1: float
    line: int
    baseline: float
    waistline: float


class RawWordsFile(TypedDict):
    """Detector stage: the words.json written by `tools.reader`."""

    words: list[RawWord]


class Word(TypedDict):
    """A plain word box: the 4-key geometry a row can carry."""

    x0: float
    y0: float
    x1: float
    y1: float


class SectionBox(Word):
    """One composed box in the detector's boxes.json."""


class PageBoxesFile(TypedDict):
    """Detector stage: the boxes.json written by `tools.reader` — each
    box a polygon of [x, y] points, page px."""

    page: PageSize
    boxes: list[list[list[float]]]


class UserLinesFile(TypedDict):
    """Rows-input stage: the reviewer's drawn row indications, one line
    of normalised (0..1) x/y points per polyline."""

    lines: list[list[tuple[float, float]]]


class StrokesFile(TypedDict):
    """Detection-input stage: the reviewer's traces, one line of
    normalised points per polyline."""

    strokes: list[list[tuple[float, float]]]


class Row(TypedDict):
    """One adjudicated row: its identity, kind, display number, the words
    (boxes inline — a row never references another file's word ids), and
    the band (the exact union of the words' boxes, page px)."""

    id: str
    kind: str
    number: int
    word_boxes: list[Word]
    band: Word


class RowsFile(TypedDict):
    """Rows stage: the adjudicated rows.json, the row contract."""

    rows: list[Row]


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


def load_raw_words(path: Path) -> RawWordsFile:
    """The detector's words.json, validated as the raw stage."""
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate(path=path, data=data, key="words", expect="RawWordsFile")
    for i, record in enumerate(data["words"]):
        if not isinstance(record, dict):
            raise ValueError(f"{path}: words[{i}] is not a record")
        missing = {"x0", "y0", "x1", "y1", "line", "baseline", "waistline"} - set(record)
        if missing:
            raise ValueError(f"{path}: words[{i}] missing {sorted(missing)} — not a raw word record")
    return data  # type: ignore[return-value]  # validated field-by-field above; the checker cannot narrow json.loads


def load_rows(path: Path) -> RowsFile:
    """The adjudicated rows.json, validated as the rows stage."""
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate(path=path, data=data, key="rows", expect="RowsFile")
    for i, record in enumerate(data["rows"]):
        if not isinstance(record, dict):
            raise ValueError(f"{path}: rows[{i}] is not a record")
        missing = {"id", "kind", "number", "word_boxes", "band"} - set(record)
        if missing:
            raise ValueError(f"{path}: rows[{i}] missing {sorted(missing)}")
        for j, box in enumerate(record["word_boxes"]):
            _expect_fields(box, path, f"rows[{i}].word_boxes[{j}]", {"x0", "y0", "x1", "y1"}, {"x0", "y0", "x1", "y1"})
        _expect_fields(record["band"], path, f"rows[{i}].band", {"x0", "y0", "x1", "y1"}, {"x0", "y0", "x1", "y1"})
    return data  # type: ignore[return-value]  # validated field-by-field above; the checker cannot narrow json.loads


def load_user_lines(path: Path) -> UserLinesFile:
    """The reviewer's drawn lines, validated."""
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate(path=path, data=data, key="lines", expect="UserLinesFile")
    for i, line in enumerate(data["lines"]):
        if not isinstance(line, list) or not all(
            isinstance(p, list) and len(p) == 2 and all(isinstance(c, (int, float)) for c in p) for p in line
        ):
            raise ValueError(f"{path}: lines[{i}] — expected a polyline of [x, y] pairs")
    return data  # type: ignore[return-value]  # validated polyline-by-polyline above; the checker cannot narrow json.loads


def load_page_boxes(path: Path) -> PageBoxesFile:
    """The detector's boxes.json, validated (page size + box polygons)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate(path=path, data=data, key="boxes", expect="PageBoxesFile")
    if not isinstance(data.get("page"), dict) or not {"width", "height"} <= set(data["page"]):
        raise ValueError(f"{path}: no page size — not a PageBoxesFile")
    for i, box in enumerate(data["boxes"]):
        if (
            not isinstance(box, list)
            or len(box) < 1
            or not all(isinstance(p, list) and len(p) == 2 and all(isinstance(c, (int, float)) for c in p) for p in box)
        ):
            raise ValueError(f"{path}: boxes[{i}] — expected a polygon of [x, y] points")
    return data  # type: ignore[return-value]  # validated page-and-polygons above; the checker cannot narrow json.loads


def load_strokes(path: Path) -> StrokesFile:
    """The reviewer's traces, validated."""
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate(path=path, data=data, key="strokes", expect="StrokesFile")
    return data  # type: ignore[return-value]  # the top-level shape is checked above; the checker cannot narrow json.loads
