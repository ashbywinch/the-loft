"""Apply the self-report to an existing layout without re-running the
detection stage (2026-08-15, user: "why do we need to rerun the layout
pass?"). Reads the existing layout.json, recomputes the per-word conf
values from the self-report and the struck markers, and rewrites the
file. Pure Python (main venv, no PaddleOCR), ~1s per page.

Usage: python -m tools.layout_apply_selfreport <batch_id> [page ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tools.layout import is_struck, normalize, write_layout
from tools.selfreport_driver import run_cli
from tools.store import DiskStore  # noqa: F401

REPORT_NAME = "selfreport.json"


def _word_flag(word: str, *, selfreport_line: set[str] | None) -> float:
    """The per-word flag source (user, 2026-08-15): the self-report
    (the transcription model's own doubt) + the ~~struck~~ markers.
    Struck words always flag; self-reported words flag; everything else
    is confident."""
    if is_struck(word):
        return 0.0
    if selfreport_line and normalize(word) in selfreport_line:
        return 0.0
    return 1.0


def apply_selfreport(layout: dict, selfreport: list[dict] | None) -> dict:
    """Rewrite the per-word conf values in a layout dict using the
    self-report. Returns the updated layout (modifies in place, returns
    for convenience)."""
    report_by_line: dict[int, set[str]] = {}
    if selfreport:
        for entry in selfreport:
            line_no = entry.get("line")
            if isinstance(line_no, int) and 1 <= line_no <= len(layout.get("lines", [])):
                report_by_line.setdefault(line_no - 1, set()).add(normalize(entry.get("word", "")))

    for line in layout.get("lines", []):
        vi = line.get("index")
        flags = report_by_line.get(vi) if vi is not None else None
        for w in line.get("words", []):
            w["conf"] = _word_flag(w.get("word", ""), selfreport_line=flags)
        if line.get("words"):
            confs = [w["conf"] for w in line["words"]]
            line["conf"] = sum(confs) / len(confs)
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
        # the page name is the part before .selfreport:
        # page-01.selfreport.json -> page-01
        page_stem = report.stem.split(".")[0]
        layout_path = report.parent / f"{page_stem}.layout.json"
        if not layout_path.exists():
            continue
        layout = json.loads(layout_path.read_text(encoding="utf-8"))
        selfreport = json.loads(report.read_text(encoding="utf-8"))
        apply_selfreport(layout, selfreport)
        write_layout(layout, layout_path)
        flagged = sum(1 for line in layout["lines"] for w in line["words"] if w["conf"] == 0.0)
        print(f"layout: applied self-report to {layout_path.name} -> {flagged} flagged words")
    return 0


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
