"""The review-posted gate's contract: the head commit counts as reviewed
ONLY when an output artifact exists — a completed "PR Agent - Review"
check run, or a guide/skip comment covering the commit. Nothing else:
the action exits 0 whether or not the review happened (PRAgent.
handle_request swallows every exception), so a gate that trusts the
bot's own word re-introduces the exact bug it exists to catch."""

import os
import subprocess
import sys
from pathlib import Path

from pipeline.evals import check_review_posted as gate

_SHA = "abc123"
_COMMIT = {"commit": {"committer": {"date": "2026-09-05T10:00:00Z"}}}
_GUIDE = {"body": "## Incremental PR Reviewer Guide 🔍", "created_at": "2026-09-05T10:05:00Z"}


def _gate(responses: dict, failure_reason=None, fetch_hook=None) -> int:
    """fetch_hook validates the outgoing URL before delegating to the
    scripted responses — the gate's URL construction is part of the
    contract (2026-09-06: a placeholder repo in the check-run query 404'd
    in production and every pr-review crashed)."""
    """The gate with an injected fetch and a stubbed failure-reason read —
    the repo's DI convention (fakes are objects/functions passed in, the
    global environment never touched). The poll delay is zeroed: a test
    never sleeps on wall-clock time (docs/testing-standards.md)."""
    env = {
        "SHA": _SHA,
        "GITHUB_REPOSITORY": "org/repo",
        "PR_NUMBER": "7",
        "GITHUB_TOKEN": "t",
    }

    def fetch(url: str, token: str):
        if fetch_hook:
            fetch_hook(url)
        for fragment, payload in responses.items():
            if fragment in url:
                return payload
        raise AssertionError(f"unexpected URL: {url}")

    return gate.run_review_gate(fetch, env, failure_reason=failure_reason, poll_delay_s=0.0)


def _review_check(status: str) -> dict:
    return {"name": "PR Agent - Review", "status": status, "conclusion": "neutral"}


def test_completed_review_check_run_covers_the_head() -> None:
    """The artifact path: the bot published its review as a check —
    covered even when the comment trail is empty. The query must target
    the actual repo."""
    seen: list[str] = []

    def hook(url: str) -> None:
        seen.append(url)

    assert (
        _gate(
            {
                "/commits/abc123/check-runs": {"check_runs": [_review_check("completed")]},
            },
            fetch_hook=hook,
        )
        == 0
    )
    assert any("repos/org/repo/commits/abc123/check-runs" in u for u in seen), seen


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


def test_comments_fetch_filters_since_the_head_commit() -> None:
    """The comments fetch carries the since filter and a wide page: the
    guide for the head commit must be server-side visible regardless of
    how many older comments the PR carries."""
    seen: list[str] = []

    def fetch(url: str, token: str):
        seen.append(url)
        if "check-runs" in url:
            return {"check_runs": []}
        if "/commits/" in url:
            return {"commit": {"committer": {"date": "2026-09-06T06:45:58Z"}}}
        if "comments" in url:
            return []
        raise AssertionError(url)

    env = {"SHA": _SHA, "GITHUB_REPOSITORY": "org/repo", "PR_NUMBER": "7", "GITHUB_TOKEN": "t"}
    gate.run_review_gate(fetch, env, failure_reason=lambda *a: "x", poll_attempts=1)
    comments_calls = [u for u in seen if "comments" in u]
    assert comments_calls, "the gate never fetched the comments"
    assert "since=" in comments_calls[0] and "per_page=100" in comments_calls[0]


def test_poll_catches_a_review_that_lands_moments_later() -> None:
    """The gate races the bot's publish: the guide posts at the very end
    of the bot step and the comments API lags it by seconds. The poll
    must re-fetch — a review that lands during the window is coverage,
    not a failure."""
    state = {"calls": 0}

    def fetch(url: str, token: str):
        state["calls"] += 1
        if "comments" in url:
            if state["calls"] > 1:
                return [_GUIDE]
            return []
        if "check-runs" in url:
            return {"check_runs": []}
        return _COMMIT

    env = {"SHA": _SHA, "GITHUB_REPOSITORY": "org/repo", "PR_NUMBER": "7", "GITHUB_TOKEN": "t"}
    code = gate.run_review_gate(fetch, env, failure_reason=lambda *a: "unused", poll_delay_s=0.0)
    assert code == 0
    assert state["calls"] >= 2


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


def test_the_real_client_honours_the_fetch_seam() -> None:
    """``run_review_gate`` calls ``fetch(url, token)`` and ``main`` passes
    the real client's bound method: the client must accept that shape. It
    took one argument, so the gate crashed with TypeError before its first
    API call — every pr-review run failed at the checker step, and the
    injected-fetch tests could not see it (2026-10-17)."""
    seen: list[str] = []

    def open_url(req) -> bytes:
        seen.append(req.headers["Authorization"])
        return b'{"ok": true}'

    client = gate._GitHub("instance-token", open_url=open_url)
    assert client.get_json("https://example.invalid/x", "caller-token") == {"ok": True}
    assert client.get_json("https://example.invalid/x") == {"ok": True}
    assert seen == ["Bearer caller-token", "Bearer instance-token"]


def test_the_gate_imports_when_run_as_ci_runs_it() -> None:
    """CI invokes the gate as a FILE — `.github/workflows/pr-agent.yml`:
    `python3 pipeline/evals/check_review_posted.py` — so `sys.path[0]` is the
    script's own directory, never the repo root, and the package import needs
    the root on the path (2026-10-21: without it the gate died with
    ModuleNotFoundError before reading a comment, and every PR's review check
    went red for a reason unrelated to the review — the injected-fetch tests
    above cannot see it). The CI variables are unset, so the gate stops at its
    own `KeyError` line: reaching that line is the assertion. No network."""
    root = Path(__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items() if k not in ("SHA", "GITHUB_REPOSITORY", "PR_NUMBER")}
    result = subprocess.run(
        [sys.executable, "pipeline/evals/check_review_posted.py"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert "ModuleNotFoundError" not in result.stderr, result.stderr
    assert "KeyError" in result.stderr, result.stderr  # the gate's first line, reached
