"""The layout stage's subprocess launcher (TECH-SPEC §16.16, VR14).

The detection pass (tools.layout_detect) runs PaddleOCR under the
.venv-htr interpreter — the main venv never imports it. Both the ingest
pipeline (tools.pipeline) and the server's reprocess (tools.sync) spawn
it; this module is the one launcher, importable by either without
dragging torch or paddle into the process.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# The layout stage's interpreter (2026-08-15): PaddleOCR lives in the
# .venv-htr venv — the htr.py KRAKEN precedent.
LAYOUT_INTERP = str(Path(__file__).resolve().parent.parent / ".venv-htr" / "bin" / "python")


def run_layout(batch_id: str, work_dir: Path, page_names: list[str] | None = None) -> None:
    """Run the layout stage for a batch (or one page) under the .venv-htr
    interpreter. Every text page gets its layout: line boxes + per-word
    confidence; the multi-orientation pages get the combined
    per-line-orientation layout (PRD VR15). The thread env caps the
    engine at nproc-1 cores — the ML stages leave a core for the rest of
    the box (2026-08-17, the laptop requirement)."""
    threads = max(1, (os.cpu_count() or 2) - 1)
    env = {**os.environ, "OMP_NUM_THREADS": str(threads), "FLAGS_paddle_num_threads": str(threads)}
    args = [LAYOUT_INTERP, "-m", "tools.layout_detect", batch_id, "--work-dir", str(work_dir)]
    if page_names:
        args.extend(page_names)
    subprocess.run(args, check=True, cwd=Path(__file__).resolve().parent.parent, env=env)
