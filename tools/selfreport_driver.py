"""The shared CLI driver of the batch report tools (selfreport,
layout_apply_selfreport): one parser shape — a batch id, an optional page
filter, --work-dir — and the dispatch to the tool's run_batch. Each tool's
run_batch does the per-batch work; the driver is the argv surface
(2026-08-16 duplicate review: the two mains were the same parser+dispatch
copy-pasted).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from tools.loft_paths import WORK_DIR


def run_cli(
    argv: list[str] | None,
    *,
    prog: str,
    description: str,
    pages_help: str,
    runner: Callable[[str, list[str] | None, Path], int],
) -> int:
    """Build the batch-tool parser and dispatch to *runner* — the shared
    argv surface: a batch id, optional page names to limit the pass, and
    --work-dir."""
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument("batch_id")
    parser.add_argument("pages", nargs="*", help=pages_help)
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR)
    args = parser.parse_args(argv)
    return runner(args.batch_id, args.pages or None, args.work_dir)
