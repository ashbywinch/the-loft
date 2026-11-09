"""Every test suite is classified in the port ledger.

The ledger is the rewrite's coverage guard: a suite missing from it can be
dropped silently when its mechanism moves. The rule is
`docs/PLAN/REWRITE-PLAN.md` "Test first, port first".
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / "docs/PLAN/test-port-ledger.md"
DISPOSITIONS = ("keep", "port", "replace")


def _rows() -> list[list[str]]:
    rows: list[list[str]] = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5 or set(cells) == {"---"} or cells[0] == "Area":
            continue
        rows.append(cells)
    return rows


def _suite_files() -> list[str]:
    found = [*REPO.glob("tests/**/test_*.py"), *REPO.glob("app/tests/**/*.test.js")]
    return sorted(str(path.relative_to(REPO)) for path in found)


def _patterns(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def test_every_suite_is_classified() -> None:
    rows = _rows()
    assert rows, "the port ledger has no rows"

    classified: set[str] = set()
    for area, suites, disposition, _increment, _home in rows:
        assert disposition.startswith(DISPOSITIONS), f"{area}: unknown disposition {disposition!r}"
        for pattern in _patterns(suites):
            matches = [path for path in REPO.glob(pattern) if path.is_file()]
            assert matches, f"{area}: pattern matches no file: {pattern}"
            classified.update(str(path.relative_to(REPO)) for path in matches)

    missing = sorted(set(_suite_files()) - classified)
    assert not missing, "test suites missing from the port ledger: " + ", ".join(missing)


def test_every_replace_row_names_its_covering_test() -> None:
    for area, _suites, disposition, _increment, home in _rows():
        if disposition.startswith("replace"):
            assert _patterns(home), f"{area}: a replace row must name the covering test"
