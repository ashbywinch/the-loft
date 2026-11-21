"""Who may read the archive: the family's accounts.

The list is configuration — the repo is data-free, so the addresses live in the
shell environment (`THE_LOFT_FAMILY_MEMBERS`).
"""

from __future__ import annotations

from pipeline.api.members import family_members, is_member
from pipeline.api.session_user import SessionUser


def test_the_family_list_is_the_configured_accounts() -> None:
    """The emails named in THE_LOFT_FAMILY_MEMBERS, casefolded (the archive
    matches people that way); stray spaces and empty entries do not count."""
    assert family_members({"THE_LOFT_FAMILY_MEMBERS": "Aria@Example.com, meg@example.com ,,"}) == frozenset(
        {"aria@example.com", "meg@example.com"}
    )


def test_no_list_means_nobody() -> None:
    """Unset is nobody, never everybody: the private layer must not open
    because an operator forgot a variable. The empty list is injected, not
    read from the environment — a test that read it would pass or fail on
    whatever another suite left behind."""
    assert family_members({}) == frozenset()
    assert is_member(SessionUser("aria@example.com"), frozenset()) is False


def test_a_session_is_family_only_when_the_list_names_it() -> None:
    """Signing in is not being family: the account must be on the list. No
    session is never a member."""
    members = family_members({"THE_LOFT_FAMILY_MEMBERS": "Aria@Example.com"})
    assert is_member(SessionUser("ARIA@example.com"), members) is True
    assert is_member(SessionUser("stranger@example.com"), members) is False
    assert is_member(None, members) is False
