"""The 2060 test (PRD §18.9, docs/testing-standards.md): a stranger with no
app and no credentials can reconstruct items from the archive's files alone.

Not tautological: these assertions run against the repo's *real* committed
projection and the *real* contract text, so they fail on plausible bugs —
a missing asset, a malformed item, or the contract drifting."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_committed_projection_is_self_describing() -> None:
    """Every committed item can be reconstructed from its files alone.

    Drafts are committed during dev (user, 2026-08-03), so a known status is
    the invariant — self-describability, not "everything catalogued"."""
    index = json.loads((REPO / "app" / "data" / "index.json").read_text(encoding="utf-8"))
    assert len(index["items"]) > 0, "the committed projection must not be empty"
    required = {"id", "type", "title", "date", "date_precision", "status"}
    for item in index["items"]:
        assert required <= set(item), f"{item.get('id')} is missing required fields"
        assert item["status"] in {"catalogued", "draft"}
        for asset in item["assets"]:
            path = REPO / "app" / "data" / "assets" / item["id"] / asset["file"]
            assert path.exists(), f"referenced asset missing: {path}"


def test_2060_readme_contract_is_specified() -> None:
    """The 2060 contract (a README that explains the archive, no credentials)
    is written down in the requirements — the test fails if it drifts."""
    prd = (REPO / "docs" / "PRD.md").read_text(encoding="utf-8")
    assert "written for a reader in 2060" in prd
    assert "Recoverable without credentials" in prd or "recoverable without credentials" in prd
    assert "README" in prd
