"""The identity migration's status and date mapping (TECHSPEC/11 §What maps).

The old record status is a *disposition* plus the basis and confidence it was
held with: `confirmed` was knowledge, `estimated` was a recollection, and a
proposal stays a proposal. The old `date`/`date2`/`date_precision` triple
becomes the structured `DateValue` (§18.4); the flat columns stay derived.
"""

from __future__ import annotations

from typing import Any

Basis = dict[str, str]


class BasisKinds:
    """The two basis/confidence pairs the migration assigns, and the evidence
    fields a reviewer's own words ride in."""

    KNOWN: Basis = {"basis": "knowledge", "confidence": "certain"}
    RECOLLECTED: Basis = {"basis": "recollection", "confidence": "possible"}
    EVIDENCE: tuple[str, ...] = ("text", "by", "when", "note")


def renders_estimated(basis: dict[str, str] | None) -> bool:
    """Is this basis rendered as the old ``estimated`` status? A confirmed
    record whose basis is recollection/inference below certainty is
    (TECHSPEC/05 §18.2)."""
    return bool(basis) and basis.get("basis") in ("recollection", "inference") and basis.get("confidence") != "certain"


def basis_after(existing: dict[str, str] | None, disposition: Basis, stated: dict[str, str] | None = None) -> Basis:
    """The basis after a determination: the disposition's basis/confidence,
    with the reviewer's own words (or the record's evidence) alongside."""
    fields = BasisKinds.EVIDENCE
    evidence = {key: value for key, value in (existing or {}).items() if key in fields}
    evidence.update({key: value for key, value in (stated or {}).items() if key in fields})
    return {**disposition, **evidence}


def disposition_of(status: str | None, basis: dict[str, str] | None = None) -> tuple[str, Basis]:
    """The new disposition and basis for an identity record's old status.

    A missing status is an asserted edge/record (confirmed by knowledge); an
    old `estimated` becomes confirmed-with-recollection and keeps the
    reviewer's own text/by/when in the basis.
    """
    if status == "estimated":
        out = dict(BasisKinds.RECOLLECTED)
        for key, value in (basis or {}).items():
            out.setdefault(key, value)
        return "confirmed", out
    if status == "proposed":
        return "proposed", dict(basis) if basis else dict(BasisKinds.RECOLLECTED)
    if status == "rejected":
        return "rejected", dict(basis) if basis else dict(BasisKinds.KNOWN)
    return "confirmed", dict(basis) if basis else dict(BasisKinds.KNOWN)


def _parts(date: str) -> dict[str, int]:
    """The year/month/day parts of an ISO date, as far as it goes."""
    text = str(date).strip()
    parts: dict[str, int] = {}
    if len(text) >= 4 and text[:4].isdigit():
        parts["year"] = int(text[:4])
    if len(text) >= 7 and text[5:7].isdigit() and text[4] == "-":
        parts["month"] = int(text[5:7])
    if len(text) >= 10 and text[8:10].isdigit() and text[7] == "-":
        parts["day"] = int(text[8:10])
    return parts


def _stated_parts(date: str, precision: str) -> dict[str, int]:
    """The parts the precision actually states (a year keeps no month/day)."""
    parts = _parts(date)
    if precision == "year":
        return {"year": parts["year"]} if "year" in parts else {}
    if precision == "month":
        return {key: parts[key] for key in ("year", "month") if key in parts}
    return parts


def date_value(date: str, precision: str, date2: str | None = None, *, phrase: str | None = None) -> dict[str, Any]:
    """The structured DateValue for an old date/precision pair."""
    value: dict[str, Any] = {
        "calendar": "gregorian",
        "type": "date",
        "qualifier": None,
        "range": None,
        "from": _stated_parts(date, precision) if date else None,
        "to": _parts(date2) if date2 else None,
        "phrase": phrase,
    }
    if precision == "approx":
        value["qualifier"] = "about"
    elif precision == "estimated":
        value["qualifier"] = "estimated"
    elif precision == "before":
        value.update({"type": "range", "range": "before", "from": None, "to": _parts(date)})
    elif precision == "after":
        value.update({"type": "range", "range": "after", "from": _parts(date), "to": None})
    elif precision == "between":
        value.update({"type": "range", "range": "between"})
    elif precision == "period":
        value.update({"type": "period"})
    return value
