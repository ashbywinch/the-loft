"""B4a's real-archive acceptance: the exported correction equals the real one.

Runs only under `make verify` (`-m archive`); CI has no archive. A real page's
reading, words and drawn lines are imported into a scratch database, corrected
through the service, and exported to a scratch work tree: both files must be
byte-identical to the real ones the old writer left. `page-01` has two drawn
lines (43 rows from 41 reading lines); `page-02` is a "rows are right" check
with no lines. The real work tree is read, never written.
"""

# lucidlint: ignore-file fakefs the check reads the real work tree and writes a real
# SQLite database and a scratch tree — C-level I/O, the testing standard's
# real-FS exception.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loft.live.compat_pages import PageCompatibility
from loft.live.page_row import PageState
from loft.live.page_writes import PageWrites
from loft.live.store import LiveStore
from tools.loft_paths import LoftPaths

BATCH = "adopt-20260813-201004"
PAGES = ("page-01", "page-02")
GUESS = LoftPaths.WORK_DIR / BATCH / "ocr-guess"


def _files(guess: Path, page: str) -> tuple[dict, dict, bytes]:
    reading = json.loads((guess / f"{page}.rows.json").read_text(encoding="utf-8"))
    words = json.loads((guess / f"{page}.words.json").read_text(encoding="utf-8"))
    drawn = (guess / f"{page}.row-adjustments.json").read_bytes()
    return reading, words, drawn


@pytest.mark.archive
@pytest.mark.skipif(not (GUESS / "page-01.rows.json").exists(), reason="work tree not mounted")
def test_the_real_correction_exports_the_real_files(tmp_path: Path) -> None:
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    scratch = tmp_path / "work"
    try:
        for page in PAGES:
            reading, words, drawn = _files(GUESS, page)
            stored = {**reading, "words": list(words.get("words") or [])}
            page_id = f"{BATCH}/{page}.jpg"
            with store.change(actor="import") as change:
                change.pages.save(
                    PageState(
                        page_id=page_id,
                        image_asset_id=page_id,
                        sha256=f"sha-{page}",
                        revision=1,
                        rotation=0,
                        category="writing",
                        status="rows_pending",
                    ),
                    reading=stored,
                )
            PageWrites(store).correct_rows(page_id, drawn, stored, actor="p-editor")
            assert PageCompatibility(store, scratch).write(page_id)
            exported = scratch / BATCH / "ocr-guess"
            assert (exported / f"{page}.row-adjustments.json").read_bytes() == drawn
            assert (exported / f"{page}.rows-adjusted.json").read_bytes() == (
                GUESS / f"{page}.rows-adjusted.json"
            ).read_bytes(), f"{page}: the derived rows differ from the real correction"
    finally:
        store.close()
