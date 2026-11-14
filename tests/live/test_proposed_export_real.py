"""B3b's real-archive acceptance: the exported proposed queue equals the old one.

Runs only under `make verify` (`-m archive`); CI has no archive. The identity
tables are imported (A3) into a scratch database and the queue exporter runs
against a scratch archive. The real queue is copied in first: every real file
must survive byte-identical (the queue is append-only; the real records were
promoted, so their rows are confirmed), and every `proposed` row — the nine
the table still holds, which the real queue never wrote a file for — must gain
one. A reject then removes exactly its own file and a promote keeps its own.
The real archive is read, never written.
"""

# lucidlint: ignore-file fakefs the check reads the real archive and writes a real
# SQLite database and a scratch archive — C-level I/O, the testing standard's
# real-FS exception.

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from loft.live.compat import CompatibilityExport
from loft.live.import_identity import import_identities
from loft.live.store import LiveStore
from tools.archive import Archive
from tools.loft_paths import LoftPaths
from tools.records import Person, Place
from tools.store import DiskStore

ARCHIVE = LoftPaths.ARCHIVE_DIR


def _queue_files(root: Path) -> list[str]:
    """Every queue file under a tree, relative and sorted."""
    return sorted(str(path.relative_to(root)) for path in (root / "proposed").rglob("*.json"))


def _parsed(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _imported(tmp_path: Path) -> LiveStore:
    marker = tmp_path / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    report = import_identities(store, ARCHIVE, backup_marker=marker)
    assert report.mismatches == ()
    return store


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE / "people.json").exists(), reason="archive not mounted")
def test_every_proposed_row_gains_the_queue_file_the_real_queue_never_wrote(tmp_path: Path) -> None:
    """The table's own proposals (the identify pass's, never queued by the old
    path) get a file in the old shape — the read side then lists them."""
    store = _imported(tmp_path)
    scratch = tmp_path / "archive"
    scratch.mkdir()
    archive = Archive(DiskStore(scratch))
    try:
        CompatibilityExport(store, archive).write()
        proposed_people = [person for person in store.people.all() if person.status == "proposed"]
        proposed_places = [place for place in store.places.all() if place.status == "proposed"]
        assert proposed_people, "the real archive has no proposed person to check"
        assert {path for path in _queue_files(scratch) if path.startswith("proposed/people/")} == {
            f"proposed/people/{person.id}.json" for person in proposed_people
        }
        assert {path for path in _queue_files(scratch) if path.startswith("proposed/places/")} == {
            f"proposed/places/{place.id}.json" for place in proposed_places
        }
        for person in proposed_people:
            exported = Person.from_dict(_parsed(scratch / "proposed" / "people" / f"{person.id}.json"))
            assert exported.to_dict() == person.to_dict(), f"person {person.id} does not round-trip"
            assert exported.status == "proposed"
        for place in proposed_places:
            exported_place = Place.from_dict(_parsed(scratch / "proposed" / "places" / f"{place.id}.json"))
            assert exported_place.to_dict() == place.to_dict(), f"place {place.id} does not round-trip"
    finally:
        store.close()


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE / "people.json").exists(), reason="archive not mounted")
def test_the_real_queue_survives_a_reject_removes_one_file_and_a_promote_keeps_one(tmp_path: Path) -> None:
    """The append-only queue on the real sample: every real file stays
    byte-identical, a reject removes exactly its own file, and a promote keeps
    its own."""
    store = _imported(tmp_path)
    scratch = tmp_path / "archive"
    scratch.mkdir()
    shutil.copytree(ARCHIVE / "proposed", scratch / "proposed")
    archive = Archive(DiskStore(scratch))
    real = {path: (ARCHIVE / path).read_bytes() for path in _queue_files(ARCHIVE)}
    try:
        assert len(real) == 29  # the sample the handoff counted
        CompatibilityExport(store, archive).write()
        assert {path: (scratch / path).read_bytes() for path in real} == real  # kept, never rewritten

        proposed = [person for person in store.people.all() if person.status == "proposed"]
        rejected_id, promoted_id = proposed[0].id, proposed[1].id
        store.identities.reject_person(rejected_id, actor="p-editor")
        store.identities.promote_person(promoted_id, actor="p-editor")
        CompatibilityExport(store, archive).write()

        assert not (scratch / "proposed" / "people" / f"{rejected_id}.json").exists()
        assert (scratch / "proposed" / "people" / f"{promoted_id}.json").exists()
        assert set(_queue_files(scratch)) == set(real) | {
            f"proposed/people/{person.id}.json" for person in proposed if person.id != rejected_id
        }
    finally:
        store.close()
