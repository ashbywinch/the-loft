"""The HTR stage — cursive pages, read by the field's tooling (TECHSPEC
§16.14; MULTI-DOC-IMPORT-PRD.md R10–R12).

Newer field precedent: the vision-language model reads the page
(``tools/vlm.py``, the opencode-go vision role) — verbatim text, token
usage in a sidecar, and the line geometry the layout pass needs. The
local detector/recognition stack (kraken/orli/TrOCR/transformers in a
.venv-htr) was removed 2026-09-23: its recognition was measured garbage
on the family's pages (TECHSPEC §16.14, the 2026-08-14 comparison) and
nothing outside it used the stack.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from tools.atomic import atomic_write
from tools.loft_paths import WORK_DIR
from tools.pipeline_store import PipelineStore, file_sha256
from tools.store import DiskStore  # noqa: F401 — the architecture test's store-layer marker (htr writes via the store)
from tools.vlm import parse_transcription_response, transcribe_image_vlm, transcription_system_with_context


def _marker_input_matches(marker: Path, input_sha: str) -> bool:
    """Does the completion marker record the CURRENT input fingerprint?
    The marker is stale when the page's image changed after it was
    written (a re-orientation rewrote the jpg) — the text was read from
    the old image, so the skip must not reuse it (2026-08-20: page-02's
    marker predated its orientation fix, so the chain "reused" the
    corrupt guess)."""
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("input_sha") == input_sha


# the extra params (transcribe seam, people/places/label context) belong to this backend alone — a
# stage-inputs type would be ceremony for one use (2026-09-23: the htr_pages comparison died with the local backend)
# lucidlint: ignore long-param-list the VLM backend's stage inputs are the seam and the reading context
def htr_pages_vlm(
    pages: list[tuple[str, Path]],
    raw_dir: Path,
    transcribe: Any = None,
    *,
    people: list[str] | None = None,
    places: list[str] | None = None,
    label: str | None = None,
    store_root: Path = WORK_DIR,
) -> None:
    """The vision-model backend (the 2026-08-14 decision; the only
    backend since 2026-09-23 — the local TrOCR stack was removed as
    unused): each page in, verbatim text out, token usage recorded in a
    sidecar so re-runs skip transcribed pages and the cost is auditable.
    ``transcribe`` is the injectable seam (transcribe_image_vlm shape).
    The system prompt carries the context that helps the model READ —
    the family's known names and places (a familiar name is read
    correctly, not guessed letter-by-letter), the pile's label, and the
    previous page's text for continuity (user, 2026-08-15: "whatever
    useful context we have to help it guess better")."""
    call = transcribe if transcribe is not None else transcribe_image_vlm
    previous: str | None = None
    for name, image in pages:
        out = raw_dir / Path(name).with_suffix(".txt")
        marker = out.with_suffix(".vlm.json")
        batch_id = out.parent.parent.name
        # Skip only when BOTH the completion marker and the artifact it
        # promises exist and are non-empty, AND the marker records the
        # CURRENT input image's fingerprint. A marker whose input changed
        # (a re-orientation rewrote the jpg) is stale — the text was read
        # from the old image (2026-08-20: page-02's marker predated its
        # orientation fix, so the chain "reused" the corrupt guess).
        # Existence alone is a lie of a completion proxy; validate the
        # input dependency before skipping.
        input_sha = file_sha256(image)
        if (
            marker.exists()
            and out.exists()
            and out.read_text(encoding="utf-8").strip()
            and _marker_input_matches(marker, input_sha)
        ):
            print(f"vlm: {name} already done — reusing")
            previous = out.read_text(encoding="utf-8")  # keep the continuity current
            continue
        if marker.exists():
            print(f"vlm: {name} input changed or text missing — re-transcribing")
        else:
            print(f"vlm: {name} transcribing…", flush=True)
        system = transcription_system_with_context(people=people, places=places, label=label, previous_page=previous)
        text, usage = call(image, system=system)
        plain, boxes = parse_transcription_response(text)
        atomic_write(out, plain)  # backward compat — callers read from the old path
        PipelineStore(store_root).write(str(Path(batch_id) / "ocr-guess" / out.name), plain)
        marker_data: dict[str, Any] = dict(usage)
        marker_data["input_sha"] = input_sha
        if boxes is not None:
            # the VLM's own line geometry (normalized 0-1000) — the layout
            # pass uses it instead of the rec association, which cannot read
            # cursive (2026-08-16: the rec merges lines into tall boxes and
            # misses the top line entirely — the VLM that READ the page can
            # anchor each line it transcribed). Only the entries with boxes
            # ride along; a page without geometry keeps the old fallback.
            marker_data["lines"] = [{"text": plain.split("\n")[i], "box": boxes[i]} for i in sorted(boxes)]
        PipelineStore(store_root).write(
            str(Path(batch_id) / "ocr-guess" / marker.name), json.dumps(marker_data, ensure_ascii=False)
        )
        atomic_write(marker, json.dumps(marker_data, ensure_ascii=False))  # backward compat — marker.exists()
        previous = plain
        print(f"vlm: {name} -> {out.name} ({usage.get('total_tokens', 0)} tokens)")


if __name__ == "__main__":
    sys.exit(0)
