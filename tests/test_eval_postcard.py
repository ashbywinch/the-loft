"""The end-to-end grouping eval on the Caradog Roberts 1915 postcard
(public domain, Wikimedia Commons — NOT family data).

The postcard's *reading* is the reviewer's own row detection (the postcard
decision, 2026-11-15): its writing runs in two directions and the automatic
layout path cannot carry it. This eval checks the grouping contract only —
one document, the picture side first.

Runs the REAL pipeline on the two sides of a postcard whose back carries
text at 0° AND 90° (a handwritten Welsh message running up the left edge)
and asserts the one contract that is the pipeline's here: the grouping
pairs the two sides into one document, the picture side first
(acceptance 21).

Real model calls — run with ``make evals`` / ``pytest -m eval``, never in
``make test``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.registry import load_batch
from tools.loft_paths import LoftPaths  # the eval's media gate — the pipeline reads the archive's batch, LoftPaths

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BACK = FIXTURES / "godolphin-1906-back.jpg"
FRONT = FIXTURES / "godolphin-1906-front.jpg"
BATCH = "godolphin-1906-eval"

# the eval runs the REAL pipeline: real filesystem (the scratch batch +
# the layout stage's subprocess), real model calls — the fakefs contract
# is for the unit tests, never for an end-to-end eval
# lucidlint: ignore-file fakefs the eval drives the real pipeline + the layout stage's subprocess


def _seed_batch(tmp_path: Path) -> tuple[Path, Path]:
    """The scratch batch: the two fixture images registered as
    back.jpg + front.jpg (the back sorts first, like a real scan)."""
    folder = tmp_path / "folder"
    folder.mkdir()
    for src, name in ((FRONT, "front.jpg"), (BACK, "back.jpg")):
        (folder / name).write_bytes(src.read_bytes())
    registry = tmp_path / "registry"
    registry.mkdir()
    work = tmp_path / "work"
    (registry / f"{BATCH}.json").write_text(
        json.dumps(
            {
                "batch_id": BATCH,
                "path": str(folder),
                "label": "Caradog Roberts 1915 postcard (public domain)",
                "source": "external",
                "status": "importing",
                "pages": {name: "0" * 64 for name in ("back.jpg", "front.jpg")},
            }
        ),
        encoding="utf-8",
    )
    return registry, work


def _assert_contracts(registry: Path) -> None:
    """The grouping contract: the two sides are one document, the picture
    side first (acceptance 21)."""
    record = load_batch(BATCH, registry_dir=registry)
    # acceptance 21: the two sides are ONE document, the picture side first
    docs = [b for b in record.boundaries or [] if b.pages]
    assert len(docs) == 1, f"expected one document, got {len(docs)}"
    assert docs[0].pages == ["front.jpg", "back.jpg"], docs[0].pages

    # The back's READING is the reviewer's own row detection now (the
    # postcard decision, 2026-11-15): the auto layout path cannot carry a
    # page whose writing runs in two directions, so the reviewer draws the
    # rows on the row screen and the read follows their lines. That path is
    # not asserted here yet — this eval checks the grouping contract only.


@pytest.mark.eval
@pytest.mark.skipif(
    not (BACK.exists() and FRONT.exists()) or not LoftPaths.ARCHIVE_DIR.exists(),
    reason="the public-domain fixture images or the archive are missing (media-gated, off-CI)",
)
def test_postcard_groups_two_sides_as_one_document(tmp_path: Path) -> None:
    """The full pipeline on the sample postcard: the two sides are ONE
    document, the picture side first (acceptance 21). The back's reading is
    the reviewer's row detection (the postcard decision) — not asserted yet."""
    registry, work = _seed_batch(tmp_path)
    # the pipeline imports torch (classify) — kept inside the eval so make
    # test's collection never loads the heavy stack
    # lucidlint: ignore inline-import the eval runs the real pipeline — torch loads only here
    from pipeline.chain import process

    process(BATCH, registry_dir=registry, work_dir=work)
    _assert_contracts(registry)
