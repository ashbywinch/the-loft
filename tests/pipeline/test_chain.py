"""Tests for the ingest chain: document-boundary grouping, the guess
prompt/parse, and the review gate — the deterministic contracts. The
model call itself is an eval (real model); the orient/OCR stages run on
the real scans."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import override

import pytest
from PIL import Image

from document.word import Word
from document.words import Words
from pipeline.batch_record import BatchRecord
from pipeline.chain import (
    BatchRun,
    Classification,
    _read_pages,
    review,
)
from pipeline.detect.reader import Reading
from pipeline.store import PipelineStore
from tools.loft_paths import LoftPaths


def _reading() -> Reading:
    """A one-line, one-word page as the reader hands it over."""
    return Reading(
        lines=[
            {
                "index": 0,
                "text": "",
                "box": [0, 0, 40, 10],
                "orientation": 0,
                "box_source": "reader",
                "words": [0],
            }
        ],
        words=[Word(1.0, 1.0, 9.0, 9.0, line=0, baseline=9.0, waistline=1.0)],
        width=40,
        height=40,
    )


def _page(tmp_path: Path) -> tuple[Path, Path]:
    batch = tmp_path / "adopt-0003"
    guess, oriented = batch / "ocr-guess", batch / "oriented"
    guess.mkdir(parents=True)
    oriented.mkdir(parents=True)
    Image.new("L", (40, 40), 255).save(oriented / "p1.jpg")
    return guess, oriented


def test_read_pages_writes_the_page_text_from_its_rows(tmp_path: Path) -> None:
    """The page's text is its rows' reading — the file the review surface's
    drafts read. (The guess stage, which used to write it, is gone.)"""
    guess, oriented = _page(tmp_path)
    row_texts = {1: "the draft row"}

    _read_pages(
        ["p1.jpg"],
        guess,
        oriented,
        tmp_path,
        "adopt-0003",
        _reading=lambda _image: _reading(),
        _rows_text=lambda _image, _out: row_texts,
    )
    assert (guess / "p1.txt").read_text() == "the draft row\n"


def test_read_pages_writes_the_rows_the_model_read_and_the_words(tmp_path: Path) -> None:
    """The read stage persists both halves of the reading: the row boxes, each
    carrying the writing the model READ for that row, and the words the
    drawn-lines correction groups — a page persisted without its words cannot
    be corrected in the review.

    The row's text is its own reading, not the page guess's text indexed onto
    the rows in order: indexing put a sentence one row out wherever the page's
    rows and its text lines ran differently."""
    guess, oriented = _page(tmp_path)
    reading = _reading()

    _read_pages(
        ["p1.jpg"],
        guess,
        oriented,
        tmp_path,
        "adopt-0003",
        _reading=lambda _image: reading,
        _rows_text=lambda _image, _out: {1: "the model read this row"},
    )

    rows = json.loads((guess / "p1.rows.json").read_text(encoding="utf-8"))
    assert rows["lines"][0]["text"] == "the model read this row"
    assert json.loads((guess / "p1.words.json").read_text(encoding="utf-8")) == Words(reading.words).to_dict()


def test_a_page_the_reading_returns_nothing_for_is_left_unwritten(tmp_path: Path) -> None:
    """The marker rule: an artifact that looks done but is empty is worse than
    a page to re-run. A reading that answers nothing writes NO rows.json, so
    the page stays to-do instead of looking read."""
    guess, oriented = _page(tmp_path)

    _read_pages(
        ["p1.jpg"],
        guess,
        oriented,
        tmp_path,
        "adopt-0003",
        _reading=lambda _image: _reading(),
        _rows_text=lambda _image, _out: {},
    )

    assert not (guess / "p1.rows.json").exists(), "an empty reading was recorded as done"
    assert not (guess / "p1.words.json").exists(), "the words were written without a reading"


def test_a_corrected_page_is_re_read_into_the_reading(tmp_path: Path) -> None:
    """The reviewer's drawn lines are the rows the page is read against: the
    reading's lines ARE the corrected rows, carrying their own text, and the
    correction's sha closes the loop so the next pass does not read again."""
    guess, oriented = _page(tmp_path)
    reading = _reading()
    _read_pages(
        ["p1.jpg"],
        guess,
        oriented,
        tmp_path,
        "adopt-0003",
        _reading=lambda _image: reading,
        _rows_text=lambda _image, _out: {1: "the draft row"},
    )
    (guess / "p1.row-adjustments.json").write_text(
        json.dumps({"lines": [[[0.0, 0.125], [1.0, 0.125]]]}), encoding="utf-8"
    )
    calls: list[int] = []

    def corrected(_image, rows, _out):
        calls.append(len(rows))
        return {row.number: f"corrected {row.number}" for row in rows}

    _read_pages(
        ["p1.jpg"],
        guess,
        oriented,
        tmp_path,
        "adopt-0003",
        _reading=lambda _image: reading,
        _rows_text=lambda _image, _out: {1: "the draft row"},
        _corrected_text=corrected,
    )

    assert calls == [1]  # the page was re-read once, against the drawn line
    stored = json.loads(PipelineStore(tmp_path).read_latest("adopt-0003/ocr-guess/p1.rows.json"))
    assert stored["lines"][0]["text"] == "corrected 1"
    assert stored["lines"][0]["box_source"] == "rows-adjusted"
    assert stored["revision"] == 2  # the draft reading's next version
    assert stored["corrected"]  # the drawn lines this reading was built from
    corrected_rows = json.loads((guess / "p1.rows-adjusted.json").read_text(encoding="utf-8"))
    assert corrected_rows["rows"][0]["text"] == "corrected 1"
    assert corrected_rows["rows"][0]["stage"] == "raw"

    # the reading now carries these lines: the same correction is not re-read
    _read_pages(
        ["p1.jpg"],
        guess,
        oriented,
        tmp_path,
        "adopt-0003",
        _reading=lambda _image: reading,
        _rows_text=lambda _image, _out: {1: "the draft row"},
        _corrected_text=corrected,
    )
    assert calls == [1]


