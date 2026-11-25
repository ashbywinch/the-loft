"""Called by .github/workflows/pr-agent.yml — fail the PR if the review bot
did not post a "PR Reviewer Guide" comment covering the head commit.
The review may have failed silently; this check prevents merging unreviewed.

A comment covers the head commit when its body references the commit's SHA
(the incremental-review form, "Starting from commit .../<SHA>") or it was
posted after the head commit landed (the first review on a PR is posted
without the SHA marker — observed: pr-agent v0.41.1 regular reviews never
contain the head SHA). The range-start SHA in the incremental body is the
first NEW commit, not the head — coverage still falls to the posted-after
rule; the explicit form is belt-and-braces for reviews that embed it.

The bot's own SKIP verdict also covers: an incremental review with no
files changed since the previous review posts "Incremental Review
Skipped" (linking the previous review) instead of a guide. That skip IS
the reviewed verdict — the diff since the last review was examined and
found empty (merging the base branch in, for example, changes nothing in
the PR's diff) — so it covers the commit exactly like the human /skip
opt-out does. A run that genuinely failed to post leaves no comment and
still fails.

A second, silent skip is real too: when the PR has no files the bot can
analyse — a one-file CSV diff, for instance — pr-agent logs "PR has no
analyzable files" and "skipping review" and posts nothing, by design. The
run log is the only witness, so the guard reads it: a clean skip (the
marker with no traceback and no token-cap) passes, and the same log with a
failure marker still fails.

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

import json
import os
import re
import sys
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError

_SIZE_RE = re.compile(r"Tokens:\s*(\d+),\s*total tokens over limit:\s*(\d+)")


class _ApiRequest(urllib.request.Request):
    """A GitHub API request: the two headers every call carries."""

    def __init__(self, url: str, token: str, accept: str = "application/vnd.github+json"):
        super().__init__(url)
        self.add_header("Authorization", f"Bearer {token}")
        self.add_header("Accept", accept)


def _get(url: str, token: str, accept: str = "application/vnd.github+json") -> bytes:
    return urllib.request.urlopen(_ApiRequest(url, token, accept)).read()


class _ApiError(Exception):
    """The API did not give a usable answer: the request failed on the way
    (refused, timed out), it came back non-2xx, or the body is not the JSON it
    promised — a proxy's error page, a truncated read."""


def _get_json(url: str, token: str, get: Callable[[str, str], bytes] = _get):
    """Fetch and parse one API response. The transport is the optional seam
    (the repo's DI convention): tests inject a fake, production uses ``_get``."""
    try:
        body = get(url, token)
    except HTTPError as e:  # a URLError subclass: check it first
        raise _ApiError(f"HTTP {e.code}") from e
    except URLError as e:
        raise _ApiError(f"{e.reason}") from e
    try:
        return json.loads(body)
    except ValueError as e:
        raise _ApiError(f"the body is not JSON ({e})") from e


# The log endpoint 302s to a signed blob URL; urllib's auto-follow forwards
# the Authorization header onto the blob host, which rejects it (401
# InvalidAuthenticationInfo, 2026-08-11). An opener with NO redirect handler
# stops at the 302 — HTTPErrorProcessor hands it to HTTPDefaultErrorHandler,
# which raises HTTPError, and the caller fetches the signed Location bare.
_OPENER = urllib.request.OpenerDirector()
for _handler in (
    urllib.request.HTTPHandler(),
    urllib.request.HTTPSHandler(),
    urllib.request.HTTPErrorProcessor(),
    urllib.request.HTTPDefaultErrorHandler(),
):
    _OPENER.add_handler(_handler)


def _job_name_matches(name: str, wanted: str) -> bool:
    """A reusable workflow's job is listed with its workflow prefix: the job
    called ``pr-review`` appears as ``review / pr-review``. Match the bare name
    and the prefixed form, and nothing else — a prefix is not a wildcard."""
    return name == wanted or name.endswith(f"/ {wanted}")


