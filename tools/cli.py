"""The loft CLI — the one operator surface for the archive's tools.

``loft publish | serve | create-demo | capture-document | capture-memory |
gedcom in|out | eval-memory``. Every command constructs an object-model noun
and calls its methods — Archive.publish(), Server.serve(),
Archive.create_demo(), Archive.capture_document(), Archive.capture_memory(),
GedcomDocument.to_text()/from_text() — so the domain vocabulary lives in the
nouns, and the CLI is a thin argument surface. No per-module __main__ shims
(coding-standards.md, 2026-08-06): a command's argv handling lives here, and
the repo-root ``loft`` wrapper forwards it.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from tools.archive import Archive
from tools.store import DiskStore

ROOT = Path(__file__).resolve().parent.parent


def _archive(archive_dir: str) -> Archive:
    return Archive(DiskStore(Path(archive_dir)))


def cmd_publish(args: argparse.Namespace) -> int:
    archive = _archive(args.archive)
    archive.publish(Path(args.data))
    print(f"published {args.archive} -> {args.data}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from tools.ai_client import AIClient, AIClientError
    from tools.server import Server

    try:
        client = AIClient()  # the capture API needs the key; absent -> the API 503s
    except AIClientError as e:
        print(f"serve: no capture client ({e}) — serving the app only")
        client = None
    Server(
        DiskStore(Path(args.archive)),
        Path(args.data),
        client,
        Path(args.app),
        host=args.host,
        port=args.port,
    ).serve()
    return 0


def cmd_create_demo(args: argparse.Namespace) -> int:
    archive = _archive(args.archive)
    archive.create_demo()
    archive.publish(Path(args.data))  # the demo's own projection, never app/data by surprise
    print(f"seeded demo archive {args.archive} -> {args.data}")
    return 0


def cmd_capture_document(args: argparse.Namespace) -> int:
    _archive(args.archive).capture_document(Path(args.scans))
    return 0


def cmd_capture_memory(args: argparse.Namespace) -> int:
    from tools.ai_client import AIClient, AIClientError

    account = sys.stdin.read() if args.account == "-" else Path(args.account).read_text(encoding="utf-8")
    try:
        client = AIClient()
    except AIClientError as e:
        print(f"capture-memory: no API key: {e}")
        return 1
    story = _archive(args.archive).capture_memory(
        client,
        anchor=json.loads(args.anchor) if args.anchor else {},
        who=args.who,
        account=account,
        status=args.status,
    )
    print(f"saved story {story['id']} ({args.status})")
    return 0


def cmd_gedcom(args: argparse.Namespace) -> int:
    from tools.gedcom_document import GedcomDocument

    archive = _archive(args.archive)
    if args.action == "export":
        Path(args.file).write_text(GedcomDocument.to_text(archive), encoding="utf-8")
        print(f"wrote GEDCOM 7.0 to {args.file}")
        return 0
    # import: parse + report — applying a file's wire shapes to the archive
    # is a reviewed, per-document capture, never a blind write (2026-08-06)
    text = Path(args.file).read_text(encoding="utf-8")
    places_table = archive.get_identity("places")
    result = GedcomDocument.from_text(text, (places_table or {}).get("places", []))
    print(f"parsed {args.file}: {len(result['people'])} people, {len(result['relationships'])} relationships")
    return 0


def cmd_eval_memory(args: argparse.Namespace) -> int:
    from tools.eval_memory import main as eval_main

    return eval_main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loft", description="The Loft archive tools — one surface.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("publish", help="regenerate the projection (app/data) from the archive")
    p.add_argument("--archive", default="archive")
    p.add_argument("--data", default="app/data")
    p.set_defaults(fn=cmd_publish)

    p = sub.add_parser("serve", help="serve the app (no-cache) with the memory-capture API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8124)
    p.add_argument("--archive", default="archive")
    p.add_argument("--data", default="app/data")
    p.add_argument("--app", default=str(ROOT / "app"))
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("create-demo", help="seed a demo archive with fictional content and publish")
    p.add_argument("--archive", default="archive")
    p.add_argument("--data", default="demo/data")
    p.set_defaults(fn=cmd_create_demo)

    p = sub.add_parser("capture-document", help="capture the scanned documents (idempotent)")
    p.add_argument("--scans", type=Path, default=Path("/tmp/paseo-attachments-gfNYXK"))
    p.add_argument("--archive", default="archive")
    p.set_defaults(fn=cmd_capture_document)

    p = sub.add_parser("capture-memory", help="capture a narrator's memory from an account (file or -)")
    p.add_argument("account", help="the narrator's account text, or - for stdin")
    p.add_argument("--who", default="")
    p.add_argument("--anchor", default="", help="JSON anchor context (item/person/theme)")
    p.add_argument("--status", default="draft", choices=["draft", "catalogued"])
    p.add_argument("--archive", default="archive")
    p.set_defaults(fn=cmd_capture_memory)

    p = sub.add_parser("gedcom", help="GEDCOM 7.0 interchange — export the confirmed genealogy, or parse a file")
    p.add_argument("action", choices=["export", "import"])
    p.add_argument("file", help="the GEDCOM file to write (export) or read (import)")
    p.add_argument("--archive", default="archive")
    p.set_defaults(fn=cmd_gedcom)

    p = sub.add_parser("eval-memory", help="run the prototype memory-capture evals")
    p.set_defaults(fn=cmd_eval_memory)

    return parser


def main(argv: list[str] | None = None) -> int:
    # the server's diagnostics must be visible — the auth flows log their
    # outcomes at INFO (2026-08-06: the device flow was diagnosed blind)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
