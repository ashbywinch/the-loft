"""Apply the self-report to an existing layout without re-running the
detection stage (user: "why do we need to rerun the layout
pass?"). Reads the existing layout.json, recomputes the per-word conf
values from the self-report and the struck markers, and rewrites the
file. Pure Python (main venv, no PaddleOCR), ~1s per page.

Usage: python -m pipeline.layout_apply_selfreport <batch_id> [page ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pipeline.layout import Layout, is_struck, normalize
from pipeline.model.unsure_word import UnsureWord
from pipeline.store import PipelineStore
from tools.loft_paths import WORK_DIR
from tools.selfreport_driver import run_cli
from tools.store import DiskStore  # noqa: F401 — the architecture test's store-layer marker

REPORT_NAME = "selfreport.json"


def _word_flag(word: str, *, selfreport_line: set[str] | None) -> float:
    """The per-word flag source (user): the self-report
    (the transcription model's own doubt) + the ~~struck~~ markers.
    Struck words always flag; self-reported words flag; everything else
    is confident."""
    if is_struck(word):
        return 0.0
    if selfreport_line and normalize(word) in selfreport_line:
        return 0.0
    return 1.0


def apply_selfreport(layout: Layout, selfreport: list[UnsureWord] | None) -> Layout:
    """Rewrite the per-word conf values in a layout using the
    self-report. Returns the updated layout (modifies in place, returns
    for convenience)."""
    report_by_line: dict[int, set[str]] = {}
    if selfreport:
        for entry in selfreport:
            if 1 <= entry.line <= len(layout.lines):
                report_by_line.setdefault(entry.line - 1, set()).add(normalize(entry.word))

    for line in layout.lines:
        flags = report_by_line.get(line.index)
        for word in line.words or []:
            word.conf = _word_flag(word.word, selfreport_line=flags)
        if line.words:
            confs = [word.conf for word in line.words]
            line.conf = sum(confs) / len(confs)
    return layout


def run_batch(batch_id: str, page_names: list[str] | None, work_dir: Path) -> int:
    """Apply the self-report to every layout that has one."""
    guess_dir = work_dir / batch_id / "ocr-guess"
    if not guess_dir.is_dir():
        print(f"layout-apply: no guess dir for batch {batch_id!r}", file=sys.stderr)
        return 1
    reports = sorted(guess_dir.glob(f"*.{REPORT_NAME}"))
    if page_names:
        wanted = set(page_names)
        reports = [p for p in reports if p.stem.split(".")[0] in wanted]
    for report in reports:
        _apply_report(report)
    return 0


def _apply_report(report: Path) -> None:
    """Apply one page's self-report to its stored layout. The page name is
    the part before ``.selfreport``: page-01.selfreport.json -> page-01. A
    report whose layout is absent is skipped — nothing to rewrite."""
    page_stem = report.stem.split(".")[0]
    layout_path = report.parent / f"{page_stem}.layout.json"
    if not layout_path.exists():
        return
    layout = Layout.from_dict(json.loads(layout_path.read_text(encoding="utf-8")))
    entries = json.loads(report.read_text(encoding="utf-8"))
    # an entry with no usable line/word is dropped, never fatal: the
    # file is the model path's, but an old or hand-edited one must not
    # crash the batch
    selfreport = [
        UnsureWord.from_dict(entry)
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("line"), int) and isinstance(entry.get("word"), str)
    ]
    apply_selfreport(layout, selfreport)
    layout.write_store(PipelineStore(WORK_DIR), str(layout_path.relative_to(WORK_DIR)))
    flagged = sum(1 for line in layout.lines for word in line.words or [] if word.conf == 0.0)
    print(f"layout: applied self-report to {layout_path.name} -> {flagged} flagged words")


def main(argv: list[str] | None = None) -> int:
    return run_cli(
        argv,
        prog="layout_apply_selfreport",
        description="Apply the self-report to existing layouts (no re-detection, ~1s per page).",
        pages_help="optional page stems (e.g. page-03) to limit",
        runner=run_batch,
    )


if __name__ == "__main__":
    sys.exit(main())