def _flag(page: str, starts: bool = False, ends: bool = False, **extra: object) -> dict[str, object]:
    return {"page": page, "starts_document": starts, "ends_document": ends, **extra}


def _review_batch(tmp_path: Path, answers: list[str]) -> tuple[Path, list[str]]:
    """A minimal processed batch: registry record + guess outputs."""
    registry = tmp_path / "registry"
    registry.mkdir()
    batch = "adopt-0001"
    record = {"batch_id": batch, "path": str(tmp_path / "folder"), "label": "", "status": "review"}
    (registry / f"{batch}.json").write_text(json.dumps(record), encoding="utf-8")
    work = tmp_path / "work" / batch / "ocr-guess"
    work.mkdir(parents=True)
    (work / "p1.txt").write_text("Dear Mum,", encoding="utf-8")
    (work / "p2.txt").write_text("Love, Zelda", encoding="utf-8")
    (work / "boundaries.json").write_text(
        json.dumps([{"pages": ["p1.jpg", "p2.jpg"], "greeting": None, "signoff": None}]),
        encoding="utf-8",
    )
    answers_iter = iter(answers)
    lines_written: list[str] = []

    def fake_line(_prompt: str) -> str:
        return next(answers_iter)

    review(
        batch,
        paths=LoftPaths(registry_dir=registry, work_dir=tmp_path / "work", archive_dir=tmp_path / "archive"),
        readline=fake_line,
        write_line=lines_written.append,
    )
    return registry / f"{batch}.json", lines_written


