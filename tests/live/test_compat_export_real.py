"""B1's real-archive acceptance: the exported tables equal the old format.

Runs only under `make verify` (`-m archive`); CI has no archive. The check is
field by field and order by order on the real archive: the exporter's tables
are read back through the old reader's own classes and compared with the real
files. Byte equality is not claimed — the oldest on-disk version predates the
current writer's normalisations (one person has no `aliases` key, one has no
`bio`), while our export writes today's deterministic shape. Then the exported
tables re-import as a no-op, and a newer DB record survives a re-import.
"""

# lucidlint: ignore-file fakefs the check reads the real archive and writes a real
# SQLite database and a scratch archive — C-level I/O, the testing standard's
# real-FS exception.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loft.live.compat import CompatibilityExport
from loft.live.import_identity import _latest, import_identities
from loft.live.store import LiveStore
from tools.archive import Archive
from tools.loft_paths import LoftPaths
from tools.records import OrgsTable, PeopleTable, PlacesTable, ThemesTable
from tools.store import DiskStore

ARCHIVE = LoftPaths.ARCHIVE_DIR
TABLES = {
    "people": PeopleTable.from_dict,
    "places": PlacesTable.from_dict,
    "orgs": OrgsTable.from_dict,
    "themes": ThemesTable.from_dict,
}


def _payload(path: Path) -> dict:
    """The written file's payload without the append-only chain pointer."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("supersedes", None)
    return payload


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE / "people.json").exists(), reason="archive not mounted")
def test_the_exported_tables_equal_the_real_old_files(tmp_path: Path) -> None:
    marker = tmp_path / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    scratch = tmp_path / "archive"
    scratch.mkdir()
    archive = Archive(DiskStore(scratch))
    try:
        report = import_identities(store, ARCHIVE, backup_marker=marker)
        assert report.mismatches == ()
        # seed empty v1 tables: the exporter's v2 must reproduce the real file
        for name in TABLES:
            archive.save_identity(
                name,
                {
                    "people": PeopleTable(people=(), relationships=()),
                    "places": PlacesTable(places=()),
                    "orgs": OrgsTable(orgs=()),
                    "themes": ThemesTable(themes=()),
                }[name],
            )
        assert CompatibilityExport(store, archive).write() == ("people", "places", "orgs", "themes")
        for name, parse in TABLES.items():
            real = _latest(ARCHIVE, name)
            exported = scratch / f"{name}-2.json"
            assert exported.is_file(), f"{name} did not get a second version"
            assert json.loads(exported.read_text(encoding="utf-8"))["supersedes"] == f"{name}.json"
            # through the old reader's own class: every field, in the archive's
            # order. (Byte equality is not claimed: the on-disk v37 predates the
            # current writer's `aliases: []` normalisation on one record, so the
            # semantic diff is the contract — see the docstring.)
            assert parse(_payload(exported)).to_dict() == parse(_payload(real)).to_dict(), (
                f"{name} differs from the old file"
            )
    finally:
        store.close()


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE / "people.json").exists(), reason="archive not mounted")
def test_the_exported_tables_re_import_as_a_no_op(tmp_path: Path) -> None:
    marker = tmp_path / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    source = LiveStore.create(tmp_path / "source.db", app_version="test")
    scratch = tmp_path / "archive"
    scratch.mkdir()
    archive = Archive(DiskStore(scratch))
    try:
        import_identities(source, ARCHIVE, backup_marker=marker)
        CompatibilityExport(source, archive).write()
        watched = source.people.all()[0].id
        fresh = LiveStore.create(tmp_path / "fresh.db", app_version="test")
        try:
            first = import_identities(fresh, scratch, backup_marker=marker)
            assert first.mismatches == ()
            assert first.counts == {
                "people": len(source.people.all()),
                "relationships": len(source.relationships.all()),
                "places": len(source.places.all()),
                "orgs": len(source.orgs.all()),
                "themes": len(source.themes.all()),
            }
            events_before = len(fresh.events_for(watched))
            second = import_identities(fresh, scratch, backup_marker=marker)
            assert second.operations == ()
            assert second.skipped == first.counts
            assert len(fresh.events_for(watched)) == events_before
            assert fresh.verify_chain() == ()
        finally:
            fresh.close()
    finally:
        source.close()


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE / "people.json").exists(), reason="archive not mounted")
def test_a_re_import_never_regresses_a_newer_db_record(tmp_path: Path) -> None:
    marker = tmp_path / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        import_identities(store, ARCHIVE, backup_marker=marker)
        proposed = next(person for person in store.people.all() if person.status == "proposed")
        store.identities.confirm_person(proposed.id, actor="p-editor")
        report = import_identities(store, ARCHIVE, backup_marker=marker)
        assert report.operations == ()
        assert store.people.require(proposed.id).status == "confirmed"
        assert store.verify_chain() == ()
    finally:
        store.close()
