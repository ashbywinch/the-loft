"""The VLM read cache (2026-08-26): the batch's reads are a pure
function of (panel image bytes, call spec). Persisting them keyed by
that pair means gate tweaks, assembly changes, and plain re-runs cost
ZERO tokens for unchanged pages — the expensive call happens once per
distinct panel. LOFT_VLM_CACHE=0 or fresh=True bypasses (a deliberate
re-sample); the default location is work/.vlm-cache/."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from tools.loft_paths import WORK_DIR

CACHE_DIR = WORK_DIR / ".vlm-cache"


def _cache_key(panel: Path, spec: dict[str, Any], cache_dir: Path = CACHE_DIR) -> tuple[str, Path]:
    panel_hash = hashlib.sha256(panel.read_bytes()).hexdigest()[:32]
    spec_blob = json.dumps(spec, sort_keys=True, default=str)
    spec_hash = hashlib.sha256(spec_blob.encode()).hexdigest()[:16]
    return f"{panel_hash}-{spec_hash}.json", cache_dir


def store_read(panel: Path, spec: dict[str, Any], text: str, tokens: int, *, cache_dir: Path = CACHE_DIR) -> None:
    """Persist one read: {panel bytes + spec} -> (text, total_tokens).
    Failures to cache are silent-by-design — the cache is an
    optimization, never a correctness dependency. ``cache_dir`` is
    injectable so the hermetic tests never touch the real work disk
    (2026-08-29, the CI's build-and-test failure)."""
    try:
        key, directory = _cache_key(panel, spec, cache_dir)
        directory.mkdir(parents=True, exist_ok=True)
        atomic = directory / f"{key}.tmp"
        atomic.write_text(json.dumps({"text": text, "tokens": tokens}), encoding="utf-8")
        atomic.replace(directory / key)
    # lucidlint: ignore swallow the cache is an optimization — a full disk must never break a run
    except OSError:
        pass


def load_cached_read(
    panel: Path, spec: dict[str, Any], *, fresh: bool = False, cache_dir: Path = CACHE_DIR
) -> tuple[str, int] | None:
    """The cached (text, tokens) for this exact panel+spec, or None on a
    miss (or when caching is off via LOFT_VLM_CACHE=0 / fresh=True).
    ``cache_dir`` is injectable (the hermetic tests, 2026-08-29)."""
    if fresh or os.environ.get("LOFT_VLM_CACHE") == "0":
        return None
    try:
        key, directory = _cache_key(panel, spec, cache_dir)
        path = directory / key
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["text"], int(data["tokens"])
    except (OSError, ValueError, KeyError):
        return None


def _selfreport_key(panel: Path, text: str) -> tuple[str, Path]:
    panel_hash = hashlib.sha256(panel.read_bytes()).hexdigest()[:32]
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"{panel_hash}-sr-{text_hash}.json", CACHE_DIR


def store_selfreport(panel: Path, text: str, report: list[dict]) -> None:
    """Cache one self-report keyed on (panel bytes, transcription text)
    — the flags are a pure function of the read, so re-assembly of an
    unchanged page never re-pays the doubt call."""

    # disk must never break a run that would otherwise succeed
    try:
        key, directory = _selfreport_key(panel, text)
        directory.mkdir(parents=True, exist_ok=True)
        atomic = directory / f"{key}.tmp"
        atomic.write_text(json.dumps(report), encoding="utf-8")
        atomic.replace(directory / key)
    # lucidlint: ignore swallow the cache is an optimization — a full disk must never break a run
    except OSError:
        pass


def load_selfreport(panel: Path, text: str) -> list[dict] | None:
    """The cached self-report for this exact (panel, text), or None."""
    try:
        key, directory = _selfreport_key(panel, text)
        path = directory / key
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
