"""The letter-import eval (user: the import must not strand people).

An attested family link written only as prose ("Pearl's husband",
"married Marta Voss, 1972") without its corresponding edge lists the
family as "Also in the archive" instead of connected. This eval scans
the import's OWN declared data — the casts and edges the import asserts
— and refuses the build if any attested family link lacks its edge. It
names no family data: the declarations come from the import module
itself.
"""

from __future__ import annotations

import pytest

from tools.attestation import attested_edge_gaps
from tools.document_capture import email_cast, email_edges, record_cast, record_edges
from tools.loft_paths import ARCHIVE_DIR

ARCHIVE = ARCHIVE_DIR / "people.json"


@pytest.mark.archive
@pytest.mark.skipif(not ARCHIVE.exists(), reason="archive not bootstrapped yet")
def test_letter_import_declared_edges_cover_its_attested_links() -> None:
    people = email_cast() + record_cast()
    gaps = attested_edge_gaps(people, email_edges() + record_edges())
    assert not gaps, "the letter import declares family links without edges:\n" + "\n".join(gaps)


@pytest.mark.archive
@pytest.mark.skipif(not ARCHIVE.exists(), reason="archive not bootstrapped yet")
def test_declared_edge_endpoints_are_declared_people() -> None:
    """Every endpoint of the import's declared edges must be a declared
    person — a fresh bootstrap validates the table, so an edge to an
    undeclared id fails capture-document."""
    declared = {p["id"] for p in email_cast() + record_cast()}
    missing = sorted(
        {
            endpoint
            for edge in email_edges() + record_edges()
            for endpoint in (edge["a"], edge["b"])
            if endpoint not in declared
        }
    )
    assert not missing, "declared edges reference undeclared people:\n" + "\n".join(missing)
