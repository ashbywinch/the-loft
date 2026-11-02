"""One batch's artefact paths — the one place the stage layout is written.

Every stage writes into ``work/<batch>``: the classification, the oriented
pages, and the readings under ``ocr-guess`` (a page's text and one marker per
read). The API reads those same files to decide what the review may show, and
the reconciler reads them to decide what still needs running. They used to
each spell the layout out, and the spellings disagreed — a page whose marker
existed but whose text did not was "read" to one and "missing" to another, so
the reconciler demanded a stage the stage itself would skip.

``BatchArtefacts`` is that layout, and ``is_read`` is the one answer to "has
this page been read?", per the route the category gives it. A marker is the
completion mark and is written AFTER the text, so a marker is the read's own
word that the read finished.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# the marker suffix each route's read writes (pipeline/classify.read_route)
READ_MARKERS: dict[str, tuple[str, ...]] = {
    "direct": ("printed", "structured"),
    "structured": ("structured",),
    "rows": ("rows",),
    "none": (),
}
# the reviewer's correction files, written beside the reading
ADJUSTMENTS = "row-adjustments.json"
ADJUSTED_ROWS = "rows-adjusted.json"


@dataclass(frozen=True)
class BatchArtefacts:
    """One batch's stage paths, and the read-completion rule over them."""

    work_dir: Path
    batch_id: str

    @property
    def batch_dir(self) -> Path:
        return self.work_dir / self.batch_id

    @property
    def classify(self) -> Path:
        return self.batch_dir / "classify.json"

    @property
    def oriented_dir(self) -> Path:
        return self.batch_dir / "oriented"

    @property
    def raw_dir(self) -> Path:
        return self.batch_dir / "ocr-raw"

    @property
    def guess_dir(self) -> Path:
        return self.batch_dir / "ocr-guess"

    @property
    def boundaries(self) -> Path:
        return self.guess_dir / "boundaries.json"

    def relative(self, path: Path) -> str:
        """The store-relative name of an artefact (PipelineStore's key space)."""
        return str(path.relative_to(self.work_dir))

    def oriented(self, page: str) -> Path:
        return self.oriented_dir / page

    def text(self, page: str) -> Path:
        """The page's text — the review's draft, whatever read wrote it."""
        return self.guess_dir / f"{Path(page).stem}.txt"

    def marker(self, page: str, kind: str) -> Path:
        """One read marker (``printed``, ``structured``, ``rows``, ``words``)."""
        return self.guess_dir / f"{Path(page).stem}.{kind}.json"

    def adjustments(self, page: str) -> Path:
        """The reviewer's drawn row lines."""
        return self.guess_dir / f"{Path(page).stem}.{ADJUSTMENTS}"

    def adjusted_rows(self, page: str) -> Path:
        """The correction's rows (the wire contract)."""
        return self.guess_dir / f"{Path(page).stem}.{ADJUSTED_ROWS}"

    def direct_marker(self, page: str) -> Path:
        """The page's direct-read marker, whichever read wrote it (printed
        prose, or a form's structure); the printed path when there is none."""
        for kind in READ_MARKERS["direct"]:
            marker = self.marker(page, kind)
            if marker.is_file():
                return marker
        return self.marker(page, "printed")

    def read_kind(self, page: str, route: str) -> str | None:
        """The marker kind that completed this page's read, or None."""
        for kind in READ_MARKERS.get(route, ()):
            if self.marker(page, kind).is_file():
                return kind
        return None

    def is_read(self, page: str, route: str) -> bool:
        """Whether the page's read is done: its route's marker exists (the
        marker is written after the text, so it is the read's own receipt).
        A page with no writing to read (route ``none``) is trivially read."""
        return route == "none" or self.read_kind(page, route) is not None
