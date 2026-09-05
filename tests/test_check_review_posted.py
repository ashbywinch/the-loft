"""The review-posted gate's contract: the head commit counts as reviewed
ONLY when an output artifact exists — a completed "PR Agent - Review"
check run, or a guide/skip comment covering the commit. Nothing else:
the action exits 0 whether or not the review happened (v0.41.1
PRAgent.handle_request swallows every exception; the 2026-09-04 401
incident ran to completion producing nothing), so a gate that trusts the
bot's own word re-introduces the exact bug it exists to catch."""

from tools import check_review_posted as gate

_SHA = "abc123"
_COMMIT = {"commit": {"committer": {"date": "2026-09-05T10:00:00Z"}}}
_GUIDE = {"body": "## Incremental PR Reviewer Guide 🔍", "created_at": "2026-09-05T10:05:00Z"}


def _gate(responses: dict, failure_reason=None) -> int:
    """The gate with an injected fetch and a stubbed failure-reason read —
    the repo's DI convention (fakes are objects/functions passed in, the
    global environment never touched)."""
    env = {
        "SHA": _SHA,
        "GITHUB_REPOSITORY": "org/repo",
        "PR_NUMBER": "7",
        "GITHUB_TOKEN": "t",
    }

    def fetch(url: str, token: str):
        for fragment, payload in responses.items():
            if fragment in url:
                return payload
        raise AssertionError(f"unexpected URL: {url}")

    return gate.run_review_gate(fetch, env, failure_reason=failure_reason)


def _review_check(status: str) -> dict:
    return {"name": "PR Agent - Review", "status": status, "conclusion": "neutral"}


def test_completed_review_check_run_covers_the_head() -> None:
    """The artifact path: the bot published its review as a check —
    covered even when the comment trail is empty."""
    assert (
        _gate(
            {
                "/commits/abc123/check-runs": {"check_runs": [_review_check("completed")]},
            }
        )
        == 0
    )


def test_in_progress_check_run_is_not_coverage() -> None:
    """A check that never completed means the review never produced its
    verdict — the gate fails loud; the reason names the bot, not a guess."""
    reasons: list[str] = []

    def reason(repo: str, token: str) -> str:
        reasons.append("the review died before publishing")
        return reasons[-1]

    code = _gate(
        {
            "/commits/abc123/check-runs": {"check_runs": [_review_check("in_progress")]},
            "/commits/abc123": _COMMIT,
            "/issues/7/comments": [],
        },
        failure_reason=reason,
    )
    assert code == 1
    assert reasons == ["the review died before publishing"]


def test_comment_covering_the_head_is_coverage() -> None:
    """The fallback path: no check run (the configs before
    publish_as_check_run), but a guide comment posted after the head
    commit landed."""
    assert (
        _gate(
            {
                "/commits/abc123/check-runs": {"check_runs": []},
                "/commits/abc123": _COMMIT,
                "/issues/7/comments": [_GUIDE],
            }
        )
        == 0
    )


def test_silent_skip_is_still_coverage_via_the_comment() -> None:
    """The incremental review's silent decision to skip — nothing new to
    read — is coverage when it says so: the bot assessed the head and
    concluded the existing review holds."""
    skip = {
        "body": "Incremental Review Skipped\nNo files were changed since the previous review",
        "created_at": "2026-09-05T10:06:00Z",
    }
    assert (
        _gate(
            {
                "/commits/abc123/check-runs": {"check_runs": []},
                "/commits/abc123": _COMMIT,
                "/issues/7/comments": [skip],
            }
        )
        == 0
    )


def test_no_artifact_and_no_comment_fails_loud(capsys) -> None:
    """The bot ran and produced nothing — the gate must fail, not pass on
    the action's word (the original bug: a green step claims nothing)."""

    def reason(repo: str, token: str) -> str:
        return "the bot's log could not be read from the checks API"

    code = _gate(
        {
            "/commits/abc123/check-runs": {"check_runs": []},
            "/commits/abc123": _COMMIT,
            "/issues/7/comments": [],
        },
        failure_reason=reason,
    )
    assert code == 1
    assert "AI review did not post" in capsys.readouterr().out
