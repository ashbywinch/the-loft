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
fetches the run's own log (the actions API) and extracts the bot's error
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
from dataclasses import dataclass
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


class _NoLogError(Exception):
    """There is no log to read, and the message names which of the ways it is
    missing: no run to read, no jobs listed yet, no job carrying the review's
    name, no download URL. The caller repeats it, so the failure names the
    cause it observed instead of guessing at one."""


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

    def job_log(self, run_id: str | None = None, wanted: str | None = None) -> str:
        """The review job's accumulated log (the bot step's output). Requires
        the workflow's ``actions: read``.

        ``run_id`` and ``wanted`` default to this workflow's own environment
        (``GITHUB_RUN_ID``, ``REVIEW_JOB_NAME``); passing them is the test seam.

        A log that is not there raises ``_NoLogError`` naming which way it is not
        there; a fetch that fails raises its own error. Nothing is returned to
        stand for "no log": a caller that conflated the two would report a
        cause it never observed.
        """
        run_id = run_id or os.environ.get("GITHUB_RUN_ID")
        if not run_id:
            raise _NoLogError("GITHUB_RUN_ID is not set, so there is no run to read")
        jobs = self.api(f"actions/runs/{run_id}/jobs")
        if not jobs.get("jobs"):
            raise _NoLogError(f"run {run_id} lists no jobs")
        # The reason we want lives in the REVIEW job's log, not in whichever job
        # the API happens to list first — this runs from a second job in the
        # same run, and listing order is not the workflow's order.
        wanted = wanted or os.environ.get("REVIEW_JOB_NAME", "pr-review")
        matches = [j for j in jobs["jobs"] if _job_name_matches(j.get("name", ""), wanted)]
        if not matches:
            raise _NoLogError(f"the run lists no job named {wanted!r} (set REVIEW_JOB_NAME)")
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
                raise _NoLogError("the log download answered a redirect with no Location") from e
            return urllib.request.urlopen(location, timeout=30).read().decode("utf-8", errors="replace")
        return resp.read().decode("utf-8", errors="replace")


class _BotLog:
    """The bot's own run log, read one way for every question asked of it.

    Two facts come from it: whether the review died, and whether it
    deliberately reviewed nothing. **Both scan the whole log**, so a marker
    outside the JSON wrapper still counts — a run that died cannot be read as a
    clean skip because its traceback was logged as plain text. Only the failure
    *message* narrows to the bot's structured lines (`"text"`), because those
    carry the words worth quoting; narrowing the scan itself would let a silent
    failure read as a verdict.

    The reason is extracted rather than guessed: the diff-token cap that
    precedes a pruned diff, the swallowed traceback seam, and failing both, the
    last thing the bot said.
    """

    FAILURE_MARKERS = ("Failed to process the command.", "Traceback (most recent call last)")
    SKIP_MARKERS = ("PR has no analyzable files", "skipping review", "skipping describe")
    TAIL_LINES = 12  # lines after a failure marker worth reporting

    def __init__(self, text: str) -> None:
        self.text = text
        self._structured = [line for line in self.text.splitlines() if '"text"' in line]

    @property
    def failed(self) -> bool:
        """The review died: a failure marker or the token-cap line, anywhere."""
        return any(mark in self.text for mark in self.FAILURE_MARKERS) or bool(_SIZE_RE.search(self.text))

    @property
    def skipped(self) -> bool:
        """The bot examined the PR and deliberately reviewed nothing.

        pr-agent skips a PR it has no analyzable files for — a lone CSV diff,
        say — logs why, and posts no comment. That is a verdict, not a failure,
        and it counts only when the same log carries no failure.
        """
        if not self.text or self.failed:
            return False
        return any(marker in self.text for marker in self.SKIP_MARKERS)

    @property
    def reason(self) -> str:
        """Why the review did not post, in the bot's own words.

        An empty log is a log that was served and said nothing; a log with no
        structured lines is one the step wrote as plain text. The two are
        different witnesses and get different sentences — neither is asked to
        stand for a log that could not be read at all, which arrives here as a
        fetch error (`_NoLogError`).
        """
        if not self.text:
            return "the bot's job log is empty: the step produced no output at all"
        if not self._structured:
            return "the bot's step wrote no structured output — every line was plain text"
        return self._from_structured()

    def _from_structured(self) -> str:
        """The failure the bot's own records name, or the last thing it said."""
        for line in self._structured:
            match = _SIZE_RE.search(line)
            if match:
                return (
                    f"the PR's cumulative diff is {match.group(1)} tokens — over the bot's "
                    f"{match.group(2)}-token review cap; the review died after pruning the diff"
                )
        for index, line in enumerate(self._structured):
            if any(mark in line for mark in self.FAILURE_MARKERS):
                tail = [ln for ln in self._structured[index : index + self.TAIL_LINES] if ln.strip()]
                snippet = " | ".join(ln.split("\t")[-1][:200] for ln in tail[:4])
                return f"the bot logged an error before dying: {snippet}"
        last = next((ln for ln in reversed(self._structured) if ln.strip()), "")
        return f"the bot's last output before going silent: {last.split(chr(9))[-1][:200]}"


