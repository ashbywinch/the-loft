"""The no-PII matcher's own contract — the shared per-file scan, including the
case semantics the fast path relies on.
"""

from __future__ import annotations

from tools.pii_markers import NonFamily, file_offenders


def test_email_marker_matches_lowercase_text() -> None:
    # the case bug: an uppercase email marker must still be found in the
    # lowercased file text the guard scans
    assert file_offenders("Contact: N.Smith@Example.coM via letter", {"N.Smith@Example.coM"}) == ["N.Smith@Example.coM"]


def test_email_marker_absent_when_not_present() -> None:
    assert file_offenders("no identifying email here", {"a.b@example.org"}) == []


def test_word_marker_matches_at_word_boundaries() -> None:
    text = "Ashton sailed aboard the Aurora."
    assert file_offenders(text, {"Ashton"}) == ["Ashton"]
    # a substring ("Ash") must not match inside the word "Ashton"
    assert file_offenders(text, {"Ash"}) == []


def test_multiple_markers_all_reported() -> None:
    # the matcher iterates a set — which markers are found is the contract,
    # not the iteration order (CI's PYTHONHASHSEED differs from local)
    found = file_offenders("Nora Voss — n.voss@post.de", {"n.voss@post.de", "Voss", "Mum"})
    assert sorted(found) == ["Voss", "n.voss@post.de"]


def test_no_markers_is_empty() -> None:
    assert file_offenders("plain text, no names", set()) == []


def test_the_non_family_allowlist_is_deliberate() -> None:
    """The only markers the guard may ignore are the GEDCOM sample's names and
    the library's copyright holder — a new entry is a review finding."""
    assert set(NonFamily.ALLOWED) == {
        "docs/object-model.md",
        "tests/fixtures/maximal70.ged",
        "tests/test_gedcom_document.py",
    }
    markers = {"John", "Family"}
    assert set(file_offenders("John and the Family", markers, "tests/fixtures/maximal70.ged")) == {"Family"}
    assert set(file_offenders("John and the Family", markers)) == {"John", "Family"}
