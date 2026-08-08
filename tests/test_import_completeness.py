"""The import-completeness eval (2026-08-06): the live archive must
contain everything the import declares.

The import script grew Theo Kendall Sr/Jr and their edges while the
live archive stayed put — the import's "already in the table — skipping"
note hid the drift, and the tree silently lacked two people. This eval
compares the import's declared casts and edges against the live archive
and refuses the build when the archive has less than the import
declares. The reverse direction (the archive holding more than the
import declares) is fine — captures land in the archive by other routes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools.document_capture import email_cast, email_edges, record_cast, record_edges

REPO = Path(__file__).resolve().parent.parent


def _latest(paths: list[Path]) -> Path:
    best: tuple[int, Path] | None = None
    for p in paths:
        m = re.search(r"(\d+)\.json$", p.name)
        version = int(m.group(1)) if m else 1
        if best is None or version > best[0]:
            best = (version, p)
    assert best is not None
    return best[1]


@pytest.mark.skipif(not (REPO / "archive" / "people.json").exists(), reason="archive not bootstrapped yet")
def test_live_archive_contains_everything_the_import_declares() -> None:
    paths = sorted((REPO / "archive").glob("people*.json"))
    table = json.loads(_latest(paths).read_text(encoding="utf-8"))
    live_ids = {p["id"] for p in table.get("people", [])}
    live_edges = {(r.get("a"), r.get("b"), r.get("kind")) for r in table.get("relationships", [])}

    declared_people = email_cast() + record_cast()
    declared_edges = email_edges() + record_edges()

    missing_people = [p["id"] for p in declared_people if p["id"] not in live_ids]
    missing_edges = [e for e in declared_edges if (e["a"], e["b"], e["kind"]) not in live_edges]

    assert not missing_people, (
        "the live archive lacks people the import declares — a fresh bootstrap would add them, "
        "so the live tree is silently missing them:\n" + "\n".join(missing_people)
    )
    assert not missing_edges, "the live archive lacks edges the import declares:\n" + "\n".join(
        f"{e['a']} {e['kind']} {e['b']}" for e in missing_edges
    )
