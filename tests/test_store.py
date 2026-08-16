"""Tests for the append-only store: the immutable-archive requirement
(docs/prd/PRD.md, docs/TECH-SPEC.md §3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.store import DiskStore, ImmutableStoreError, MemoryStore, StoreError


def test_memory_store_writes_new_files() -> None:
    store = MemoryStore()
    store.write_new("assets/story-x/item.json", '{"id": "story-x"}')
    assert store.exists("assets/story-x/item.json")
    assert store.read("assets/story-x/item.json") == '{"id": "story-x"}'


def test_memory_store_rejects_any_write_to_an_existing_file() -> None:
    """The fake filesystem's whole point: an in-place edit fails the test."""
    store = MemoryStore()
    store.write_new("assets/story-x/item.json", "v1")
    with pytest.raises(ImmutableStoreError):
        store.write_new("assets/story-x/item.json", "v2 — an edit")


def test_memory_store_supersession_uses_a_new_path() -> None:
    """Supersede = a new file, never an edit of the old one."""
    store = MemoryStore()
    store.write_new("assets/story-x/item.json", "v1")
    store.write_new("assets/story-x/item-2.json", "v2")
    assert store.read("assets/story-x/item.json") == "v1"  # the original survives


def test_memory_store_lists_files_under_a_directory() -> None:
    store = MemoryStore()
    store.write_new("assets/story-x/item.json", "{}")
    store.write_new("assets/story-x/page-1.svg", "<svg/>")
    store.write_new("people.json", "{}")
    assert store.list("assets/story-x") == ["assets/story-x/item.json", "assets/story-x/page-1.svg"]
    assert store.list("assets") == ["assets/story-x/item.json", "assets/story-x/page-1.svg"]


def test_disk_store_round_trip(tmp_path: Path) -> None:
    store = DiskStore(tmp_path)
    store.write_new("assets/story-x/item.json", '{"id": "story-x"}')
    assert store.exists("assets/story-x/item.json")
    assert store.read("assets/story-x/item.json") == '{"id": "story-x"}'
    assert store.list("assets/story-x") == ["assets/story-x/item.json"]


def test_disk_store_refuses_to_edit(tmp_path: Path) -> None:
    store = DiskStore(tmp_path)
    store.write_new("a.json", "v1")
    with pytest.raises(ImmutableStoreError):
        store.write_new("a.json", "v2")


def test_disk_store_write_leaves_no_temp_siblings(tmp_path: Path) -> None:
    store = DiskStore(tmp_path)
    store.write_new("a.json", "v1")
    store.write_new("b.json", "v2")
    leftovers = [p.name for p in tmp_path.iterdir() if ".tmp" in p.name or p.name.startswith(".")]
    assert leftovers == []  # write-then-rename: readers never see temp files


def test_atomic_write_publishes_the_umask_derived_mode(tmp_path: Path) -> None:
    # the published file must be readable by other users (a second account,
    # a sync process) — owner-only (0600, mkstemp's default) broke that
    # (review, 2026-08-14), and the os.umask() dance that fixed it raced
    # with concurrent writers (review, 2026-08-15: a zeroed process umask
    # publishes 0o666 in an intimate archive). The kernel-umask mode at
    # creation is both.
    from tools.atomic import atomic_write

    target = tmp_path / "a.json"
    atomic_write(target, "v1")
    mode = target.stat().st_mode & 0o777
    assert mode == 0o666 & ~_current_umask()
    assert mode != 0o600  # never owner-only
    assert mode != 0o666  # and never world-writable


def _current_umask() -> int:
    import os

    umask = os.umask(0)
    os.umask(umask)
    return umask


def test_disk_store_rejects_paths_escaping_the_root(tmp_path: Path) -> None:
    store = DiskStore(tmp_path)
    with pytest.raises(StoreError):
        store.write_new("../escape.json", "{}")
    with pytest.raises(StoreError):
        _ = store.read("../../etc/passwd")