class _ReviewGate:
    """Review coverage for one repository: what it fetches, and what the bot's
    own log says when a review did not post."""

    def __init__(
        self,
        repo: str,
        token: str,
        get_json: Callable[[str, str], Any] = _get_json,
    ):
        self.repo = repo
        self.token = token
        self.get_json = get_json

    def api(self, path: str):
        """GET a repository-relative API path."""
        return self.get_json(f"https://api.github.com/repos/{self.repo}/{path}", self.token)

    def job_log(self) -> str | None:
        """The running job's own accumulated log (the bot step's output), or
        None when there is no log to read: no run id, no jobs yet, no job by
        that name. A fetch that fails raises, so the caller can say which
        failure it was. Requires the workflow's ``actions: read``."""
        run_id = os.environ.get("GITHUB_RUN_ID")
        if not run_id:
            return None
        jobs = self.api(f"actions/runs/{run_id}/jobs")
        if not jobs.get("jobs"):
            return None
        # The reason we want lives in the REVIEW job's log, not in whichever job
        # the API happens to list first — this runs from a second job in the
        # same run, and listing order is not the workflow's order.
        wanted = os.environ.get("REVIEW_JOB_NAME", "pr-review")
        matches = [j for j in jobs["jobs"] if _job_name_matches(j.get("name", ""), wanted)]
        if not matches:
            return None
        req = _ApiRequest(f"https://api.github.com/repos/{self.repo}/actions/jobs/{matches[0]['id']}/logs", self.token)
        try:
            resp = _OPENER.open(req)
        except HTTPError as e:
            # GitHub answers the log endpoint with a redirect to blob storage, and
            # this opener's error handler is what raises on it — that is how the
            # redirect is stopped from being followed WITH our token. Follow the
            # signed URL ourselves, without it: the target is a third-party host
            # that must never receive a token.
            if e.code not in (301, 302, 303, 307, 308):
                raise
            location = e.headers.get("Location")
            if not location:
                return None
            return urllib.request.urlopen(location, timeout=30).read().decode("utf-8", errors="replace")
        return resp.read().decode("utf-8", errors="replace")


def _bot_failure_reason(log: str | None) -> str:
    """The bot's own words about its failure, from the run log — the reason
    the review died, instead of a guess. Falls back to the last thing the
    bot said."""
    if log is None:
        # the fail-loud step runs inside the bot's OWN job — GitHub does not
        # serve a job's log until the job completes, so the reason extractor
        # can never see it here. Run this check from a SEPARATE job (needs:
        # the bot job) for the real reason; this fallback is the honest
        # admission that the review did not post.
        return "the bot's job log is not served while the job is still running (run this check from a separate job)"
    # The raw job blob is TIMESTAMPZ + message lines with no step prefixes
    # (the runner's processed view adds them); the bot's own records are the
    # structured JSON lines with a "text" field — those carry the markers.
    bot_lines = [ln for ln in log.splitlines() if '"text"' in ln]
    if not bot_lines:
        return "the bot's step produced no log output"

    return _failure_reason(bot_lines)


def _failure_reason(
    bot_lines: list[str],
    markers: tuple[str, ...] = ("Failed to process the command.", "Traceback (most recent call last)"),
    tail_lines: int = 12,  # lines after a failure marker worth reporting
) -> str:
    """Why the bot died, from its own log lines: the diff-token cap (the
    size signal that precedes a died model call), the swallowed traceback
    seam, or the last thing it said.

    The markers and the tail are parameters because they describe this log's
    shape, not the module's state."""
    for ln in bot_lines:
        m = _SIZE_RE.search(ln)
        if m:
            return (
                f"the PR's cumulative diff is {m.group(1)} tokens — over the bot's "
                f"{m.group(2)}-token review cap; the review died after pruning the diff"
            )
    for i, ln in enumerate(bot_lines):
        if any(mark in ln for mark in markers):
            tail = [line for line in bot_lines[i : i + tail_lines] if line.strip()]
            snippet = " | ".join(line.split("\t")[-1][:200] for line in tail[:4])
            return f"the bot logged an error before dying: {snippet}"
    last = next((line for line in reversed(bot_lines) if line.strip()), "")
    return f"the bot's last output before going silent: {last.split(chr(9))[-1][:200]}"


def _review_skipped(
    log: str | None,
    failure_markers: tuple[str, ...] = ("Failed to process the command.", "Traceback (most recent call last)"),
    skip_markers: tuple[str, ...] = ("PR has no analyzable files", "skipping review", "skipping describe"),
) -> bool:
    """True when the bot examined the PR and deliberately reviewed nothing.

    pr-agent skips a PR it has no analyzable files for — a lone CSV diff, say
    — logs why, and posts no comment. That is a verdict, not a failure. The
    run log is its only record, so the marker counts ONLY when the same log
    carries no traceback and no token-cap line: a run that died cannot hide
    behind a skip line it logged before dying."""
    if not log:
        return False
    if any(mark in log for mark in failure_markers) or _SIZE_RE.search(log):
        return False
    return any(marker in log for marker in skip_markers)


