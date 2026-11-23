"""The page commit — one page version's write inside a change.

`tests/live/test_live_store.py` pins the same write through `change.pages`;
this suite names the step itself. The commit decides create vs supersede
against the projection, so the version it becomes, the event it appends and
the row it writes are one decision — and a refused one writes nothing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from loft.live.errors import Conflict, NotFound, StaleVersion
from loft.live.page_commit import PageCommit
from loft.live.page_row import PageState
from loft.live.store import LiveStore

PAGE_ID = "batch-1/page-01.jpg"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[LiveStore]:
    live = LiveStore.create(tmp_path / "loft.db", app_version="test")
    yield live
    live.close()


def _page(*, revision: int = 1) -> PageState:
    return PageState(
        page_id=PAGE_ID,
        image_asset_id=PAGE_ID,
        sha256="sha-1",
        revision=revision,
        rotation=180,
        category="text",
        status="rows_pending",
    )


def _reading(text: str = "Hello") -> dict[str, Any]:
    return {
        "page": "ignored",
        "width": 100,
        "height": 200,
        "rotation": 0,
        "revision": 1,
        "lines": [{"index": 0, "text": text, "box": [0, 0, 10, 10], "words": []}],
        "words": [{"x0": 0, "y0": 0, "x1": 10, "y1": 10}],
    }


def _commit(change: Any, *, base: int | None = None, revision: int = 1) -> PageCommit:
    return PageCommit(change, change.pages.projection, _page(revision=revision), base=base)


def test_a_create_appends_one_event_and_writes_the_row(store: LiveStore) -> None:
    with store.change(actor="import") as change:
        saved = _commit(change).commit(reading=_reading())
    assert saved.revision == 1
    events = store.events_for(PAGE_ID, entity_kind="page")
    assert [event["event_type"] for event in events] == ["created"]
    assert store.pages.require(PAGE_ID).status == "rows_pending"
    assert store.verify_chain() == ()


def test_a_page_cannot_be_built_below_its_first_version() -> None:
    """A page's version starts at 1 and only grows: `PageState` refuses 0 as
    well as a negative one where the page is made, so `_version`'s create case
    is the page's own version rather than a repair of a zero."""
    with pytest.raises(ValueError, match="must carry a version"):
        _page(revision=0)
    with pytest.raises(ValueError, match="must carry a version"):
        _page(revision=-1)


def test_a_commit_stores_the_reading_and_the_adjustment_together(store: LiveStore) -> None:
    """One commit can carry both: the reading blob and the reviewer's
    correction are stored in the same version, and the rows derive from the
    reading."""
    with store.change(actor="review") as change:
        saved = _commit(change).commit(reading=_reading(), adjustment=b'{"lines": []}', adjustment_at="2026-01-01")
    assert saved.revision == 1
    reading = store.pages.reading(PAGE_ID)
    assert reading is not None and reading.rows == 1
    adjustment = store.pages.adjustment(PAGE_ID)
    assert adjustment is not None and store.content.get(adjustment.sha256) == b'{"lines": []}'


def test_a_create_stores_the_reading_blob_and_counts_it(store: LiveStore) -> None:
    with store.change(actor="import") as change:
        _commit(change).commit(reading=_reading())
    reading = store.pages.reading(PAGE_ID)
    assert reading is not None and (reading.rows, reading.words) == (1, 1)
    blob = store.pages.reading_blob(PAGE_ID)
    assert blob is not None and blob["lines"][0]["text"] == "Hello"
    assert [row.text for row in store.pages.rows(PAGE_ID)] == ["Hello"]


def test_a_create_that_finds_the_page_is_a_conflict(store: LiveStore) -> None:
    with store.change(actor="import") as change:
        _commit(change).commit(reading=_reading())
    with pytest.raises(Conflict, match="exists"), store.change(actor="import") as change:
        _commit(change).commit(reading=_reading())
    assert len(store.events_for(PAGE_ID, entity_kind="page")) == 1


def test_a_supersede_is_the_next_version_and_replaces_the_rows(store: LiveStore) -> None:
    with store.change(actor="import") as change:
        _commit(change).commit(reading=_reading("Hello"))
    with store.change(actor="import") as change:
        saved = _commit(change, base=1).commit(reading=_reading("Changed"))
    assert saved.revision == 2
    assert [event["event_type"] for event in store.events_for(PAGE_ID, entity_kind="page")] == [
        "created",
        "superseded",
    ]
    assert [row.text for row in store.pages.rows(PAGE_ID)] == ["Changed"]
    assert store.verify_chain() == ()


def test_a_supersede_of_an_unknown_page_is_not_found(store: LiveStore) -> None:
    with pytest.raises(NotFound, match=PAGE_ID), store.change(actor="import") as change:
        _commit(change, base=1).commit(reading=_reading())
    assert store.events_for(PAGE_ID, entity_kind="page") == []


def test_a_stale_base_is_refused_with_the_page_as_it_stands(store: LiveStore) -> None:
    with store.change(actor="import") as change:
        _commit(change).commit(reading=_reading("Hello"))
    with store.change(actor="import") as change:
        _commit(change, base=1).commit(reading=_reading("Second"))
    with pytest.raises(StaleVersion) as caught, store.change(actor="import") as change:
        _commit(change, base=1).commit(reading=_reading("Lost"))
    assert caught.value.current is not None and caught.value.current.revision == 2
    assert [row.text for row in store.pages.rows(PAGE_ID)] == ["Second"]  # the refused write changed nothing


def test_a_commit_with_no_reading_stores_no_blob_and_no_rows(store: LiveStore) -> None:
    with store.change(actor="import") as change:
        _commit(change).commit()
    assert store.pages.reading(PAGE_ID) is None
    assert store.pages.rows(PAGE_ID) == ()


def test_the_adjustment_is_stored_as_the_pages_correction(store: LiveStore) -> None:
    drawn = b'{"lines":[]}'
    with store.change(actor="import") as change:
        _commit(change).commit(reading=_reading(), adjustment=drawn, adjustment_at="2026-01-01T00:00:00+00:00")
    adjustment = store.pages.adjustment(PAGE_ID)
    assert adjustment is not None
    assert adjustment.sha256 == hashlib.sha256(drawn).hexdigest()
    assert adjustment.updated_at == "2026-01-01T00:00:00+00:00"


def test_an_adjustment_without_a_reading_is_stored_on_its_own(store: LiveStore) -> None:
    """The import pipeline saves a page whose correction exists before any
    reading does (`PagePlan.reading` is None when the reading file is absent),
    so the two are independent arguments of one commit."""
    drawn = b'{"lines":[]}'
    with store.change(actor="import") as change:
        _commit(change).commit(adjustment=drawn, adjustment_at="2026-01-01T00:00:00+00:00")
    adjustment = store.pages.adjustment(PAGE_ID)
    assert adjustment is not None and adjustment.sha256 == hashlib.sha256(drawn).hexdigest()
    assert store.pages.reading(PAGE_ID) is None
    assert store.pages.rows(PAGE_ID) == ()