def test_review_accept_mints_the_archive_item(tmp_path: Path) -> None:
    record_path, _ = _review_batch(tmp_path, ["\n", "A letter from Zelda\n", "1963-05-14\n"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["status"] == "confirmed"
    assert record["boundaries"][0]["status"] == "confirmed"
    assert record["boundaries"][0]["item_id"] == "doc-1963-05-14"
    item = json.loads((tmp_path / "archive" / "assets" / "doc-1963-05-14" / "item.json").read_text(encoding="utf-8"))
    assert item["title"] == "A letter from Zelda"
    transcription = tmp_path / "archive" / "assets" / "doc-1963-05-14" / "transcription.txt"
    assert transcription.read_text(encoding="utf-8") == "Dear Mum,\nLove, Zelda"


def test_review_reject_records_the_rejection(tmp_path: Path) -> None:
    record_path, _ = _review_batch(tmp_path, ["r\n"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["boundaries"][0]["status"] == "rejected"
    assert not (tmp_path / "archive" / "assets").exists()  # a rejection mints nothing


def test_review_skips_photo_only_documents(tmp_path: Path) -> None:
    """A photo-only document (the postcard's standalone fronts)
    has nothing to transcribe — the confirm gate notes it and moves on;
    the text document confirms normally, and the photo doc stays "review"
    for the people/places identification flow."""
    registry = tmp_path / "registry"
    registry.mkdir()
    batch = "adopt-0001"
    record = {"batch_id": batch, "path": str(tmp_path / "folder"), "label": "", "status": "review"}
    (registry / f"{batch}.json").write_text(json.dumps(record), encoding="utf-8")
    work = tmp_path / "work" / batch / "ocr-guess"
    work.mkdir(parents=True)
    (work / "p2.txt").write_text("Dear Mum,", encoding="utf-8")
    (work / "boundaries.json").write_text(
        json.dumps(
            [
                {"pages": ["photo1.jpg"], "greeting": None, "signoff": None},
                {"pages": ["p2.jpg"], "greeting": None, "signoff": None},
            ]
        ),
        encoding="utf-8",
    )
    lines_written: list[str] = []
    answers = iter(["\n", "A letter\n", "1963-05-14\n"])
    review(
        batch,
        paths=LoftPaths(registry_dir=registry, work_dir=tmp_path / "work", archive_dir=tmp_path / "archive"),
        readline=lambda _prompt: next(answers),
        write_line=lines_written.append,
    )
    record = json.loads((registry / f"{batch}.json").read_text(encoding="utf-8"))
    assert record["status"] == "confirmed"
    # replace-by-pages: only the reviewed document lands in the registry;
    # the unconfirmed photo doc is absent — the drafts default reads it
    # "review" until the identification flow claims it
    assert record["boundaries"] == [
        {"pages": ["p2.jpg"], "greeting": None, "signoff": None, "status": "confirmed", "item_id": "doc-1963-05-14"}
    ]
    assert any("no text to check" in line for line in lines_written)
    transcription = tmp_path / "archive" / "assets" / "doc-1963-05-14" / "transcription.txt"
    assert transcription.read_text(encoding="utf-8") == "Dear Mum,"


def test_review_photo_only_batch_confirms_nothing(tmp_path: Path) -> None:
    """Make confirm on a photo-only batch must not error."""
    import json as _json

    registry = tmp_path / "registry"
    registry.mkdir()
    batch = "adopt-0002"
    (registry / f"{batch}.json").write_text(
        _json.dumps({"batch_id": batch, "path": str(tmp_path), "status": "review"}), encoding="utf-8"
    )
    work = tmp_path / "work" / batch
    classify = work / "classify.json"
    classify.parent.mkdir(parents=True)
    classify.write_text(_json.dumps({"p1.jpg": {"kind": "photo"}}), encoding="utf-8")

    lines: list[str] = []
    review(
        batch,
        paths=LoftPaths(registry_dir=registry, work_dir=tmp_path / "work", archive_dir=tmp_path / "archive"),
        readline=lambda _p: "r\n",
        write_line=lines.append,
    )
    assert any("no text pages" in line for line in lines)


def test_a_failed_pass_puts_the_batch_back_in_the_queue(tmp_path: Path) -> None:
    """The registry's records ARE the worker's queue: a pass that dies half-way
    must leave the batch `pending` again, or a crash strands it in `importing`
    where no sweep looks for it."""

    class _Broken(BatchRun):
        @override
        def classify_pages(self, pages: list[Path], **_kwargs: object) -> Classification:
            raise RuntimeError("the classifier died")

    registry = tmp_path / "registry"
    registry.mkdir()
    folder = tmp_path / "folder"
    folder.mkdir()
    Image.new("RGB", (8, 8), (255, 255, 255)).save(folder / "p1.jpg")
    batch = "adopt-0001"
    record = {
        "batch_id": batch,
        "path": str(folder),
        "status": "pending",
        "pages": {"p1.jpg": "hash"},
        "fingerprint": ["hash"],
    }
    _ = (registry / f"{batch}.json").write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(RuntimeError, match="classifier died"):
        _Broken(batch, registry_dir=registry, work_dir=tmp_path / "work").process()

    saved = json.loads((registry / f"{batch}.json").read_text(encoding="utf-8"))
    assert saved["status"] == "pending"


def test_a_processing_pass_stamps_when_it_started(tmp_path: Path) -> None:
    """The worker's sweep tells a live pass from a killed one by this stamp —
    a pass that is killed cannot reset its own record — and on this host the
    pid decides, so the stamp carries the process and its host."""
    registry = tmp_path / "registry"
    registry.mkdir()
    record = BatchRecord(batch_id="adopt-0001", path=tmp_path)

    BatchRun(
        "adopt-0001", registry_dir=registry, work_dir=tmp_path / "work", archive_dir=tmp_path / "archive"
    ).update_status(record, BatchRecord.STATUS_PROCESSING)

    saved = json.loads((registry / "adopt-0001.json").read_text(encoding="utf-8"))
    assert saved["status"] == "importing"
    assert saved["started_at"]
    assert saved["started_pid"] == os.getpid()
    assert saved["started_host"] == socket.gethostname()


def test_the_boundary_call_judges_documents_over_the_pages_readings() -> None:
    """Document grouping survives the guess stage's removal: the model judges
    boundaries over each page's READING (it does not re-read the text), and the
    grouping scorer weighs that against the physical evidence."""
    from pipeline.chain import _boundary_prompt, page_flags
    from pipeline.page_text import PageText

    system, user = _boundary_prompt(
        [PageText("p1.jpg", "Dear Mum,"), PageText("p2.jpg", "Yours, Nora")], "Box 1", ["nora"], ["hull"]
    )
    assert "do not correct or rewrite" in system
    assert "STARTS a document" in system and "ENDS one at a sign-off" in system
    assert "nora" in system and "Box 1" in system
    assert "vision model's reading" in user and "Dear Mum," in user

    def client(_system: str, _user: str) -> str:
        return json.dumps(
            {
                "pages": [
                    {
                        "page": "p1.jpg",
                        "text": "",
                        "starts_document": True,
                        "ends_document": False,
                        "greeting": "Dear Mum,",
                        "signoff": None,
                    },
                    {
                        "page": "p2.jpg",
                        "text": "",
                        "starts_document": False,
                        "ends_document": True,
                        "greeting": None,
                        "signoff": "Yours, Nora",
                    },
                ]
            }
        )

    flags = page_flags([PageText("p1.jpg", "Dear Mum,"), PageText("p2.jpg", "Yours, Nora")], "Box 1", [], [], client)
    assert [flag.page for flag in flags] == ["p1.jpg", "p2.jpg"]
    assert flags[0].starts_document and flags[1].ends_document
    assert flags[0].greeting == "Dear Mum,"
