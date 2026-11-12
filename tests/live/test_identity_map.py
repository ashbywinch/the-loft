"""A3 — the identity migration's status and date mapping (TECHSPEC/11 §What maps)."""

from __future__ import annotations

from loft.live.identity_map import date_value, disposition_of


def test_confirmed_is_knowledge_certain() -> None:
    assert disposition_of("confirmed") == ("confirmed", {"basis": "knowledge", "confidence": "certain"})
    assert disposition_of(None) == ("confirmed", {"basis": "knowledge", "confidence": "certain"})


def test_estimated_is_confirmed_recollection_and_keeps_its_basis() -> None:
    status, basis = disposition_of("estimated", {"text": "Aunt Nora's memory", "by": "Nora", "when": "2026"})
    assert status == "confirmed"
    assert basis["basis"] == "recollection"
    assert basis["confidence"] == "possible"
    assert basis["text"] == "Aunt Nora's memory"
    assert basis["by"] == "Nora"


def test_proposed_stays_proposed() -> None:
    assert disposition_of("proposed")[0] == "proposed"


def test_exact_date_is_a_dated_value_with_parts() -> None:
    value = date_value("1963-05-14", "exact")
    assert value["type"] == "date"
    assert value["from"] == {"year": 1963, "month": 5, "day": 14}
    assert value["qualifier"] is None


def test_month_and_year_keep_the_parts_they_have() -> None:
    assert date_value("1963-05-01", "month")["from"] == {"year": 1963, "month": 5}
    assert date_value("1963-01-01", "year")["from"] == {"year": 1963}


def test_approx_is_about_and_bounds_are_ranges() -> None:
    assert date_value("1963-05-14", "approx")["qualifier"] == "about"
    before = date_value("1963-05-14", "before")
    assert (before["type"], before["range"], before["from"], before["to"]) == (
        "range",
        "before",
        None,
        {"year": 1963, "month": 5, "day": 14},
    )
    after = date_value("1963-05-14", "after")
    assert (after["range"], after["from"], after["to"]) == ("after", {"year": 1963, "month": 5, "day": 14}, None)
    between = date_value("1963-05-14", "between", "1964-01-02")
    assert between["range"] == "between"
    assert between["to"] == {"year": 1964, "month": 1, "day": 2}


def test_period_and_phrase() -> None:
    assert date_value("1963", "period")["type"] == "period"
    assert date_value("1963", "exact", phrase="the summer of 1963")["phrase"] == "the summer of 1963"
