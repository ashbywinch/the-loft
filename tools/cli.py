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
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import uvicorn

from tools.ai_client import AIClient, AIClientError
from tools.archive import Archive
from tools.gedcom_document import GedcomDocument
from tools.loft_paths import ARCHIVE_DIR
from tools.server import Server, ServerConfig, build_app, lan_urls
from tools.store import DiskStore

ROOT = Path(__file__).resolve().parent.parent


def _archive(archive_dir: str) -> Archive:
    return Archive(DiskStore(Path(archive_dir)))


def _publish_and_report(archive: Archive, archive_dir: str, data_dir: str, verb: str) -> int:
    """Publish the projection to *data_dir* and print the outcome — the
    shared publish+print tail of the publish and create-demo commands."""
    archive.publish(Path(data_dir))
    print(f"{verb} {archive_dir} -> {data_dir}")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    return _publish_and_report(_archive(args.archive), args.archive, args.data, "published")


def cmd_create_demo(args: argparse.Namespace) -> int:
    archive = _archive(args.archive)
    archive.create_demo()  # the demo's own projection, never app/data by surprise
    return _publish_and_report(archive, args.archive, args.data, "seeded demo archive")


def _capture_client() -> AIClient | None:
    """The capture client when an API key exists — the capture API needs the
    key; absent, the server serves without capture (visible, never silent)."""
    try:
        return AIClient()
    except AIClientError as e:
        print(f"serve: no capture client ({e}) — serving the app only")
        return None


def serve_app(_env: Mapping[str, str] | None = None) -> Any:
    """The uvicorn factory for --reload (2026-08-16: make serve always
    auto-reloads the backend on source changes). The reloader re-imports
    this module and calls the factory fresh in a subprocess — the server's
    configuration travels via the environment the CLI set before running.
    ``_env`` is the injectable seam for tests; None reads the process env."""
    env = os.environ if _env is None else _env
    client = _capture_client()
    return build_app(
        ServerConfig(
            DiskStore(Path(env["LOFT_ARCHIVE"])),
            Path(env["LOFT_DATA"]),
            client,
            Path(env["LOFT_APP"]),
        ),
        _env=env,
    )


def cmd_serve(args: argparse.Namespace) -> int:
    if args.reload:
        # auto-reload: uvicorn needs the app as an import string + factory —
        # the config rides the environment into the reloader's subprocess
        os.environ["LOFT_ARCHIVE"] = str(args.archive)
        os.environ["LOFT_DATA"] = str(args.data)
        os.environ["LOFT_APP"] = str(args.app)
        if args.host == "0.0.0.0":
            for url in lan_urls(args.port):
                print(f"Serving {args.app} at {url} (no-cache, reload on)")
        else:
            print(f"Serving {args.app} on {args.host}:{args.port} (no-cache, reload on)")
        uvicorn.run(
            "tools.cli:serve_app",
            factory=True,
            reload=True,
            # Watch only the backend source — the whole-repo watch scans and
            # reloads on .venv/conda-tools churn, and uvicorn's reload-exclude
            # patterns can't match mid-path dirs (Path.match is right-aligned;
            # absolute patterns are rejected outright, 2026-08-16). Narrow
            # roots are the honest fix: tools/ + tests/ are all the backend
            # has; the frontend is served without a build step.
            reload_dirs=[str(ROOT / "tools"), str(ROOT / "tests")],
            host=args.host,
            port=args.port,
            log_level="info",
        )
        return 0

    client = _capture_client()
    Server(
        ServerConfig(
            DiskStore(Path(args.archive)),
            Path(args.data),
            client,
            Path(args.app),
        ),
        host=args.host,
        port=args.port,
    ).serve()
    return 0


def cmd_capture_document(args: argparse.Namespace) -> int:
    _archive(args.archive).capture_document(Path(args.scans))
    return 0


def cmd_capture_memory(args: argparse.Namespace) -> int:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loft", description="The Loft archive tools — one surface.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("publish", help="regenerate the projection (app/data) from the archive")
    p.add_argument("--archive", default=str(ARCHIVE_DIR))
    p.add_argument("--data", default="app/data")
    p.set_defaults(fn=cmd_publish)

    p = sub.add_parser("serve", help="serve the app (no-cache) with the memory-capture API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8124)
    p.add_argument("--archive", default=str(ARCHIVE_DIR))
    p.add_argument("--data", default="app/data")
    p.add_argument("--app", default=str(ROOT / "app"))
    p.add_argument("--reload", action="store_true", help="auto-reload the backend on source changes (make serve)")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("create-demo", help="seed a demo archive with fictional content and publish")
    p.add_argument("--archive", default="demo/archive")
    p.add_argument("--data", default="demo/data")
    p.set_defaults(fn=cmd_create_demo)

    p = sub.add_parser("capture-document", help="capture the scanned documents (idempotent)")
    p.add_argument("--scans", type=Path, default=Path("/tmp/paseo-attachments-gfNYXK"))
    p.add_argument("--archive", default=str(ARCHIVE_DIR))
    p.set_defaults(fn=cmd_capture_document)

    p = sub.add_parser("capture-memory", help="capture a narrator's memory from an account (file or -)")
    p.add_argument("account", help="the narrator's account text, or - for stdin")
    p.add_argument("--who", default="")
    p.add_argument("--anchor", default="", help="JSON anchor context (item/person/theme)")
    p.add_argument("--status", default="draft", choices=["draft", "catalogued"])
    p.add_argument("--archive", default=str(ARCHIVE_DIR))
    p.set_defaults(fn=cmd_capture_memory)

    p = sub.add_parser("gedcom", help="GEDCOM 7.0 interchange — export the confirmed genealogy, or parse a file")
    p.add_argument("action", choices=["export", "import"])
    p.add_argument("file", help="the GEDCOM file to write (export) or read (import)")
    p.add_argument("--archive", default=str(ARCHIVE_DIR))
    p.set_defaults(fn=cmd_gedcom)

    return parser


def main(argv: list[str] | None = None) -> int:
    # the server's diagnostics must be visible — the auth flows log their
    # outcomes at INFO (2026-08-06: the device flow was diagnosed blind)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
