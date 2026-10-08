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
from typing import Any

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


def same_paper(a: tuple[int, int], b: tuple[int, int], tolerance: float = PAPER_TOLERANCE) -> bool:
    """Two page images are the same physical paper when their normalized
    aspects agree within the tolerance (the phone-scan proxy for paper
    size)."""
    pa, pb = paper_aspect(*a), paper_aspect(*b)
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
        dims: dict[str, tuple[int, int]],
        texts: dict[str, str | None],
        flags: dict[str, dict[str, Any]],
    ) -> None:
        self._kinds = kinds
        self._dims = dims
        self._texts = texts
        self._flags = flags

    def _new_document(self, page: str) -> dict[str, Any]:
        """Open a document at ``page`` — the model's greeting when this page
        carries the starts_document flag (a photo page never does)."""
        flag = self._flags.get(page, {})
        return {
            "pages": [page],
            "greeting": flag.get("greeting") if flag.get("starts_document") else None,
            "signoff": None,
        }

    def _open_document(self, documents: list[dict[str, Any]], page: str) -> dict[str, Any]:
        """A fresh document at ``page``, appended to the sequence."""
        document = self._new_document(page)
        documents.append(document)
        return document

    def _carry(self, doc: dict[str, Any], page: str) -> None:
        """Carry the model's greeting/sign-off into the doc when a joined page
        has them — the duplex doc opens with the picture side (no flag), and
        the text side's model values belong to the doc (2026-08-17)."""
        flag = self._flags.get(page, {})
        if doc.get("greeting") is None and flag.get("greeting"):
            doc["greeting"] = flag["greeting"]
        if flag.get("ends_document") and flag.get("signoff"):
            doc["signoff"] = flag["signoff"]

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
        return not (self._flags.get(prev, {}).get("ends_document") or self._flags.get(page, {}).get("starts_document"))

    def score(self, pages: list[str]) -> list[dict[str, Any]]:
        """The full-sequence grouping — the loop score_boundaries runs over
        the scorer's evidence (see score_boundaries for the rules)."""
        documents: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        # the pages already claimed by a duplex pair — a page is the two sides
        # of at most ONE sheet, so the greedy pair never pairs again with its
        # other neighbour ([back1, front1, back2]: front1 pairs with back1,
        # never with back2)
        claimed: set[str] = set()
        prev: str | None = None
        for page in pages:
            kind = str(self._kinds.get(page, "text"))
            if current is None:
                current = self._open_document(documents, page)
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
                    current["pages"].insert(0, page)
                else:
                    current["pages"].append(page)
                self._carry(current, page)
            elif kind == "text" and prev_kind == "text":
                if self._text_pair_decision(prev, page):
                    current["pages"].append(page)
                else:
                    current = self._open_document(documents, page)
                self._carry(current, page)
            else:
                # a light page after a text page of a different paper, or two
                # light pages — no cue: it starts its own document
                current = self._open_document(documents, page)
            prev = page
        return documents


def score_boundaries(
    pages: list[str],
    kinds: dict[str, str],
    dims: dict[str, tuple[int, int]],
    texts: dict[str, str | None],
    flags: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group the FULL page sequence (photos included, in scan order) into
    documents by the evidence hierarchy. Returns the boundaries list —
    the same shape the guess stage publishes. ``flags`` is the model's
    per-page boundary report (text pages only); ``dims`` the image
    sizes; ``texts`` the corrected page text (None for photos)."""
    return GroupingScorer(kinds, dims, texts, flags).score(pages)
