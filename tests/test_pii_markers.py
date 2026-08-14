"""The no-PII matcher's own contract — the shared per-file scan, including the
case semantics the fast path relies on (2026-08-14, review: the guard's fast
path compared original-case email markers against lowercased text, so an
uppercase email marker silently bypassed the per-marker scan).
"""

from __future__ import annotations

from tools.pii_markers import file_offenders


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


def test_multiple_markers_reported_in_input_order() -> None:
    assert file_offenders("Nora Voss — n.voss@post.de", {"n.voss@post.de", "Voss", "Mum"}) == [
        "n.voss@post.de",
        "Voss",
    ]


def test_no_markers_is_empty() -> None:
    assert file_offenders("plain text, no names", set()) == []
