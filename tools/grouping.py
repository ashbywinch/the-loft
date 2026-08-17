"""The document grouping scorer (TECH-SPEC §16.14, 2026-08-17).

The guess's model flags (greeting/sign-off boundaries) decide text-only
grouping; the scorer adds the physical evidence the model never sees —
the full page sequence (photo pages included), the paper sizes, and the
page numbers. Evidence priority (user, 2026-08-17):

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

# The paper-size tolerance for phone scans: the SAME physical sheet
# photographed twice differs in pixel dims (distance, crop — the
# postcard's two sides measure 3500x2215 and 2333x3500, 2026-08-17), so
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
    size, 2026-08-17)."""
    pa, pb = paper_aspect(*a), paper_aspect(*b)
    return abs(pa - pb) / max(min(pa, pb), 1e-9) <= tolerance


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


def _new_document(page: str, flags: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Open a document at ``page`` — the model's greeting when this page
    carries the starts_document flag (a photo page never does)."""
    flag = flags.get(page, {})
    return {
        "pages": [page],
        "greeting": flag.get("greeting") if flag.get("starts_document") else None,
        "signoff": None,
    }


def _carry(doc: dict[str, Any], page: str, flags: dict[str, dict[str, Any]]) -> None:
    """Carry the model's greeting/sign-off into the doc when a joined page
    has them — the duplex doc opens with the picture side (no flag), and
    the text side's model values belong to the doc (2026-08-17)."""
    flag = flags.get(page, {})
    if doc.get("greeting") is None and flag.get("greeting"):
        doc["greeting"] = flag["greeting"]
    if flag.get("ends_document") and flag.get("signoff"):
        doc["signoff"] = flag["signoff"]


def _text_pair_decision(
    prev: str,
    page: str,
    dims: dict[str, tuple[int, int]],
    texts: dict[str, str | None],
    flags: dict[str, dict[str, Any]],
) -> bool:
    """The text-text rules for an adjacent pair — "join" (True, same
    document) or "split" (False, a new document at ``page``), in the
    2026-08-17 priority order: paper size, then page numbers, then the
    model's greeting/sign-off flags."""
    if not same_paper(dims[prev], dims[page]):
        return False  # 2. different papers are not the same document
    n = first_page_number(texts.get(page))
    if n is not None:
        # 3. page numbers outvote the model flags: a numbered
        # continuation joins, a fresh "1" starts a new document
        return n != 1
    # 4. the model's greeting/sign-off flags
    return not (flags.get(prev, {}).get("ends_document") or flags.get(page, {}).get("starts_document"))


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
    documents: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    # the pages already claimed by a duplex pair — a page is the two sides
    # of at most ONE sheet, so the greedy pair never pairs again with its
    # other neighbour ([back1, front1, back2]: front1 pairs with back1,
    # never with back2)
    claimed: set[str] = set()
    prev: str | None = None
    for page in pages:
        kind = str(kinds.get(page, "text"))
        if current is None:
            current = _new_document(page, flags)
            documents.append(current)
            prev = page
            continue
        assert prev is not None  # the first iteration set it — pyrefly's narrowing needs the explicit fact
        prev_kind = str(kinds.get(prev, "text"))
        # 1. the duplex cue (strongest): one light side + one text side,
        # the same paper — the two sides of one sheet, same document.
        if (
            _is_light(kind) != _is_light(prev_kind)
            and same_paper(dims[prev], dims[page])
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
            _carry(current, page, flags)
            prev = page
            continue
        if kind == "text" and prev_kind == "text":
            if _text_pair_decision(prev, page, dims, texts, flags):
                current["pages"].append(page)
            else:
                current = _new_document(page, flags)
                documents.append(current)
            _carry(current, page, flags)
            prev = page
            continue
        # a light page after a text page of a different paper, or two
        # light pages — no cue: it starts its own document
        current = _new_document(page, flags)
        documents.append(current)
        prev = page
    return documents
