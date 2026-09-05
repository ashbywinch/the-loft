"""Called by .github/workflows/pr-agent.yml — fail the PR if the review bot
did not produce a review covering the head commit. The review may have
failed silently; this check prevents merging unreviewed.

Coverage, in order: a COMPLETED "PR Agent - Review" check run on the head
SHA — the output artifact the bot publishes only with the review text in
hand (github.publish_as_check_run; v0.41.1 _publish_check_run) — then the
comment trail below. The bot's own step conclusion is NEVER trusted: as
the 2026-08-11 v0.41.1 reading found (and the 2026-09-04 401 incident
confirmed in the wild), the action exits 0 whether or not the review
happened, so a green step claims nothing about a review existing.

A comment covers the head commit when its body references the commit's SHA
(the incremental-review form, "Starting from commit .../<SHA>") or it was
posted after the head commit landed (the first review on a PR is posted
without the SHA marker — observed: pr-agent v0.41.1 regular reviews never
contain the head SHA).

Why the bot's own step cannot fail (2026-08-11, read from the v0.41.1
source): ``PRAgent.handle_request`` catches EVERY exception with a bare
``except`` — it logs "Failed to process the command." plus the traceback
and returns False — and ``github_action_runner.py`` discards that return
value, so the action exits 0 whether or not the review happened. A green
bot step is therefore meaningless, and the only truthful signal is this
check. To make the failure SELF-EXPLAINING rather than a guess, the check
fetches the run's own log (the checks API) and extracts the bot's error
lines: the "Failed to process the command." traceback, model/API errors,
and the diff-token-cap marker — the check's failure message names the
reason instead of "may have failed silently".
"""

import http
import json
import os
import re
import sys
import urllib.request
from urllib.error import HTTPError

BOT_STEP_MARK = "Run the-pr-agent/pr-agent"

# The markers the bot leaves when a review dies inside the (swallowed)
# exception seam, plus the size signal that precedes a died model call.
_ERROR_MARKERS = (
    "Failed to process the command.",
    "Traceback (most recent call last)",
)
_SIZE_RE = re.compile(r"Tokens:\s*(\d+),\s*total tokens over limit:\s*(\d+)")
_TRACEBACK_TAIL = 12  # lines after a traceback/marker worth reporting


def _get(url: str, token: str, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": accept},
    )
    return urllib.request.urlopen(req).read()


