"""Called by .github/workflows/pr-agent.yml — fail the PR if the review bot
did not produce a review covering the head commit. The review may have
failed silently; this check prevents merging unreviewed.

The one coverage signal is a COMPLETED "PR Agent - Review" check run on the
head SHA — the artifact the bot publishes only with the review text in hand
(`github.publish_as_check_run`; `_publish_check_run`). The bot's own step
conclusion is NEVER trusted: the action exits 0 whether or not the review
happened, so a green step claims nothing about a review existing.

A comment is not coverage. A run that dies after posting its guide leaves a
comment that reads exactly like a finished review, and the guide carries no
record of which head it reviewed. The live config therefore publishes the
check run (persistent comment, a full review per push) and this gate reads
it; a review that did not happen leaves the gate red.

Why the bot's own step cannot fail: ``PRAgent.handle_request`` catches
EVERY exception with a bare ``except`` — it logs "Failed to process the
command." plus the traceback and returns False — and
``github_action_runner.py`` discards that return value, so the action
exits 0 whether or not the review happened. A green
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
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, override
from urllib.error import HTTPError

# CI runs this as a FILE (`python3 pipeline/evals/check_review_posted.py`), so
# sys.path[0] is this script's own directory and the repo root — the `pipeline`
# package — is absent: without the bootstrap the gate dies with
# ModuleNotFoundError before reading a comment, and every PR's review check
# goes red for a reason unrelated to the review (2026-10-21).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.model.http_headers import HttpHeaders  # noqa: E402 — the bootstrap above must run first

_SIZE_RE = re.compile(r"Tokens:\s*(\d+),\s*total tokens over limit:\s*(\d+)")


class _GitHub:
    _ERROR_MARKERS: ClassVar[tuple[str, ...]] = ()
    _TRACEBACK_TAIL: ClassVar[int] = 0

    """The API client this check speaks: every call carries the same token and
    asks for the same JSON accept header, so they travel as this class's state.
    The transport is injected (the repo's DI convention) — the tests drive the
    real client through a fake opener, never a patched global."""

    def __init__(self, token: str, open_url: Callable[[urllib.request.Request], bytes] | None = None) -> None:
        self.token = token
        self._open = open_url or (lambda req: urllib.request.urlopen(req).read())

    def get(self, url: str, accept: str = "application/vnd.github+json", token: str = "") -> bytes:
        req = urllib.request.Request(
            url,
            headers=HttpHeaders(authorization=f"Bearer {token or self.token}", accept=accept).to_dict(),
        )
        return self._open(req)

    def get_json(self, url: str, token: str = ""):
        """The gate's fetch seam is ``fetch(url, token)`` (the tests inject
        exactly that): the argument is honoured, the instance's token is the
        default — passing the bound method straight to ``run_review_gate``
        used to raise TypeError before the first API call (2026-10-17)."""
        return json.loads(self.get(url, token=token))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The log endpoint 302s to a signed blob URL; urllib's auto-follow
    forwards the Authorization header onto the blob host, which rejects it
    (401 InvalidAuthenticationInfo, 2026-08-11). Stop at the 302 and fetch
    the signed Location bare."""

    @staticmethod
    @override
    def redirect_request(req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


# The markers the bot leaves when a review dies inside the (swallowed)
# exception seam, plus the size signal that precedes a died model call.
_GitHub._ERROR_MARKERS = (
    "Failed to process the command.",
    "Traceback (most recent call last)",
    # the route/auth class: the review 401s at the API boundary and dies
    # silently
    "AuthenticationError",
    "Invalid API key",
    "Unauthorized",
    "401",
)

_GitHub._TRACEBACK_TAIL = 12  # lines after a traceback/marker worth reporting


class _ReviewSite:
    """The bot's artifacts for one repository: its run log, the failure
    reason drawn from it, and the anchor a skip vouches for. The repo and the
    token travel together (one site, one credential) — a free function taking
    the pair for each read would repeat the clump."""

    def __init__(self, repo: str, token: str) -> None:
        self.repo = repo
        self.token = token

    def job_log(self) -> str | None:
        """The running job's own accumulated log (the bot step's output), or
        None when the checks API won't serve it mid-run — the caller falls
        back to the generic message. Requires the workflow's ``actions: read``."""
        run_id = os.environ.get("GITHUB_RUN_ID")
        if not run_id:
            return None
        try:
            jobs = _GitHub(self.token).get_json(f"https://api.github.com/repos/{self.repo}/actions/runs/{run_id}/jobs")
            if not jobs.get("jobs"):
                return None
            req = urllib.request.Request(
                f"https://api.github.com/repos/{self.repo}/actions/jobs/{jobs['jobs'][0]['id']}/logs",
                headers=HttpHeaders(
                    authorization=f"Bearer {self.token}", accept="application/vnd.github+json"
                ).to_dict(),
            )
            try:
                return _OPENER.open(req).read().decode("utf-8", errors="replace")
            except HTTPError as e:
                if e.code != http.HTTPStatus.FOUND:
                    raise
                # the signed blob host rejects bare urllib (the WAF's UA rule);
                # fetch the Location bare — a refusal here degrades to None
                # (the generic message), never a crash
                try:
                    # the signed blob host's WAF rejects urllib's default UA
                    # (the same rule that hit the gateway) — send the house's
                    # known-good UA or the log read degrades to the generic
                    # message
                    req2 = urllib.request.Request(
                        e.headers["Location"],
                        headers={"User-Agent": "opencode/1.14.20"},
                    )
                    return urllib.request.urlopen(req2, timeout=60).read().decode("utf-8", errors="replace")
                except (urllib.error.URLError, OSError):
                    return None
        except (HTTPError, KeyError, ValueError, urllib.error.URLError, OSError):
            return None

    def failure_reason(self) -> str:
        """The bot's own words about its failure, from the run log — the reason
        the review died, instead of a guess. Falls back to the last thing the
        bot said."""
        log = self.job_log()
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
        return f"the bot's last output before going silent: {last.split(chr(9))[-1][:200]}"


def _completed_review_check_run(fetch, repo: str, sha: str) -> bool:
    """Is there a COMPLETED "PR Agent - Review" check run on the head
    commit? The bot creates it ONLY with the review output text in hand
    (github_provider._publish_check_run: called from
    publish_persistent_comment with the review text; a failed or skipped
    review produces no check). It is the output artifact, not the step's
    self-reported success — the action can run to completion while
    producing nothing, so a step-conclusion gate would pass a review that
    never happened. (User: "isn't this re-introducing our original bug
    where it just claims it's successful even when it's not?".) The
    conclusion is always "neutral"; completed-neutral means the review
    text was published. Any query failure degrades to False: a crashed gate
    would be the worst outcome, and a false negative fails loud."""
    try:
        runs = fetch(f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs", "")
        return any(
            r.get("name") == "PR Agent - Review" and r.get("status") == "completed" for r in runs.get("check_runs", [])
        )
    except (KeyError, ValueError, AttributeError, OSError):
        return False


def _bot_failure_reason(repo: str, token: str) -> str:
    """The injected default: the site's own words about a failed review."""
    return _ReviewSite(repo, token).failure_reason()


def _size_reason(bot_lines: list[str]) -> str | None:
    """The size signal first — a review that died right after pruning is a
    PR that outgrew the bot's review budget."""
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
        if any(mark in ln for mark in _GitHub._ERROR_MARKERS):
            tail = [line for line in bot_lines[i : i + _GitHub._TRACEBACK_TAIL] if line.strip()]
            snippet = " | ".join(line.split("\t")[-1][:200] for line in tail[:4])
            return f"the bot logged an error before dying: {snippet}"
    return None


def run_review_gate(fetch, env, failure_reason=None) -> int:
    """The gate as a pure function: ``fetch(url, token)`` -> parsed JSON,
    ``env`` the CI environment mapping, ``failure_reason(repo, token)`` the
    bot's own words about a death. Testable by injection — the repo's DI
    convention; never monkeypatch."""
    sha = env["SHA"]
    repo = env["GITHUB_REPOSITORY"]
    token = env["GITHUB_TOKEN"]
    if _completed_review_check_run(fetch, repo, sha):
        return 0
    reason = (failure_reason or _bot_failure_reason)(repo, token)
    print(f"::error::AI review did not post for commit {sha} — {reason}.")
    return 1


def main() -> int:
    api = _GitHub(os.environ.get("GITHUB_TOKEN", ""))
    return run_review_gate(api.get_json, os.environ)


if __name__ == "__main__":
    sys.exit(main())
