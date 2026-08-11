"""Placeholder content generation — the SVG stand-ins for scans that live
outside the repo (the archive's real images are never committed, AGENTS.md).

Used by ``tools/publish`` (a sidecar references a scan that isn't in the
archive) and by the demo generator (``tools/demo_data``) — one copy of the
placeholder logic, never duplicated. A placeholder is honest: it is visibly a
stand-in (paper, photo frame, object) so a reader never mistakes it for the
artifact. When a real scan lands in the archive, publish copies it instead.
"""

from __future__ import annotations

import html
from typing import Any

FILLS = {
    "amber": "#e8c39a",
    "sage": "#b9c4a4",
    "slate": "#b7c0c9",
    "rose": "#e0b8b0",
    "sky": "#aec9d6",
    "lilac": "#c9bcd6",
}

# A letter asset that isn't page-N (an envelope, a back) — the page parse
# falls back to 1. Named so the except clause needs no parentheses: ruff
# format removes them (`except (A, B):`), which reads like Python 2.
_PAGE_PARSE_ERRORS = (IndexError, ValueError)


def svg_paper(page_no: int, n_pages: int) -> str:
    """A letter page: paper with hand-written-looking lines."""
    lines = "\n".join(
        f'<path d="M24 {40 + i * 22} q {40 + (i % 3) * 10} -6 220 -2" '
        f'stroke="#8a7a63" stroke-width="2.4" fill="none" stroke-linecap="round" opacity="0.55"/>'
        for i in range(11)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 420">
  <rect width="320" height="420" rx="6" fill="#f3ead6"/>
  <rect x="10" y="10" width="300" height="400" rx="4" fill="none" stroke="#d8c9a8"/>
  {lines}
  <text x="24" y="30" font-family="Georgia, serif" font-size="15" fill="#5b4c3a">{page_no} / {n_pages}</text>
</svg>"""


def svg_photo(label: str, hue: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">
  <rect width="400" height="300" rx="8" fill="{FILLS[hue]}"/>
  <rect x="14" y="14" width="372" height="272" rx="6" fill="none" stroke="rgba(90,70,50,.35)"/>
  <circle cx="200" cy="120" r="42" fill="rgba(255,255,255,.5)"/>
  <rect x="120" y="196" width="160" height="14" rx="7" fill="rgba(255,255,255,.65)"/>
  <text x="200" y="252" text-anchor="middle" font-family="Georgia, serif" font-size="17" fill="#4c3d2c">{label}</text>
</svg>"""


def initials_of(name: str) -> str:
    """First initials of the alpha words in a name: 'Marta (Ida)' -> 'P'."""
    words = [w for w in name.split() if w and w[0].isalpha()]
    return "".join(w[0].upper() for w in words[:2]) or "?"


def svg_avatar(initials: str, hue: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <rect width="120" height="120" rx="60" fill="{FILLS[hue]}"/>
  <text x="60" y="72" text-anchor="middle" font-family="Georgia, serif" font-size="34" fill="#4c3d2c">{initials}</text>
</svg>"""


def svg_object(label: str, year: str) -> str:
    """The generic object stand-in — a framed item, never a family-specific
    shape (the boat placeholder went: the app knows artifact TYPES, not the
    family's boats, 2026-08-06)."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
        f'<rect width="400" height="300" rx="12" fill="#b7c0c9"/>'
        f'<rect x="60" y="40" width="280" height="220" rx="6" fill="none" stroke="#fff" stroke-width="4"/>'
        f'<text x="200" y="165" text-anchor="middle" font-family="serif" font-size="22" '
        f'fill="#37424b">{label}</text>'
        f'<text x="200" y="195" text-anchor="middle" font-family="serif" font-size="16" '
        f'fill="#37424b">{html.escape(str(year), quote=True)}</text>'
        "</svg>"
    )


def asset_svg(item: dict[str, Any], filename: str) -> str:
    """The stand-in for one missing asset of *item* — the shape follows the
    item's type, the label comes from the item's own data: a ``demo`` field
    marks stand-in text that is not attested (fictional/demo content), and
    everything else falls back to the item's real title. Never the item's
    id — the engine is family-agnostic (2026-08-05: it once branched on the
    real family's artifact ids, baking content into code)."""
    label = html.escape(str(item.get("demo") or item["title"]), quote=True)
    if item["type"] == "letter":
        try:
            page_no = int(filename.split("-")[1].split(".")[0])
        except _PAGE_PARSE_ERRORS:
            page_no = 1  # non-page letter assets (envelopes, backs) fall back
        return svg_paper(page_no, len(item["assets"]))
    if item["type"] == "object":
        return svg_object(label, item["date"])
    return svg_photo(label, "sky")


class PlaceholderPaper:
    """The paper stand-in for a letter/document page — honest: visibly a
    stand-in, never mistaken for the artifact."""

    @staticmethod
    def svg(page_no: int, n_pages: int) -> str:
        return svg_paper(page_no, n_pages)


class PlaceholderPhoto:
    """The photo-frame stand-in for a missing photo."""

    @staticmethod
    def svg(label: str, hue: str = "sky") -> str:
        return svg_photo(label, hue)


class PlaceholderObject:
    """The generic object stand-in — a framed item. Never a family-specific
    shape: the app knows artifact types, not the family's objects (the boat
    placeholder went for this reason, 2026-08-06)."""

    @staticmethod
    def svg(label: str, year: str) -> str:
        return svg_object(label, year)


class PlaceholderAvatar:
    """The avatar stand-in for a person without a real portrait."""

    @staticmethod
    def svg(initials: str, hue: str) -> str:
        return svg_avatar(initials, hue)


def placeholder_for(item: dict[str, Any], filename: str) -> str:
    """The stand-in class for one missing asset of *item* — the object-model
    dispatch (asset_svg's factory role, named for the family it belongs to)."""
    return asset_svg(item, filename)
