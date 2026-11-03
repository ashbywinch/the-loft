"""Per-page transcript approval: one page at a time, the item assembled.

The reviewer approves a page's text without waiting for the other pages. The
archive item exists from the first approval as a `draft` holding only the
approved pages, and becomes `catalogued` when every text page of the document
has been approved — one item throughout, never a second.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.api.approval import ApprovalContext, DocumentFacts, agreement_for, approve_page
from tools.archive import Archive
from tools.store import DiskStore


def _batch(tmp_path: Path) -> tuple[Path, Path]:
    """A two-page document, read and grouped, awaiting the review."""
    work, registry = tmp_path / "work", tmp_path / "registry"
    registry.mkdir()
    batch = work / "adopt-0001"
    guess = batch / "ocr-guess"
    guess.mkdir(parents=True)
    classify = {
        "p1.jpg": {"kind": "printed", "confidences": {"printed": 0.9}},
        "p2.jpg": {"kind": "printed", "confidences": {"printed": 0.9}},
    }
    (batch / "classify.json").write_text(json.dumps(classify))
    for page, text in (("p1.jpg", "PAGE ONE"), ("p2.jpg", "PAGE TWO")):
        (guess / f"{page[:-4]}.txt").write_text(text + "\n")
        (guess / f"{page[:-4]}.printed.json").write_text("{}")
    (guess / "boundaries.json").write_text(json.dumps([{"pages": ["p1.jpg", "p2.jpg"]}]))
    (registry / "adopt-0001.json").write_text(
        json.dumps(
            {
                "batch_id": "adopt-0001",
                "path": str(tmp_path / "pile"),
                "status": "review",
                "arrived_at": "2026-01-01T00:00:00+00:00",
                "pages": {"p1.jpg": "h1", "p2.jpg": "h2"},
                "fingerprint": ["h1", "h2"],
                "boundaries": [{"pages": ["p1.jpg", "p2.jpg"]}],
            }
        )
    )
    return work, registry


def _item_text(archive: Archive, item_id: str) -> str:
    item = archive.get_item(item_id)
    assert item is not None
    asset = next(a for a in item.assets if a.kind == "transcription")
    return archive.read_content(item.id, asset.file) or ""


def test_one_page_is_approved_without_waiting_for_the_other(tmp_path: Path) -> None:
    work, registry = _batch(tmp_path)
    archive = Archive(DiskStore(tmp_path / "archive"))
    result = approve_page(
        "adopt-0001",
        "p1.jpg",
        "PAGE ONE",
        context=ApprovalContext(archive, work, registry),
        facts=DocumentFacts(title="A letter", date="1915-05-02", date_precision="exact"),
    )
    assert result.document_complete is False
    assert (result.pages_approved, result.pages_total) == (1, 2)
    item = archive.get_item(result.item_id)
    assert item is not None and item.status == "draft"
    assert _item_text(archive, result.item_id) == "PAGE ONE"

    # the second page's approval completes the document: the SAME item, now
    # catalogued, holding both pages in reading order
    done = approve_page(
        "adopt-0001",
        "p2.jpg",
        "PAGE TWO",
        context=ApprovalContext(archive, work, registry),
        facts=DocumentFacts(title="A letter", date="1915-05-02", date_precision="exact"),
    )
    assert done.item_id == result.item_id
    assert done.document_complete is True
    item = archive.get_item(done.item_id)
    assert item is not None and item.status == "catalogued"
    assert _item_text(archive, done.item_id) == "PAGE ONE\n\nPAGE TWO"


def test_re_approving_a_page_supersedes_the_same_item(tmp_path: Path) -> None:
    work, registry = _batch(tmp_path)
    archive = Archive(DiskStore(tmp_path / "archive"))
    first = approve_page(
        "adopt-0001",
        "p1.jpg",
        "PAGE ONE",
        context=ApprovalContext(archive, work, registry),
        facts=DocumentFacts(title="A letter", date="1915-05-02", date_precision="exact"),
    )
    second = approve_page(
        "adopt-0001",
        "p1.jpg",
        "PAGE ONE, CORRECTED",
        context=ApprovalContext(archive, work, registry),
        facts=DocumentFacts(title="A letter", date="1915-05-02", date_precision="exact"),
    )
    assert second.item_id == first.item_id
    assert _item_text(archive, second.item_id) == "PAGE ONE, CORRECTED"
    agreement = agreement_for("p1.jpg", "adopt-0001", work)
    assert agreement is not None and agreement.text == "PAGE ONE, CORRECTED"
