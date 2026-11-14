"""The review-posted gate's contract: the head commit counts as reviewed
ONLY when the bot's own output artifact exists — a completed "PR Agent -
Review" check run on that SHA. Nothing else: the action exits 0 whether or
not the review happened (PRAgent.handle_request swallows every exception),
and a comment (a guide, a skip) carries no record of which head it reviewed,
so a gate that trusts one re-introduces the exact bug it exists to catch."""

import os
import subprocess
import sys
from pathlib import Path

from pipeline.evals import check_review_posted as gate

_SHA = "abc123"


def _gate(responses: dict, failure_reason=None, fetch_hook=None) -> int:
    """The gate with an injected fetch and a stubbed failure-reason read —
    the repo's DI convention (fakes are objects/functions passed in, the
    global environment never touched). The fetch_hook validates the outgoing
    URL before delegating to the scripted responses: the gate's URL
    construction is part of the contract (2026-09-06: a placeholder repo in
    the check-run query 404'd in production and every pr-review crashed)."""
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

    return gate.run_review_gate(fetch, env, failure_reason=failure_reason)


def _review_check(status: str, name: str = "PR Agent - Review") -> dict:
    return {"name": name, "status": status, "conclusion": "neutral"}


def test_completed_review_check_run_covers_the_head() -> None:
    """The artifact path: the bot published its review as a check — covered.
    The query must target the actual repo."""
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
        {"/commits/abc123/check-runs": {"check_runs": [_review_check("in_progress")]}},
        failure_reason=reason,
    )
    assert code == 1
    assert reasons == ["the review died before publishing"]


def test_a_completed_check_run_of_another_name_is_not_coverage() -> None:
    """CI's own checks (build-and-test, verify) complete on every push; only
    the bot's review check is the artifact."""
    assert (
        _gate(
            {
                "/commits/abc123/check-runs": {
                    "check_runs": [
                        _review_check("completed", name="build-and-test"),
                        _review_check("completed", name="verify"),
                    ]
                },
            },
            failure_reason=lambda *a: "no review check run",
        )
        == 1
    )


def test_a_guide_comment_alone_does_not_cover_the_head() -> None:
    """The cancelled-run case: a run posts its guide and dies. The comment
    looks like a review, carries no reviewed SHA, and is not coverage — the
    gate reads the check run only."""
    assert (
        _gate(
            {"/commits/abc123/check-runs": {"check_runs": []}},
            failure_reason=lambda *a: "the run was cancelled",
        )
        == 1
    )


def test_no_artifact_fails_loud(capsys) -> None:
    """The bot ran and produced nothing — the gate must fail, not pass on
    the action's word (the original bug: a green step claims nothing)."""

    def reason(repo: str, token: str) -> str:
        return "the bot's log could not be read from the checks API"

    code = _gate({"/commits/abc123/check-runs": {"check_runs": []}}, failure_reason=reason)
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
    assert "KeyError" in result.stderr, result.stderr[-2000:]
    assert "ModuleNotFoundError" not in result.stderr
