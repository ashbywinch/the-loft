"""Tests for the placeholder engine (tools/placeholders.py): the stand-in
SVG for a missing scan is family-agnostic — the shape follows the item's
type, the label comes from the item's own data (``demo`` for fictional
stand-in text, else the title). Never from the item's id (2026-08-05: the
engine once branched on the real family's artifact ids, baking attested and
unattested content into code)."""

from __future__ import annotations

from typing import Any

from tools.placeholders import asset_svg


def _item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": "object-anything",
        "type": "object",
        "title": "The widget",
        "date": "1980",
        "assets": [],
    }
    item.update(overrides)
    return item


def test_demo_label_wins_over_title() -> None:
    """A ``demo`` label is the fictional stand-in text — it renders, and the
    title does not (the label marks content that is not attested)."""
    svg = asset_svg(_item(demo="A widget", title="The widget"), "w.svg")
    assert "A widget" in svg
    assert "The widget" not in svg


def test_no_demo_falls_back_to_title() -> None:
    """Without a ``demo`` label the item's own title is the honest stand-in
    label — real content, never a hardcoded family label."""
    svg = asset_svg(_item(title="The widget"), "w.svg")
    assert "The widget" in svg


def test_engine_never_branches_on_an_id() -> None:
    """The old id-gated branches (object-the-yard -> "The boatyard",
    photo-giraffes -> "Slides: giraffes") are gone: a fabricated item
    bearing those ids renders its own data, not a hardcoded label."""
    yard = asset_svg(_item(id="object-the-yard", title="The yard"), "y.svg")
    assert "The yard" in yard
    assert "boatyard" not in yard.lower()
    giraffes = asset_svg(_item(id="photo-giraffes", type="photo", title="The giraffes"), "g.svg")
    assert "The giraffes" in giraffes
    assert "giraffes" not in giraffes.lower().replace("the giraffes", "")


def test_label_with_xml_special_characters_is_escaped() -> None:
    """Publish generates placeholders for real archive items, so a title
    containing & < or " must not produce malformed SVG (2026-08-05 review,
    importance 6)."""
    svg = asset_svg(_item(title='Boat & "Sparrow" <the>'), "w.svg")
    assert "&amp;" in svg and "&lt;" in svg and "&quot;" in svg
    assert 'Boat & "Sparrow" <the>' not in svg  # raw characters never reach the SVG
    import xml.etree.ElementTree as ET

    ET.fromstring(svg)  # parses as well-formed XML


def test_letter_asset_not_named_page_falls_back_to_page_one() -> None:
    """A letter asset that isn't page-N (an envelope, a back) must not
    abort the whole publish with an IndexError (2026-08-05 review,
    importance 5)."""
    svg = asset_svg(_item(id="letter-a", type="letter", assets=[{"file": "envelope.jpg"}]), "envelope.jpg")
    assert "1 / 1" in svg
