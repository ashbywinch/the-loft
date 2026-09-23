"""The layout stage's subprocess launcher (TECHSPEC §16.16, VR14).

The layout stage (tools.layout_detect) is §16.17's single pass — one VLM
call per page, on the main venv interpreter; no detector engine, no
.venv-htr. Both the ingest pipeline (tools.pipeline) and the server's
reprocess (tools.sync) spawn it; this module is the one launcher,
importable by either.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# The layout stage's interpreter: §16.17's single-pass stage needs only
# the main venv (urllib + PIL) — no detector engine, no .venv-htr
# (2026-09-06: the paddle stack left the layout path with the
# detect-then-match pipeline it served).
LAYOUT_INTERP = str(Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python")


def run_layout(batch_id: str, work_dir: Path, page_names: list[str] | None = None) -> None:
    """Run the layout stage for a batch (or one page) on the main venv
    interpreter. Every text page gets its layout: line boxes + per-word
    confidence; the multi-orientation pages get the combined
    per-line-orientation layout (PRD VR15). The paddle engine's thread
    cap and FLAGS env left with the engine (2026-09-23) — the single
    pass makes no compute-engine call."""
    env = {**os.environ}
    args = [LAYOUT_INTERP, "-m", "tools.layout_detect", batch_id, "--work-dir", str(work_dir)]
    if page_names:
        args.extend(page_names)
    subprocess.run(args, check=True, cwd=Path(__file__).resolve().parent.parent, env=env)