class _Comment:
    """One issue comment, in the shape the API returns it."""

    def __init__(self, body: str, created_at: str, updated_at: str = "", user_type: str = "Bot"):
        self.body = body
        self.created_at = created_at
        self.updated_at = updated_at
        self.user_type = user_type

    @classmethod
    def from_json(cls, node: "Mapping[str, Any]") -> "_Comment":
        """Read one comment off the wire. The mapping is the API's shape."""
        return cls(
            node.get("body") or "",
            node.get("created_at") or "",
            node.get("updated_at") or "",
            (node.get("user") or {}).get("type", ""),
        )


class _BotComment:
    """The bot's own comment formats — the gate's whole vocabulary.

    These strings are the bot's output, not our preference: if one changes, this
    file must change with it. A miss fails the gate on a review that did post,
    which is the safe direction — the gate never passes a review that did not
    happen. A looser match would trade that for the opposite risk.
    """

    GUIDE = ("## PR Reviewer Guide", "## Incremental PR Reviewer Guide")
    SKIPPED = "Incremental Review Skipped"
    SKIP = "/skip"


def _opening(body: str) -> str:
    """The body as a format match sees it: no leading whitespace, no byte-order mark."""
    return body.lstrip().removeprefix("\ufeff").lstrip()


def _review_covers(comments: list[_Comment], sha: str, reviewed_after: str) -> bool:
    """Does any comment cover the head commit? A human /skip opt-out (applies
    to the whole PR), a posted guide (regular or incremental, referencing the
    sha, created or edited after the head was received), or the bot's own
    incremental-skip verdict (created after the head was received — the diff
    was examined and found empty, so the skip is the review, not a
    failure)."""
    if any(c.body.strip() == _BotComment.SKIP for c in comments):
        return True
    # Bodies arrive as the bot wrote them: a leading newline or byte-order mark is
    # not part of either format, and a startswith that tripped on one would fail
    # the gate on a review that did post. The guide is EDITED in place too, so
    # created_at never advances — an edit after the head arrived is coverage.
    return any(
        (
            _opening(c.body).startswith(_BotComment.GUIDE)
            and (
                f"commit/{sha}" in c.body  # the incremental "Starting from commit .../<SHA>" form
                or c.created_at >= reviewed_after
                or c.updated_at >= reviewed_after
            )
        )
        or (
            _opening(c.body).startswith(_BotComment.SKIPPED) and c.user_type == "Bot" and c.created_at >= reviewed_after
        )
        for c in comments
    )


def main() -> int:
    sha = os.environ["SHA"]
    pr_number = os.environ["PR_NUMBER"]
    gate = _ReviewGate(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])

    try:
        gate.api(f"commits/{sha}")
    except _ApiError as e:
        # surfaces via the ::error line + the non-zero exit — not a swallow
        print(f"::error::commit {sha} is not fetchable ({e}) — the review cannot cover it.")
        return 1

    # "Reviewed after" is anchored to the workflow run's start, not the
    # commit's committer date: the committer date is author-controlled and
    # predates the push, so a review posted for an earlier revision could
    # "cover" a newer head authored before it. A review that covers THIS
    # push must post after the run that checks it started.
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        print(
            "::error::GITHUB_RUN_ID is not set — the coverage anchor cannot be determined, "
            "and a guess here would pass a review that does not cover this commit."
        )
        return 1
    try:
        run = gate.api(f"actions/runs/{run_id}")
        reviewed_after = run["run_started_at"]
    # No fallback is deliberate: the anchor IS the check. With no run start
    # there is no conservative guess, because the committer date predates the
    # push and an earlier head's review can land inside that window.
    except (_ApiError, KeyError) as e:
        # NO fallback to the committer date. It predates the push, so a review
        # of an earlier head, posted after the commit was authored but before
        # it was pushed, would count as covering this one. Failing is the
        # honest answer: the anchor is unknown, so coverage is unproven.
        print(
            f"::error::run_started_at unavailable ({type(e).__name__}: {e}) — "
            "cannot determine whether a review covers this commit."
        )
        return 1

    try:
        comments = [_Comment.from_json(c) for c in gate.api(f"issues/{pr_number}/comments?per_page=100")]
    except _ApiError as e:
        print(f"::error::PR comments are not fetchable ({e}) — the review coverage cannot be checked.")
        return 1
    if not _review_covers(comments, sha, reviewed_after):
        try:
            log = gate.job_log()
        except (_ApiError, KeyError, URLError) as e:
            print(
                f"::error::AI review did not post for commit {sha} — the job log could not be "
                f"read ({type(e).__name__}: {e}), so the reason is unknown."
            )
            return 1
        if _review_skipped(log):
            print(
                f"::notice::no review posted for {sha} — the reviewer found nothing it can "
                "analyse in this PR. A clean skip, not a failure."
            )
            return 0
        reason = _bot_failure_reason(log)
        print(f"::error::AI review did not post for commit {sha} — {reason}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
