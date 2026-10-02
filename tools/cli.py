"""The loft CLI — the one operator surface for the archive's tools.

``loft publish | serve | capture-memory | gedcom in|out | eval-memory``.
Every command constructs an object-model noun and calls its methods —
Archive.publish(), Server.serve(), Archive.capture_memory(),
GedcomDocument.to_text()/from_text() — so the domain vocabulary lives in
the nouns, and the CLI is a thin argument surface. No per-module __main__
shims (coding-standards.md): a command's argv handling lives here, and
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


def _capture_client() -> AIClient | None:
    """The capture client when an API key exists — the capture API needs the
    key; absent, the server serves without capture (visible, never silent)."""
    try:
        return AIClient()
    except AIClientError as e:
        print(f"serve: no capture client ({e}) — serving the app only")
        return None


def serve_app(_env: Mapping[str, str] | None = None) -> Any:
    """The uvicorn factory for --reload (make serve always auto-reloads
    the backend on source changes). The reloader re-imports
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
            # absolute patterns are rejected outright). Narrow
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
    if args.action == "export":
        return _gedcom_export(args.folder, args.path)

    # import: the GEDCOM file -> a self-contained island folder of record
    # files (people.json + places.json, the archive's record structure).
    # The folder is the import's storage — NO destination coupling, all
    # entries are created at import, places included. A target that
    # exists and is non-empty is refused: another import of the same file
    # = another identical structure elsewhere.
    target = Path(args.folder)
    if target.exists() and any(target.iterdir()):
        print(f"refusing: {args.folder} exists and is not empty — import into a fresh folder", file=sys.stderr)
        return 1
    text = Path(args.file).read_text(encoding="utf-8")
    shapes = GedcomDocument.from_text(text).wire_shapes()
    target.mkdir(parents=True, exist_ok=True)
    (target / "people.json").write_text(
        json.dumps({"people": shapes["people"], "relationships": shapes["relationships"]}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (target / "places.json").write_text(
        json.dumps({"places": shapes["places"]}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"imported {args.file}: {len(shapes['people'])} people, "
        f"{len(shapes['relationships'])} relationships, {len(shapes['places'])} places -> {args.folder}"
    )
    return 0


def _gedcom_export(folder_arg: str, path_arg: str) -> int:
    """The island export — re-emit an import folder's confirmed subset as
    GEDCOM 7.0. The four swap-refusals run BEFORE anything is written: a
    swapped command cannot make a mess."""
    folder = Path(folder_arg)
    dest = Path(path_arg)
    # 1. the first argument must BE an import folder: not a bare file, not
    #    a folder without the imported structure
    if not folder.is_dir() or not (folder / "people.json").is_file() or not (folder / "places.json").is_file():
        print(
            f"refusing: {folder_arg} is not an import folder (needs people.json + places.json)",
            file=sys.stderr,
        )
        return 1
    # 2. the destination must not be the import folder or any path inside
    #    it — the source island stays untouched
    dest_resolved = dest.resolve()
    folder_resolved = folder.resolve()
    if dest_resolved == folder_resolved or folder_resolved in dest_resolved.parents:
        print(f"refusing: {path_arg} is the import folder or a path inside it", file=sys.stderr)
        return 1
    # 3. an existing directory, 4. an existing file — no silent overwrite
    if dest.is_dir():
        print(f"refusing: {path_arg} is an existing directory", file=sys.stderr)
        return 1
    if dest.exists():
        print(f"refusing: {path_arg} exists — no silent overwrite", file=sys.stderr)
        return 1
    people_table = json.loads((folder / "people.json").read_text(encoding="utf-8"))
    places_table = json.loads((folder / "places.json").read_text(encoding="utf-8"))
    shapes = {
        "people": people_table.get("people", []),
        "relationships": people_table.get("relationships") or [],
        "places": places_table.get("places", []),
    }
    dest.write_text(GedcomDocument.from_shapes(shapes).to_text(), encoding="utf-8")
    print(f"wrote GEDCOM 7.0 to {path_arg}")
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

    p = sub.add_parser("capture-memory", help="capture a narrator's memory from an account (file or -)")
    p.add_argument("account", help="the narrator's account text, or - for stdin")
    p.add_argument("--who", default="")
    p.add_argument("--anchor", default="", help="JSON anchor context (item/person/theme)")
    p.add_argument("--status", default="draft", choices=["draft", "catalogued"])
    p.add_argument("--archive", default=str(ARCHIVE_DIR))
    p.set_defaults(fn=cmd_capture_memory)

    p = sub.add_parser(
        "gedcom",
        help="GEDCOM 7.0 interchange — import a file into a folder (the island), or export its confirmed subset",
    )
    g = p.add_subparsers(dest="gedcom_action", required=True)
    pi = g.add_parser("import", help="parse a GEDCOM 7 file into a self-contained folder of record files")
    pi.add_argument("file", help="the GEDCOM file to read")
    pi.add_argument("folder", help="the import folder to write (refused when it exists and is not empty)")
    pi.set_defaults(fn=cmd_gedcom, action="import")
    pe = g.add_parser("export", help="re-emit an import folder's confirmed subset as GEDCOM 7.0")
    pe.add_argument("folder", help="the import folder to read")
    pe.add_argument("path", help="the GEDCOM file to write (must not exist)")
    pe.set_defaults(fn=cmd_gedcom, action="export")
    return parser


def main(argv: list[str] | None = None) -> int:
    # the server's diagnostics must be visible — the auth flows log their
    # outcomes at INFO
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
