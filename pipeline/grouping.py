"""The document grouping scorer (TECHSPEC §16.14).

The guess's model flags (greeting/sign-off boundaries) decide text-only
grouping; the scorer adds the physical evidence the model never sees —
the full page sequence (photo pages included), the paper sizes, and the
page numbers. Evidence priority (user):

1. Duplex sides — a photo/drawing page adjacent to a text page of the
   same paper is the two sides of one sheet: same document, the picture
   side first. Fires only on the duplex cue — never random association.
2. Paper size — different papers are probably not the same document.
3. Page numbers — a page starting "2" continues its document; a fresh
   "1" starts one.
4. The model's greeting/sign-off flags — the fallback for text pages.

A pair with no evidence follows the model's flags. Out-of-order or
missing pages simply score lower — the scorer never invents a
relationship (the graceful-degradation rule).
"""

from __future__ import annotations

import re

from document.page_size import PageSize
from pipeline.boundary import Boundary
from pipeline.page_flag import PageFlag

_ASPECT_EPS = 1e-9  # float division-underflow guard

# The paper-size tolerance for phone scans: the SAME physical sheet
# photographed twice differs in pixel dims (distance, crop — the
# postcard's two sides measure 3500x2215 and 2333x3500), so
# the comparison is the normalized aspect (min/max), within 12%: a
# postcard (0.63-0.70) vs A4 (0.71) vs letter (0.77) stay separable
# while the two sides of one sheet match.
PAPER_TOLERANCE = 0.12

_LIGHT_KINDS = ("photo", "drawing")

_PAGE_NUMBER = re.compile(r"^\s*(?:page\s*)?(\d{1,3})\s*[.)]?\s*$", re.IGNORECASE)


def paper_aspect(width: int, height: int) -> float:
    """The rotation-invariant shape: the normalized aspect (min/max)."""
    return min(width, height) / max(width, height)


def same_paper(a: PageSize, b: PageSize, tolerance: float = PAPER_TOLERANCE) -> bool:
    """Two page images are the same physical paper when their normalized
    aspects agree within the tolerance (the phone-scan proxy for paper
    size)."""
    pa, pb = paper_aspect(a.width, a.height), paper_aspect(b.width, b.height)
    return abs(pa - pb) / max(min(pa, pb), _ASPECT_EPS) <= tolerance


def first_page_number(text: str | None) -> int | None:
    """A page's first line that is a page number — "2", "page 2", "2."
    (the model's corrected text; photo pages have none). None when the
    line is not a plain number, so a date or a greeting never fires."""
    if not text:
        return None
    first = text.split("\n", 1)[0].strip()
    m = _PAGE_NUMBER.match(first)
    return int(m.group(1)) if m else None


def _is_light(kind: str) -> bool:
    return kind in _LIGHT_KINDS


class GroupingScorer:
    """The document-grouping scorer (TECHSPEC §16.14): the page evidence —
    kinds, paper sizes, corrected texts, the model's flags — and the
    boundary decisions over the full sequence. The evidence lives here
    once; the helpers that used to receive (page, flags) everywhere read
    it off the scorer."""

    def __init__(
        self,
        kinds: dict[str, str],
        dims: dict[str, PageSize],
        texts: dict[str, str | None],
        flags: dict[str, PageFlag],
    ) -> None:
        self._kinds = kinds
        self._dims = dims
        self._texts = texts
        self._flags = flags

    def _flag(self, page: str) -> PageFlag | None:
        """The model's boundary report for ``page``, None for a page the
        model reported nothing on (a photo page)."""
        return self._flags.get(page)

    def _open_boundary(self, boundaries: list[Boundary], page: str) -> Boundary:
        """A fresh boundary at ``page``, appended to the sequence."""
        boundary = Boundary.opening_at(page, self._flag(page))
        boundaries.append(boundary)
        return boundary

    def _text_pair_decision(self, prev: str, page: str) -> bool:
        """The text-text rules for an adjacent pair — "join" (True, same
        document) or "split" (False, a new document at ``page``), in the
        2026-08-17 priority order: paper size, then page numbers, then the
        model's greeting/sign-off flags."""
        if not same_paper(self._dims[prev], self._dims[page]):
            return False  # 2. different papers are not the same document
        n = first_page_number(self._texts.get(page))
        if n is not None:
            # 3. page numbers outvote the model flags: a numbered
            # continuation joins, a fresh "1" starts a new document
            return n != 1
        # 4. the model's greeting/sign-off flags
        prev_flag, flag = self._flag(prev), self._flag(page)
        closes = prev_flag is not None and prev_flag.ends_document
        opens = flag is not None and flag.starts_document
        return not (closes or opens)

    def score(self, pages: list[str]) -> list[Boundary]:
        """The full-sequence grouping — the loop score_boundaries runs over
        the scorer's evidence (see score_boundaries for the rules)."""
        boundaries: list[Boundary] = []
        current: Boundary | None = None
        # the pages already claimed by a duplex pair — a page is the two sides
        # of at most ONE sheet, so the greedy pair never pairs again with its
        # other neighbour ([back1, front1, back2]: front1 pairs with back1,
        # never with back2)
        claimed: set[str] = set()
        prev: str | None = None
        for page in pages:
            kind = str(self._kinds.get(page, "text"))
            if current is None:
                current = self._open_boundary(boundaries, page)
                prev = page
                continue
            assert prev is not None  # the first iteration set it — pyrefly's narrowing needs the explicit fact
            prev_kind = str(self._kinds.get(prev, "text"))
            # 1. the duplex cue (strongest): one light side + one text side,
            # the same paper — the two sides of one sheet, same document.
            if (
                _is_light(kind) != _is_light(prev_kind)
                and same_paper(self._dims[prev], self._dims[page])
                and page not in claimed
                and prev not in claimed
            ):
                claimed.add(prev)
                claimed.add(page)
                if _is_light(kind) and not _is_light(prev_kind):
                    # the picture side was scanned AFTER its text side — it
                    # is still page 1 (user, 2026-08-17: the picture side of
                    # a postcard is the first page, whatever the scan order)
                    current.add_first(page)
                else:
                    current.add(page)
                current.carry(self._flag(page))
            elif kind == "text" and prev_kind == "text":
                if self._text_pair_decision(prev, page):
                    current.add(page)
                else:
                    current = self._open_boundary(boundaries, page)
                current.carry(self._flag(page))
            else:
                # a light page after a text page of a different paper, or two
                # light pages — no cue: it starts its own boundary
                current = self._open_boundary(boundaries, page)
            prev = page
        return boundaries


def score_boundaries(
    pages: list[str],
    kinds: dict[str, str],
    dims: dict[str, PageSize],
    texts: dict[str, str | None],
    flags: dict[str, PageFlag],
) -> list[Boundary]:
    """Group the FULL page sequence (photos included, in scan order) into
    documents by the evidence hierarchy. Returns the boundaries list —
    the same shape the guess stage publishes. ``flags`` is the model's
    per-page boundary report (text pages only); ``dims`` the image
    sizes; ``texts`` the corrected page text (None for photos)."""
    return GroupingScorer(kinds, dims, texts, flags).score(pages)
