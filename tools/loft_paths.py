"""Where the loft's content lives — the one seam for paths across the pipeline.

Two zones (MULTI-DOC-IMPORT-PRD.md R1–R3, TECH-SPEC §16.13):
- USER_SCAN_AREA — the user's scan folders (their org, their rules; we only
  read, and only add our own scan output folders).
- WORKSPACE — our sibling folder on the big disk, named Loft, holding the
  registry (per-batch records: labels, hashes, status), the derived work
  stages (oriented, OCR chain), the archive (confirmed knowledge) and the
  deployable projection. The user's scan folders are never written to; we
  re-attach to them by content hash.

A relocation is one edit here, never a grep across modules.
"""

from __future__ import annotations

import os
from pathlib import Path

# The big disk — the one machine-dependent input. Defaults to the current
# family's mount; override with LOFT_DISK_ROOT on a machine where the
# workspace lives elsewhere, so the data checks run there too instead of
# silently skipping as "archive not found" (review, 2026-08-14).
_DISK = Path(os.environ.get("LOFT_DISK_ROOT", "/run/media/ashby/One Touch"))

USER_SCAN_AREA = _DISK / "scans"
WORKSPACE = _DISK / "Loft"
REGISTRY_DIR = WORKSPACE / "registry"
WORK_DIR = WORKSPACE / "work"
ARCHIVE_DIR = WORKSPACE / "archive"
PROJECTION_DIR = WORKSPACE / "projection"
