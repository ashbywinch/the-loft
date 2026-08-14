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


def test_disk_store_rejects_paths_escaping_the_root(tmp_path: Path) -> None:
    store = DiskStore(tmp_path)
    with pytest.raises(StoreError):
        store.write_new("../escape.json", "{}")
    with pytest.raises(StoreError):
        _ = store.read("../../etc/passwd")
