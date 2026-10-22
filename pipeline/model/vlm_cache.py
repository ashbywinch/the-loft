"""The VLM read cache: the batch's reads are a pure function of (panel
image bytes, call spec). Persisting them keyed by that pair means gate
tweaks, assembly changes, and plain re-runs cost ZERO tokens for
unchanged pages — the expensive call happens once per distinct panel.
LOFT_VLM_CACHE=0 or fresh=True bypasses (a deliberate re-sample); the
default location is work/.vlm-cache/."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.model.cache_file import CacheFile
from pipeline.model.cached_read import CachedRead
from pipeline.model.unsure_word import UnsureWord
from tools.loft_paths import WORK_DIR

CACHE_DIR = WORK_DIR / ".vlm-cache"


@dataclass(frozen=True)
class PanelRead:
    """A panel's read identity: the image file and the call spec — a
    read is a pure function of the pair, so it is the cache key's
    input."""

    panel: Path
    spec: dict[str, Any]

    def file_key(self, cache_dir: Path = CACHE_DIR) -> CacheFile:
        panel_hash = hashlib.sha256(self.panel.read_bytes()).hexdigest()[:32]
        spec_blob = json.dumps(self.spec, sort_keys=True, default=str)
        spec_hash = hashlib.sha256(spec_blob.encode()).hexdigest()[:16]
        return CacheFile(f"{panel_hash}-{spec_hash}.json", cache_dir)


@dataclass(frozen=True)
class PanelTranscript:
    """A panel's transcription: the image file and the read text — the
    self-report key's pair (the flags are a pure function of the read)."""

    panel: Path
    text: str

    def file_key(self) -> CacheFile:
        panel_hash = hashlib.sha256(self.panel.read_bytes()).hexdigest()[:32]
        text_hash = hashlib.sha256(self.text.encode()).hexdigest()[:16]
        return CacheFile(f"{panel_hash}-sr-{text_hash}.json", CACHE_DIR)


def store_read(read: PanelRead, text: str, tokens: int, *, cache_dir: Path = CACHE_DIR) -> None:
    """Persist one read: {panel bytes + spec} -> (text, total_tokens).
    Failures to cache are silent-by-design — the cache is an
    optimization, never a correctness dependency. ``cache_dir`` is
    injectable so the hermetic tests never touch the real work disk
    (2026-08-29, the CI's build-and-test failure)."""
    try:
        entry = read.file_key(cache_dir)
        entry.write(json.dumps(CachedRead(text, tokens).to_dict()))
    # lucidlint: ignore swallow the cache is an optimization — a full disk must never break a run
    except OSError:
        pass


def load_cached_read(read: PanelRead, *, fresh: bool = False, cache_dir: Path = CACHE_DIR) -> CachedRead | None:
    """The cached read for this exact panel+spec, or None on a
    miss (or when caching is off via LOFT_VLM_CACHE=0 / fresh=True).
    ``cache_dir`` is injectable (the hermetic tests, 2026-08-29)."""
    if fresh or os.environ.get("LOFT_VLM_CACHE") == "0":
        return None
    try:
        path = read.file_key(cache_dir).path()
        if not path.is_file():
            return None
        return CachedRead.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return None


def store_selfreport(transcript: PanelTranscript, report: list[UnsureWord]) -> None:
    """Cache one self-report keyed on (panel bytes, transcription text)
    — the flags are a pure function of the read, so re-assembly of an
    unchanged page never re-pays the doubt call."""

    # disk must never break a run that would otherwise succeed
    try:
        entry = transcript.file_key()
        entry.write(json.dumps([word.to_dict() for word in report]))
    # lucidlint: ignore swallow the cache is an optimization — a full disk must never break a run
    except OSError:
        pass


def load_selfreport(transcript: PanelTranscript) -> list[UnsureWord] | None:
    """The cached self-report for this exact (panel, text), or None (a
    file that is not the report's own list of flags reads as a miss)."""
    try:
        path = transcript.file_key().path()
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return None
        return [UnsureWord.from_dict(entry) for entry in raw]
    except (OSError, ValueError, KeyError, TypeError):
        return None