def _get_json(url: str, token: str):
    return json.loads(_get(url, token))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The log endpoint 302s to a signed blob URL; urllib's auto-follow
    forwards the Authorization header onto the blob host, which rejects it
    (401 InvalidAuthenticationInfo, 2026-08-11). Stop at the 302 and fetch
    the signed Location bare."""

    @staticmethod
    # lucidlint: ignore long-param-list the urllib HTTPRedirectHandler protocol fixes this signature
    def redirect_request(req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _job_log(repo: str, token: str) -> str | None:
    """The running job's own accumulated log (the bot step's output), or
    None when the checks API won't serve it mid-run — the caller falls back
    to the generic message. Requires the workflow's ``actions: read``."""
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        return None
    try:
        jobs = _get_json(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs", token)
        if not jobs.get("jobs"):
            return None
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/jobs/{jobs['jobs'][0]['id']}/logs",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        try:
            return _OPENER.open(req).read().decode("utf-8", errors="replace")
        except HTTPError as e:
            if e.code != http.HTTPStatus.FOUND:
                raise
            return urllib.request.urlopen(e.headers["Location"]).read().decode("utf-8", errors="replace")
    except (HTTPError, KeyError, ValueError):
        return None


def _completed_review_check_run(fetch, sha: str) -> bool:
    """Is there a COMPLETED "PR Agent - Review" check run on the head
    commit? The bot creates it ONLY with the review output text in hand
    (github_provider._publish_check_run in v0.41.1: called from
    publish_persistent_comment with the review text; a failed or skipped
    review produces no check). It is the output artifact, not the step's
    self-reported success — the 2026-09-04 401 incident ran the action to
    completion while producing nothing, so a step-conclusion gate would
    have passed a review that never happened. (User, 2026-09-05: "isn't
    this re-introducing our original bug where it just claims it's
    successful even when it's not?".) The conclusion is always "neutral"
    in v0.41.1; completed-neutral means the review text was published."""
    try:
        runs = fetch(f"https://api.github.com/repos/x/y/commits/{sha}/check-runs", "")
        return any(
            r.get("name") == "PR Agent - Review" and r.get("status") == "completed" for r in runs.get("check_runs", [])
        )
    except (KeyError, ValueError, AttributeError):
        return False


def _bot_failure_reason(repo: str, token: str) -> str:
    """The bot's own words about its failure, from the run log — the reason
    the review died, instead of a guess. Falls back to the last thing the
    bot said."""
    log = _job_log(repo, token)
    if log is None:
        return "the bot's log could not be read from the checks API"
    # The raw job blob is TIMESTAMPZ + message lines with no step prefixes
    # (the runner's processed view adds them); the bot's own records are the
    # structured JSON lines with a "text" field — those carry the markers.
    bot_lines = [ln for ln in log.splitlines() if '"text"' in ln]
    if not bot_lines:
        return "the bot's step produced no log output"
    reason = _size_reason(bot_lines) or _error_marker_reason(bot_lines)
    if reason:
        return reason
    # no markers — say where the bot's output stopped
    last = next((line for line in reversed(bot_lines) if line.strip()), "")
    return f"the bot's last output before going silent: {last.split('\t')[-1][:200]}"


def _size_reason(bot_lines: list[str]) -> str | None:
    """The size signal first — a review that died right after pruning is a
    PR that outgrew the bot's review budget (2026-08-11: the model call
    produced nothing immediately after "Tokens: 144757 ... pruning diff")."""
    for ln in bot_lines:
        m = _SIZE_RE.search(ln)
        if m:
            return (
                f"the PR's cumulative diff is {m.group(1)} tokens — over the bot's "
                f"{m.group(2)}-token review cap; the review died after pruning the diff"
            )
    return None


def _error_marker_reason(bot_lines: list[str]) -> str | None:
    """The swallowed-exception seam: the traceback the bot logged and hid."""
    for i, ln in enumerate(bot_lines):
        if any(mark in ln for mark in _ERROR_MARKERS):
            tail = [line for line in bot_lines[i : i + _TRACEBACK_TAIL] if line.strip()]
            snippet = " | ".join(line.split("\t")[-1][:200] for line in tail[:4])
            return f"the bot logged an error before dying: {snippet}"
    return None


def _completed_review_check_run(fetch, sha: str) -> bool:
    """Is there a COMPLETED "PR Agent - Review" check run on the head
    commit? The bot creates it ONLY with the review output text in hand
    (github_provider._publish_check_run in v0.41.1: called from
    publish_persistent_comment with the review text; a failed or skipped
    review produces no check). It is the output artifact, not the step's
    self-reported success — the 2026-09-04 401 incident ran the action to
    completion while producing nothing, so a step-conclusion gate would
    have passed a review that never happened. (User, 2026-09-05: "isn't
    this re-introducing our original bug where it just claims it's
    successful even when it's not?".) The conclusion is always "neutral"
    in v0.41.1; completed-neutral means the review text was published."""
    try:
        runs = fetch(f"https://api.github.com/repos/x/y/commits/{sha}/check-runs", "")
        return any(
            r.get("name") == "PR Agent - Review" and r.get("status") == "completed" for r in runs.get("check_runs", [])
        )
    except (KeyError, ValueError, AttributeError):
        return False


def run_review_gate(fetch, env, failure_reason=None) -> int:
    """The gate as a pure function: ``fetch(url, token)`` -> parsed JSON,
    ``env`` the CI environment mapping, ``failure_reason(repo, token)``
    the bot's own words about a death. Testable by injection — the repo's
    DI convention; never monkeypatch."""
    sha = env["SHA"]
    repo = env["GITHUB_REPOSITORY"]
    pr_number = env["PR_NUMBER"]
    token = env["GITHUB_TOKEN"]

    # The authoritative coverage signal: a COMPLETED "PR Agent - Review"
    # check run on the head commit — the artifact the bot publishes only
    # with the review text in hand (2026-09-05, enabled via
    # github.publish_as_check_run). The comment trail below remains the
    # fallback for runs from before the check was enabled and for the
    # incremental skip that posts a comment.
    if _completed_review_check_run(fetch, sha):
        return 0

    commit = fetch(f"https://api.github.com/repos/{repo}/commits/{sha}", token)
    head_committed_at = commit["commit"]["committer"]["date"]

    comments = fetch(f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments", token)
    # the review posts with the regular header ("## PR Reviewer Guide") or
    # the incremental form ("## Incremental PR Reviewer Guide" — the -i
    # path, 2026-08-11: the first incremental run posted exactly that and
    # the check missed it, failing a review that had succeeded). A skip
    # comment ("Incremental Review Skipped / No files were changed") is
    # also coverage: the bot assessed the head commit and decided nothing
    # needed review — the restacked-branch force-pushes kept tripping the
    # gate on exactly that (2026-09-04, PRs 32/33).
    covered = any(
        (
            c.get("body", "").startswith(("## PR Reviewer Guide", "## Incremental PR Reviewer Guide"))
            or c.get("body", "").startswith("Incremental Review Skipped")
        )
        and (sha in c.get("body", "") or c.get("created_at", "") >= head_committed_at)
        for c in comments
    )
    if not covered:
        reason = (failure_reason or _bot_failure_reason)(repo, token)
        print(f"::error::AI review did not post for commit {sha} — {reason}.")
        return 1
    return 0


def main() -> int:
    return run_review_gate(_get_json, os.environ)


if __name__ == "__main__":
    sys.exit(main())
