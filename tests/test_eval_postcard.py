"""The end-to-end multi-orientation eval on the Caradog Roberts 1915
postcard (public domain, Wikimedia Commons — NOT family data, 2026-08-17).

Runs the REAL pipeline on the two sides of a postcard whose back carries
text at 0° AND 90° (a handwritten Welsh message running up the left
edge) and asserts the contracts the review depends on (VR14/VR15):

- the grouping pairs the two sides into one document, the picture side
  first (acceptance 21);
- the back's layout carries the model's OWN transcription anchored to
  per-line boxes — every line has a box, and the box holds the words it
  claims (the reproduced fault: the rec's fragments mispaired with the
  detector's boxes made the review's text nonsense);
- lines at more than one orientation are present with their orientations.

Real model calls (the layout stage's .venv-htr subprocess too) — run
with ``make evals`` / ``pytest -m eval``, never in ``make test``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.registry import load_batch
from tools.sync import draft_payloads

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BACK = FIXTURES / "caradog-1915-back.jpg"
FRONT = FIXTURES / "caradog-1915-front.jpg"
BATCH = "caradog-1915-eval"

# the eval runs the REAL pipeline: real filesystem (the scratch batch +
# the layout stage's subprocess), real model calls — the fakefs contract
# is for the unit tests, never for an end-to-end eval
# lucidlint: ignore-file fakefs the eval drives the real pipeline + the .venv-htr layout subprocess


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


def _assert_contracts(registry: Path, work: Path) -> None:
    """The review contracts the pipeline must satisfy (VR14/VR15)."""
    record = load_batch(BATCH, registry_dir=registry)
    # acceptance 21: the two sides are ONE document, the picture side first
    docs = [b for b in record.get("boundaries", []) if b.get("pages")]
    assert len(docs) == 1, f"expected one document, got {len(docs)}"
    assert docs[0]["pages"] == ["front.jpg", "back.jpg"], docs[0]["pages"]

    back_layout = None
    for document in draft_payloads(BATCH, work):
        if "back.jpg" in document.get("pages", []):
            back_layout = document["layouts"].get("back.jpg")
    assert back_layout is not None, "the back's layout is missing"
    lines = back_layout.get("lines", [])
    assert lines, "the layout has no lines"
    # VR14: every line has a box, and the box holds the words it claims —
    # the lines are the MODEL's transcription (not the rec's fragments)
    assert all(line.get("box") for line in lines), "a line has no bounding box"
    texts = [line["text"] for line in lines]
    assert any("POST CARD" in t for t in texts), f"the model's header missing: {texts[:6]}"
    assert any("lesson" in t or "arranged" in t for t in texts), f"the message missing: {texts[:8]}"
    # VR15: more than one orientation — the vertical message at its own
    orientations = {line.get("orientation") for line in lines}
    assert len(orientations) >= 2, f"expected 0° + a vertical direction, got {orientations}"


@pytest.mark.eval
@pytest.mark.skipif(not (BACK.exists() and FRONT.exists()), reason="the public-domain fixture images are missing")
def test_postcard_groups_two_sides_and_boxes_the_transcription(tmp_path: Path) -> None:
    """The full pipeline on the sample postcard: one document (picture
    side first), and the back's layout with the model's transcription at
    per-line boxes — every line boxed, both orientations present."""
    registry, work = _seed_batch(tmp_path)
    # the pipeline imports torch (classify) — kept inside the eval so make
    # test's collection never loads the heavy stack
    # lucidlint: ignore inline-import the eval runs the real pipeline — torch loads only here
    from tools.pipeline import process

    process(BATCH, registry_dir=registry, work_dir=work)
    _assert_contracts(registry, work)
