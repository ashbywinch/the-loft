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

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from tools.atomic import atomic_write

# The review surface's image: the page must read and check rows on a phone,
# not carry the 12-megapixel JPEG over the LAN. Re-encode as WebP at the
# page's own pixel dimensions for now — both readers still take their box
# coordinates from the image's natural size, so the 2000px target needs a
# coordinate change first. The derivative is cached beside the page.
VIEW_MAX_EDGE: int | None = None
VIEW_QUALITY = 70

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
    def view_dir(self) -> Path:
        return self.batch_dir / "view"

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

    def view(self, page: str) -> Path:
        """The cached review derivative of one page (WebP; the page's own
        pixel dimensions until the box-normalisation change permits 2000px)."""
        return self.view_dir / f"{Path(page).stem}.webp"

    def view_image(self, page: str, source: Path | None = None) -> Path:
        """Render (or reuse) the page's view image from *source*.

        The derivative is rebuilt when the source is newer, so a rotate or a
        re-read invalidates it. Written temp-then-rename: a concurrent reader
        never sees half an image.
        """
        source = source or self.oriented(page)
        if not source.is_file():
            raise FileNotFoundError(source)
        target = self.view(page)
        if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
            return target
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            if VIEW_MAX_EDGE is not None:
                image.thumbnail((VIEW_MAX_EDGE, VIEW_MAX_EDGE), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, "WEBP", quality=VIEW_QUALITY, method=4)
        atomic_write(target, buffer.getvalue())
        return target

    def text(self, page: str) -> Path:
        """The page's text — the review's draft, whatever read wrote it."""
        return self.guess_dir / f"{Path(page).stem}.txt"

    def marker(self, page: str, kind: str) -> Path:
        """One read marker (``printed``, ``structured``, ``rows``, ``words``)."""
        return self.guess_dir / f"{Path(page).stem}.{kind}.json"

    def agreed(self, page: str) -> Path:
        """The reviewer's approval of this page's text (the transcript approval)."""
        return self.marker(page, "agreed")

    def adjustments(self, page: str) -> Path:
        """The reviewer's drawn row lines."""
        return self.guess_dir / f"{Path(page).stem}.{ADJUSTMENTS}"

    def adjusted_rows(self, page: str) -> Path:
        """The correction's rows (the wire contract)."""
        return self.guess_dir / f"{Path(page).stem}.{ADJUSTED_ROWS}"

    def read_receipts(self, page: str) -> tuple[Path, ...]:
        """Everything that says this page's read is done: its text and every
        read marker. Deleting these makes the read step run for the page again
        — the honest form of "re-read this page"."""
        return (
            self.text(page),
            *(self.marker(page, kind) for kind in ("printed", "structured", "rows", "words")),
        )

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