@dataclass(frozen=True)
class _Comment:
    """One issue comment, in the shape the API returns it."""

    body: str
    created_at: str
    updated_at: str = ""
    user_type: str = "Bot"

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


def _from_a_machine(user_type: str) -> bool:
    """Whether the comment came from a machine rather than a human.

    The bot's empty-increment skip counts only when the bot posted it: a human
    can paste the same words, and a human's paste is not a review. GitHub
    reports machine accounts as ``Bot`` (github-actions) or ``App`` (an App's
    own comment) and people as ``User``, so the test is "not a person" rather
    than a list of the machine spellings the API happens to use today.
    """
    return user_type != "User"


@dataclass(frozen=True)
class _Coverage:
    """One comment's claim to cover the head commit, judged against this run.

    A review reaches the PR in one of three forms — a human's skip, a posted
    guide, or the bot's empty-increment skip — and each is one property here so
    ``covers`` reads as the three ways a head can be covered.
    """

    comment: _Comment
    run_started: str

    @property
    def posted_after(self) -> bool:
        """Whether the comment is this run's, by time.

        GitHub writes both stamps in one fixed format (``2026-11-24T19:22:18Z``,
        UTC), so text order is time order. An edit counts as well as a new
        comment because the guide is EDITED in place — its ``created_at`` never
        advances, so an edit after the head arrived is the only sign of a new
        review. A stamp equal to the run start counts: two runs in the same
        second on one PR are reviewing the same push.
        """
        return self.comment.created_at >= self.run_started or self.comment.updated_at >= self.run_started

    @property
    def a_human_skip(self) -> bool:
        """A human's ``/skip`` opts the whole PR out of review, by deliberate choice."""
        return self.comment.body.strip() == _BotComment.SKIP

    def a_guide_for(self, sha: str) -> bool:
        """A posted review, either form, for this head: it names the head sha or it
        arrived during this run.

        The incremental body names the range's FIRST new commit, not the head — so
        coverage for an incremental review falls to the posted-during-this-run rule,
        and the explicit form is belt-and-braces for reviews that embed the head.
        """
        if not _opening(self.comment.body).startswith(_BotComment.GUIDE):
            return False
        return f"commit/{sha}" in self.comment.body or self.posted_after

    @property
    def a_bot_skip(self) -> bool:
        """The bot's own "no new files since the last review" verdict.

        An incremental review whose increment is empty posts this instead of a
        guide: the diff since the last review was examined and found empty, so the
        skip IS the review, not a failure. It covers only when the bot posted it
        during this run.
        """
        return (
            _opening(self.comment.body).startswith(_BotComment.SKIPPED)
            and _from_a_machine(self.comment.user_type)
            and self.comment.created_at >= self.run_started
        )

    def covers(self, sha: str) -> bool:
        """One of the three forms covers this head."""
        return self.a_human_skip or self.a_guide_for(sha) or self.a_bot_skip


def _review_covers(comments: list[_Comment], sha: str, run_started: str) -> bool:
    """Does any comment cover the head commit? Three forms count, one property each:
    a human skip, a guide for this head, or the bot's empty-increment skip."""
    return any(_Coverage(comment, run_started).covers(sha) for comment in comments)


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
        except (_ApiError, _NoLogError, KeyError, URLError) as e:
            print(
                f"::error::AI review did not post for commit {sha} — the job log could not be "
                f"read ({type(e).__name__}: {e}), so the reason is unknown."
            )
            return 1
        if _BotLog(log).skipped:
            print(
                f"::notice::no review posted for {sha} — the reviewer found nothing it can "
                "analyse in this PR. A clean skip, not a failure."
            )
            return 0
        reason = _BotLog(log).reason
        print(f"::error::AI review did not post for commit {sha} — {reason}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
