"""The VLM read cache (2026-08-26): the user's question — future passes
must not re-pay tokens for pages whose panels and prompts did not
change. The cache keys on the PANEL IMAGE's bytes + the full call spec;
a hit returns the stored transcription for zero tokens, so gate and
assembly iterations are free. Only a changed panel or prompt re-reads."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from tools.vlm_cache import load_cached_read, store_read


def _png(tmp_path: Path, color: tuple[int, int, int]) -> Path:
    p = tmp_path / "panel.png"
    Image.new("RGB", (64, 64), color).save(p)
    return p


def test_same_panel_and_spec_hits(tmp_path) -> None:
    panel = _png(tmp_path, (10, 20, 30))
    store_read(panel, {"model": "m", "max_tokens": 8000}, "the text", 1234, cache_dir=tmp_path)
    hit = load_cached_read(panel, {"model": "m", "max_tokens": 8000}, cache_dir=tmp_path)
    assert hit == ("the text", 1234)


def test_changed_panel_misses(tmp_path) -> None:
    panel = _png(tmp_path, (10, 20, 30))
    store_read(panel, {"model": "m"}, "old", 1, cache_dir=tmp_path)
    changed = _png(tmp_path, (200, 200, 200))
    assert load_cached_read(changed, {"model": "m"}, cache_dir=tmp_path) is None


def test_changed_spec_misses(tmp_path) -> None:
    panel = _png(tmp_path, (10, 20, 30))
    store_read(panel, {"model": "a"}, "text", 5, cache_dir=tmp_path)
    assert load_cached_read(panel, {"model": "b"}, cache_dir=tmp_path) is None


def test_cache_disabled_env_bypasses(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOFT_VLM_CACHE", "0")
    panel = _png(tmp_path, (1, 2, 3))
    store_read(panel, {"model": "m"}, "text", 5)
    monkeypatch.delenv("LOFT_VLM_CACHE")
    assert load_cached_read(panel, {"model": "m"}, fresh=True) is None
