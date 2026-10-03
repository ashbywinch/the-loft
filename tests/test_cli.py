"""Tests for the loft CLI surface (tools/cli.py): the argument wiring the
subcommands promise. No commands run — the parser is what broke (a
GEDCOM refactor dropped capture-memory's --status/--archive and the
handler still reads them; review-bot finding on PR #61)."""

from __future__ import annotations

from tools.cli import build_parser


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
