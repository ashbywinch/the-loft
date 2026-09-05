"""Tests for the versioned pipeline store (tools/pipeline_store.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.pipeline_store import PipelineStore
from tools.store import StoreError


def test_writes_are_versioned(tmp_path: Path) -> None:
    store = PipelineStore(tmp_path)
    store.write("test.json", "v1")
    store.write("test.json", "v2")
    assert store.versions("test.json") == [1, 2]
    assert store.read_latest("test.json") == "v2"
    # The old version is preserved at -2.ext
    assert (tmp_path / "test-2.json").read_text() == "v1"


def test_version_1_is_bare_path(tmp_path: Path) -> None:
    store = PipelineStore(tmp_path)
    store.write("test.json", "content")
    assert (tmp_path / "test.json").read_text() == "content"


def test_version_2_has_suffix(tmp_path: Path) -> None:
    store = PipelineStore(tmp_path)
    store.write("test.json", "v1")
    store.write("test.json", "v2")
    # Base path now has the latest version
    assert (tmp_path / "test.json").read_text() == "v2"
    assert (tmp_path / "test-2.json").read_text() == "v1"


def test_read_latest_returns_highest_version(tmp_path: Path) -> None:
    store = PipelineStore(tmp_path)
    store.write("test.json", "v1")
    assert store.read_latest("test.json") == "v1"
    store.write("test.json", "v2")
    assert store.read_latest("test.json") == "v2"
    store.write("test.json", "v3")
    assert store.read_latest("test.json") == "v3"


def test_exists_checks_all_versions(tmp_path: Path) -> None:
    store = PipelineStore(tmp_path)
    assert not store.exists("test.json")
    store.write("test.json", "v1")
    assert store.exists("test.json")


def test_versions_returns_sorted(tmp_path: Path) -> None:
    store = PipelineStore(tmp_path)
    assert store.versions("test.json") == []
    store.write("test.json", "v1")
    assert store.versions("test.json") == [1]
    store.write("test.json", "v2")
    assert store.versions("test.json") == [1, 2]


def test_write_never_overwrites(tmp_path: Path) -> None:
    store = PipelineStore(tmp_path)
    store.write("test.json", "v1")
    store.write("test.json", "v2")  # v2 is a new file, not an overwrite
    assert store.read_latest("test.json") == "v2"
    assert (tmp_path / "test.json").read_text() == "v2"  # base path = latest
    assert (tmp_path / "test-2.json").read_text() == "v1"  # old preserved


def test_txt_files_are_versioned_too(tmp_path: Path) -> None:
    store = PipelineStore(tmp_path)
    store.write("guess.txt", "first")
    assert store.read_latest("guess.txt") == "first"
    store.write("guess.txt", "second")
    assert store.read_latest("guess.txt") == "second"
    assert (tmp_path / "guess.txt").read_text() == "second"  # base path = latest
    assert (tmp_path / "guess-2.txt").read_text() == "first"  # old preserved


def test_read_latest_raises_on_missing(tmp_path: Path) -> None:
    store = PipelineStore(tmp_path)
    with pytest.raises(StoreError):
        store.read_latest("nonexistent.json")


def test_works_with_json_content(tmp_path: Path) -> None:
    store = PipelineStore(tmp_path)
    store.write("data.json", json.dumps({"key": "value"}))
    data = json.loads(store.read_latest("data.json"))
    assert data == {"key": "value"}


def test_paths_with_dots_in_stem(tmp_path: Path) -> None:
    """Paths like 'ocr-guess/page-02.layout.json' should work correctly."""
    store = PipelineStore(tmp_path)
    store.write("ocr-guess/page-02.layout.json", "v1")
    store.write("ocr-guess/page-02.layout.json", "v2")
    assert store.read_latest("ocr-guess/page-02.layout.json") == "v2"
    assert (tmp_path / "ocr-guess" / "page-02.layout.json").read_text() == "v2"  # base = latest
    assert (tmp_path / "ocr-guess" / "page-02.layout-2.json").read_text() == "v1"  # old preserved
