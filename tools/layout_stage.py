"""The layout stage's subprocess launcher (TECH-SPEC §16.16, VR14).

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
    """Run the layout stage for a batch (or one page) under the .venv-htr
    interpreter. Every text page gets its layout: line boxes + per-word
    confidence; the multi-orientation pages get the combined
    per-line-orientation layout (PRD VR15). The thread env caps the
    engine at nproc-1 cores — the ML stages leave a core for the rest of
    the box (2026-08-17, the laptop requirement)."""
    threads = max(1, (os.cpu_count() or 2) - 1)
    env = {
        **os.environ,
        "OMP_NUM_THREADS": str(threads),
        "FLAGS_paddle_num_threads": str(threads),
        # The engine's peak on the 8GB laptop (2026-08-17): the det input
        # is bounded (text_det_limit_side_len in the ENGINE config) and
        # the framework allocates ON DEMAND — the default arena
        # pre-allocates a huge block up front, which is what pushed the
        # stage over the available memory even before the first prediction.
        "FLAGS_allocator_strategy": "auto_growth",
        "FLAGS_use_system_allocator": "1",
    }
    args = [LAYOUT_INTERP, "-m", "tools.layout_detect", batch_id, "--work-dir", str(work_dir)]
    if page_names:
        args.extend(page_names)
    subprocess.run(args, check=True, cwd=Path(__file__).resolve().parent.parent, env=env)
