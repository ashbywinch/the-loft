"""The architecture layers (2026-08-09, user): the review API subset over
the store is a layer boundary, and this pins the whole stack's direction.

Layers: app (frontend) -> server (HTTP) -> archive (the domain API over
the store) -> store (the append-only file store). The rules:
- the HTTP layer reaches the data ONLY through the Archive's methods —
  never the store's file methods, never an ad-hoc identity-table write;
- the review flow's operations (resolve/decide, the session records) are
  Archive methods, not handler-level edits;
- the read-only derived layers (projection, memory) never write the
  identity tables;
- the domain imports the store, never the HTTP layer.
"""

from __future__ import annotations

from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def _source(name: str) -> str:
    return (TOOLS / name).read_text(encoding="utf-8")


def test_the_http_layer_routes_data_through_the_archive_api() -> None:
    server = _source("server.py")
    # the review flow's operations are the Archive's API (2026-08-09): the
    # handlers call the domain methods — resolve, the queue, the session
    # records — never ad-hoc table edits
    for call in (
        "archive.resolve_person(",
        "archive.review_queue()",
        "archive.record_review_message(",
        "archive.record_review_decision(",
        "archive.get_identity(",
    ):
        assert call in server, f"the server must route through the Archive API: {call}"
    assert "save_identity(" not in server, "the HTTP layer never writes an identity table"
    # the HTTP layer never touches the store's files directly — the
    # Archive is the only path to the data
    for forbidden in ("store.read(", "store.write_new(", "store.read_bytes(", "store.delete(", "store.exists("):
        assert forbidden not in server, f"the HTTP layer never touches the store's files: {forbidden}"


def test_the_read_only_derived_layers_never_write_the_identity_tables() -> None:
    # projection and memory derive from the archive — they must never write
    # the identity tables themselves (only the archive and the
    # import/bootstrap tools may)
    for name in ("projection.py", "memory.py"):
        assert "save_identity(" not in _source(name), f"{name} must not write the identity tables"


def test_the_archive_is_the_domain_api_over_the_store() -> None:
    archive = _source("archive.py")
    # the domain owns the store and the identity-table write seam
    assert "from tools.store import" in archive
    assert "save_identity" in archive
    # and it never reaches up into the HTTP layer
    assert "fastapi" not in archive.lower()
