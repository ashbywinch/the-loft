"""Tests for the loft CLI surface (tools/cli.py): the argument wiring the
subcommands promise, and the database bootstrap that runs without a model or
the archive."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.cli import build_parser, main


def test_capture_memory_keeps_its_full_argument_surface() -> None:
    """capture-memory's handler reads status and archive — the subparser
    must still offer them (a parser that accepts fewer args than the
    handler reads crashes with AttributeError at runtime)."""
    args = build_parser().parse_args(["capture-memory", "-", "--status", "catalogued", "--archive", "somewhere"])
    assert args.status == "catalogued"
    assert args.archive == "somewhere"
    assert args.who == "" and args.anchor == ""  # defaults intact


def test_gedcom_subcommands_are_wired() -> None:
    """The island commands parse into the gedcom action and its paths."""
    args = build_parser().parse_args(["gedcom", "import", "in.ged", "folder"])
    assert args.fn.__name__ == "cmd_gedcom" and args.action == "import"
    assert args.file == "in.ged" and args.folder == "folder"
    args = build_parser().parse_args(["gedcom", "export", "folder", "out.ged"])
    assert args.fn.__name__ == "cmd_gedcom" and args.action == "export"
    assert args.folder == "folder" and args.path == "out.ged"


def test_work_is_wired_to_the_scan_pickup() -> None:
    """`loft work` parses into the worker's scan area, and one sweep by default
    (a watcher is opt-in: --watch N)."""
    args = build_parser().parse_args(["work"])
    assert args.fn.__name__ == "cmd_work"
    assert args.watch == 0.0
    args = build_parser().parse_args(["work", "--scan-area", "/tmp/scans", "--watch", "30"])
    assert args.scan_area == "/tmp/scans"
    assert args.watch == 30.0


def test_work_can_requeue_one_batch_by_id() -> None:
    """A legacy `review` batch (or one a dead pass left behind) re-enters the
    queue explicitly; a plain sweep requeues nothing."""
    args = build_parser().parse_args(["work", "--requeue", "adopt-20260813-201004"])
    assert args.requeue == "adopt-20260813-201004"
    assert build_parser().parse_args(["work"]).requeue == ""


def test_db_init_and_verify_are_wired(tmp_path: Path) -> None:
    path = tmp_path / "loft.db"
    init = build_parser().parse_args(["db", "init", "--path", str(path)])
    assert init.fn.__name__ == "cmd_db_init" and init.path == str(path)
    verify = build_parser().parse_args(["verify", "--schema", "--path", str(path)])
    assert verify.fn.__name__ == "cmd_verify" and verify.schema is True


def test_db_init_and_verify_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "loft.db"
    assert main(["db", "init", "--path", str(path)]) == 0
    assert path.is_file()
    assert main(["verify", "--schema", "--path", str(path)]) == 0
    assert "schema ok" in capsys.readouterr().out
