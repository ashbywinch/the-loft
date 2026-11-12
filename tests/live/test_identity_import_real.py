"""A3's real-archive acceptance — the identity import against the Loft disk.

Runs only under `make verify` (`-m archive`); CI has no archive.
"""

# lucidlint: ignore-file fakefs the import reads a real archive tree and writes a real
# SQLite database — C-level I/O, the testing standard's real-FS exception.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loft.live.import_identity import _latest, import_identities
from loft.live.store import LiveStore
from tools.records import OrgsTable, PeopleTable, PlacesTable, ThemesTable

ARCHIVE = Path("/run/media/ashby/One Touch/Loft/archive")


@pytest.mark.archive
def test_the_real_archive_identity_tables_import_and_read_back(tmp_path: Path) -> None:
    marker = tmp_path / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        report = import_identities(store, ARCHIVE, backup_marker=marker)
        people = PeopleTable.from_dict(json.loads(_latest(ARCHIVE, "people").read_text(encoding="utf-8")))
        places = PlacesTable.from_dict(json.loads(_latest(ARCHIVE, "places").read_text(encoding="utf-8")))
        orgs = OrgsTable.from_dict(json.loads(_latest(ARCHIVE, "orgs").read_text(encoding="utf-8")))
        themes = ThemesTable.from_dict(json.loads(_latest(ARCHIVE, "themes").read_text(encoding="utf-8")))
        assert report.counts == {
            "people": len(people.people),
            "relationships": len(people.relationships),
            "places": len(places.places),
            "orgs": len(orgs.orgs),
            "themes": len(themes.themes),
        }
        assert report.mismatches == ()
        assert store.verify_chain() == ()
        for person in people.people[:5]:
            assert store.people.require(person.id).name == person.name
    finally:
        store.close()
