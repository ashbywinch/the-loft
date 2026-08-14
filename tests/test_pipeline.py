"""Tests for the ingest chain: document-boundary grouping, the guess
prompt/parse, and the review gate — the deterministic contracts. The
model call itself is an eval (real model); the orient/OCR stages run on
the real scans."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.pipeline import _guess_prompt, apply_routes, group_documents, guess_pages, review
from tools.registry import RegistryError


def _flag(page: str, starts: bool = False, ends: bool = False, **extra: object) -> dict[str, object]:
    return {"page": page, "starts_document": starts, "ends_document": ends, **extra}


def test_group_documents_single_letter_across_three_pages() -> None:
    flags = [
        _flag("p1.jpg", starts=True, greeting="Dear Mum,"),
        _flag("p2.jpg"),
        _flag("p3.jpg", ends=True, signoff="Love, Zelda"),
    ]
    docs = group_documents(flags)
    assert len(docs) == 1
    assert docs[0]["pages"] == ["p1.jpg", "p2.jpg", "p3.jpg"]
    assert docs[0]["greeting"] == "Dear Mum,"
    assert docs[0]["signoff"] == "Love, Zelda"


def test_group_documents_two_letters_in_one_batch() -> None:
    flags = [
        _flag("p1.jpg", starts=True),
        _flag("p2.jpg", ends=True),
        _flag("p3.jpg", starts=True),
        _flag("p4.jpg", ends=True),
    ]
    docs = group_documents(flags)
    assert [d["pages"] for d in docs] == [["p1.jpg", "p2.jpg"], ["p3.jpg", "p4.jpg"]]


def test_group_documents_single_page_letter() -> None:
    docs = group_documents([_flag("p1.jpg", starts=True, ends=True)])
    assert docs[0]["pages"] == ["p1.jpg"]


def test_group_documents_no_flags_is_one_open_document() -> None:
    docs = group_documents([_flag("p1.jpg"), _flag("p2.jpg")])
    assert len(docs) == 1
    assert docs[0]["pages"] == ["p1.jpg", "p2.jpg"]
    assert docs[0]["signoff"] is None  # unclosed — the reviewer sees it


def test_apply_routes_routes_text_by_density_and_skips_images() -> None:
    classify = {"a.jpg": {"kind": "text"}, "b.jpg": {"kind": "photo"}}
    rotations = {"a.jpg": {"strong": 42}}  # cursive-class density
    out = apply_routes(classify, rotations)
    assert out["a.jpg"]["route"] == "cursive"
    assert out["b.jpg"]["route"] is None  # never transcribed


def test_guess_prompt_carries_the_standing_knowledge() -> None:
    system, user = _guess_prompt([("p1.jpg", "raw text")], "Box 1", ["person-one"], ["place-one"])
    assert "person-one" in system
    assert "place-one" in system
    assert "Box 1" in system
    assert "p1.jpg" in user
    assert "raw text" in user


def test_guess_pages_parses_the_model_json() -> None:
    def fake_client(_system: str, _user: str) -> str:
        return json.dumps(
            {
                "pages": [
                    {
                        "page": "p1.jpg",
                        "text": "Dear Mum,",
                        "starts_document": True,
                        "ends_document": False,
                        "greeting": "Dear Mum,",
                        "signoff": None,
                    },
                    {
                        "page": "p2.jpg",
                        "text": "Love, Zelda",
                        "starts_document": False,
                        "ends_document": True,
                        "greeting": None,
                        "signoff": "Love, Zelda",
                    },
                ]
            }
        )

    flags = guess_pages([("p1.jpg", "x"), ("p2.jpg", "y")], "", [], [], fake_client)
    assert flags[0]["starts_document"] is True
    assert flags[1]["signoff"] == "Love, Zelda"


def test_guess_pages_rejects_garbage_json() -> None:
    with pytest.raises(RegistryError, match="unparseable"):
        _ = guess_pages([("p1.jpg", "x")], "", [], [], lambda _s, _u: "not json")
    with pytest.raises(RegistryError, match="malformed"):
        _ = guess_pages([("p1.jpg", "x")], "", [], [], lambda _s, _u: '{"pages": [{"page": "p1.jpg"}]}')


def test_guess_pages_parses_string_flags_without_coercion() -> None:
    def fake_client(_system: str, _user: str) -> str:
        return json.dumps(
            {
                "pages": [
                    {"page": "p1.jpg", "text": "x", "starts_document": "false", "ends_document": "true"},
                ]
            }
        )

    flags = guess_pages([("p1.jpg", "x")], "", [], [], fake_client)
    assert flags[0]["starts_document"] is False  # "false" must not coerce to True
    assert flags[0]["ends_document"] is True


def test_guess_pages_rejects_oversized_batches() -> None:
    pages = [(f"p{i}.jpg", "x") for i in range(31)]
    with pytest.raises(RegistryError, match="chunking is future work"):
        _ = guess_pages(pages, "", [], [], lambda _s, _u: "{}")


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
        batch, registry_dir=registry, work_dir=tmp_path / "work", readline=fake_line, write_line=lines_written.append
    )
    return registry / f"{batch}.json", lines_written


def test_review_accept_writes_the_confirmed_document(tmp_path: Path) -> None:
    record_path, _ = _review_batch(tmp_path, ["\n"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["status"] == "confirmed"
    assert record["boundaries"][0]["status"] == "confirmed"
    confirmed = tmp_path / "work" / "adopt-0001" / "ocr-confirmed" / "doc-01.txt"
    assert confirmed.read_text(encoding="utf-8") == "Dear Mum,\nLove, Zelda"


def test_review_reject_records_the_rejection(tmp_path: Path) -> None:
    record_path, _ = _review_batch(tmp_path, ["r\n"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["boundaries"][0]["status"] == "rejected"
    assert not (tmp_path / "work" / "adopt-0001" / "ocr-confirmed" / "doc-01.txt").exists()


def test_review_photo_only_batch_confirms_nothing(tmp_path: Path) -> None:
    """2026-08-14 final review: make confirm on a photo-only batch must not error."""
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
    review(batch, registry_dir=registry, work_dir=tmp_path / "work", readline=lambda _p: "r\n", write_line=lines.append)
    assert any("no text pages" in line for line in lines)
