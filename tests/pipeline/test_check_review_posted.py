"""The review gate's coverage contract: a review covers the head commit when
it is a posted guide naming that SHA or posted (created or edited) after the
workflow run started, a human /skip opt-out, or the bot's own "Incremental
Review Skipped" verdict posted after the run started. The bot's deliberate
"no analyzable files" skip is a verdict too, and only the run log witnesses
it — a clean marker passes, the same log with a failure marker does not.

The gate is driven through its seams (parameter injection, the repo's DI
convention): the comment model and the coverage/skip/reason rules are pure
functions, and the API transport is the injected ``get``/``get_json``
argument. No network, no wall clock, no patched globals.
"""

from __future__ import annotations

import pytest

from pipeline.evals import check_review_posted as gate

_SHA = "44d47e01e09a7e4992d2760b0e86d87fc7d48d7c"
_RUN_STARTED = "2026-08-22T12:41:46Z"
_BEFORE_THE_RUN = "2026-08-22T12:00:00Z"
_AFTER_THE_RUN = "2026-08-22T12:42:27Z"

_GUIDE = "## PR Reviewer Guide 🔍\nNo major issues detected"
_SKIPPED = "Incremental Review Skipped\nNo files were changed since the previous PR Review"
_NO_ANALYZABLE_FILES = (
    '{"text":"PR has no analyzable files: o/r/12, skipping describe"}\n'
    '{"text":"PR has no analyzable files: o/r/12, skipping review"}\n'
)


def _comment(
    body: str,
    created_at: str = _AFTER_THE_RUN,
    updated_at: str = "",
    user_type: str = "Bot",
) -> gate._Comment:
    return gate._Comment(body, created_at, updated_at, user_type)


def _covers(comments: list[gate._Comment]) -> bool:
    return gate._review_covers(comments, _SHA, _RUN_STARTED)


def test_a_guide_referencing_the_head_sha_covers() -> None:
    """The incremental body names the range's first commit; a body naming the
    head SHA covers even when it was posted before this run started."""
    body = f"## Incremental PR Reviewer Guide 🔍\nStarting from commit https://github.com/o/r/commit/{_SHA}"
    assert _covers([_comment(body, created_at=_BEFORE_THE_RUN)])


def test_a_guide_edited_after_the_run_started_covers() -> None:
    """The persistent guide is edited in place: created_at stays at its first
    date, so an edit after the run started is the only sign of a new review."""
    assert _covers([_comment(_GUIDE, created_at=_BEFORE_THE_RUN, updated_at=_AFTER_THE_RUN)])


def test_an_app_typed_skip_still_covers() -> None:
    """GitHub reports machine accounts as `Bot` or `App`; the skip counts for
    either, because the test is "not a person", not a list of spellings."""
    body = "Incremental Review Skipped — no new files since the last review"
    assert _covers([_comment(body, user_type="App")])


def test_a_persons_skip_text_does_not_cover() -> None:
    """A human can paste the bot's words. A human's paste is not a review."""
    body = "Incremental Review Skipped — no new files since the last review"
    assert not _covers([_comment(body, user_type="User")])


def test_an_inline_finding_from_the_bot_covers() -> None:
    """The incremental path publishes findings as inline review comments and no
    guide (measured on the pinned action). An inline comment from a machine,
    during this run, is the review speaking."""
    inline = [_comment("**Possible Issue** something in the diff", user_type="Bot")]
    assert gate._a_finding_posted(inline, _RUN_STARTED)


def test_an_inline_comment_from_a_person_does_not_cover() -> None:
    inline = [_comment("I think this is wrong", user_type="User")]
    assert not gate._a_finding_posted(inline, _RUN_STARTED)


class _Compared:
    """A gate whose compare answers with a fixed file list."""

    def __init__(self, files: list[dict[str, str]] | None = None) -> None:
        self.files = files if files is not None else []
        self.paths: list[str] = []

    def api(self, path: str):
        self.paths.append(path)
        return {"files": self.files}


def test_a_head_that_changed_no_files_is_covered_by_the_review_before_it() -> None:
    """A merge of the base branch changes none of the PR's files; the reviewer
    publishes nothing, and the review before it still speaks for this head."""
    gate_stub = _Compared()
    assert gate._reviewed_since_unchanged(gate_stub.api, ["a" * 40], "b" * 40) == "a" * 40
    assert gate_stub.paths == [f"compare/{'a' * 40}...{'b' * 40}"]


def test_a_head_with_changed_files_is_not_covered_by_an_earlier_review() -> None:
    gate_stub = _Compared([{"filename": "pipeline/evals/eval_crop_grid.py"}])
    assert gate._reviewed_since_unchanged(gate_stub.api, ["a" * 40], "b" * 40) is None


def test_the_head_never_covers_itself_by_comparison() -> None:
    """Asking a commit to be its own ancestor would compare nothing and pass
    every head; the comparison is only ever against a different commit."""
    gate_stub = _Compared()
    assert gate._reviewed_since_unchanged(gate_stub.api, ["a" * 40], "a" * 40) is None
    assert gate_stub.paths == []


def test_a_review_that_found_nothing_to_publish_is_a_verdict() -> None:
    """pr-agent logs this when the increment was examined and came back clean."""
    log = '{"text":"Review output is not published: no major issues detected."}\n'
    assert gate._BotLog(log).nothing_to_publish


def test_a_guide_with_leading_whitespace_still_covers() -> None:
    """A body arrives as the bot wrote it. A leading newline or byte-order mark
    is not part of the format, and tripping on one would fail the gate on a
    review that did post — the one direction this check must not fail in."""
    body = f"\n\ufeff## PR Reviewer Guide 🔍\nStarting from commit /commit/{_SHA}"
    assert _covers([_comment(body)])


def test_the_bot_skip_with_leading_whitespace_still_covers() -> None:
    body = "\n  Incremental Review Skipped — the diff since the last review is empty"
    assert _covers([_comment(body)])


def test_a_guide_older_than_the_run_start_does_not_cover() -> None:
    """A guide neither naming the head nor touched since this run began is an
    earlier round's text — it says nothing about this push."""
    assert not _covers([_comment(_GUIDE, created_at=_BEFORE_THE_RUN, updated_at=_BEFORE_THE_RUN)])


def test_a_human_skip_covers() -> None:
    """A human's /skip opts the whole PR out of review — by deliberate choice."""
    assert _covers([_comment("/skip", created_at=_BEFORE_THE_RUN, user_type="User")])


def test_the_bots_incremental_skip_after_the_run_started_covers() -> None:
    """An incremental review with no files changed since the last review posts
    a skip instead of a guide: the diff was examined and found empty, so the
    skip IS the reviewed verdict."""
    assert _covers([_comment(_SKIPPED)])


def test_the_bots_incremental_skip_before_the_run_start_does_not_cover() -> None:
    """A skip for an earlier revision must not cover a newer head."""
    assert not _covers([_comment(_SKIPPED, created_at=_BEFORE_THE_RUN)])


def test_a_skip_from_a_human_does_not_cover() -> None:
    """Only the bot's own skip verdict counts; a human comment carrying the
    same prefix is not a review."""
    assert not _covers([_comment(_SKIPPED, user_type="User")])


def test_a_comment_is_read_off_the_wire_with_its_author_type() -> None:
    """The coverage rule branches on the author's type, so the wire mapping
    must carry it — a dropped user.type would turn every bot skip into a
    human one."""
    comment = gate._Comment.from_json(
        {"body": _SKIPPED, "created_at": _AFTER_THE_RUN, "updated_at": "", "user": {"type": "Bot"}}
    )
    assert comment.user_type == "Bot"
    assert _covers([comment])


def test_a_clean_no_analyzable_files_log_passes() -> None:
    """The bot examined a PR it cannot analyse (a lone CSV diff) and said so;
    it posts nothing by design. The log is the verdict."""
    assert gate._BotLog(_NO_ANALYZABLE_FILES).skipped


def test_the_same_skip_log_with_a_traceback_fails() -> None:
    """A run that died cannot hide behind a skip line it logged before dying."""
    log = _NO_ANALYZABLE_FILES + '{"text":"Failed to process the command."}\n'
    assert not gate._BotLog(log).skipped


def test_the_same_skip_log_over_the_token_cap_fails() -> None:
    """The size marker means the review was pruned past its budget, not that
    there was nothing to read."""
    log = _NO_ANALYZABLE_FILES + '{"text":"Tokens: 91000, total tokens over limit: 80000"}\n'
    assert not gate._BotLog(log).skipped


def test_a_failure_logged_as_plain_text_quotes_its_own_line() -> None:
    """The marker can arrive outside the structured lines. The quote is then the
    marker, never whichever structured lines happened to come first."""
    log = 'a plain traceback line: Traceback (most recent call last)\n{"text":"starting"}\n'
    reason = gate._BotLog(log).reason
    assert "Traceback" in reason
    assert "starting" not in reason


def test_a_non_json_api_body_is_named_in_the_failure() -> None:
    """A proxy's error page or a truncated read is not an empty review: the
    failure names the body as the thing that could not be read."""

    def html(url: str, token: str) -> bytes:
        return b"<html>Bad gateway</html>"

    with pytest.raises(gate._ApiError) as raised:
        gate._get_json("https://api.github.com/repos/o/r/commits/x", "t", get=html)
    assert "not JSON" in str(raised.value)


def test_the_gate_reads_the_pr_comments_of_its_repo_with_its_token() -> None:
    """The comment query is part of the contract: a placeholder repo or a
    missing PR number 404s, and the gate reads as "no review"."""
    seen: list[tuple[str, str]] = []

    def comments(url: str, token: str) -> list[object]:
        seen.append((url, token))
        return []

    gate._ReviewGate("org/repo", "t", get_json=comments).api("issues/7/comments?per_page=100")
    assert seen == [("https://api.github.com/repos/org/repo/issues/7/comments?per_page=100", "t")]


def test_a_prefixed_review_job_name_still_matches() -> None:
    """A reusable workflow lists ``pr-review`` as ``review / pr-review``; the
    log reader has to find that job or every failure loses its reason."""
    assert gate._job_name_matches("pr-review", "pr-review")
    assert gate._job_name_matches("review / pr-review", "pr-review")
    assert not gate._job_name_matches("review / verify", "pr-review")
    assert not gate._job_name_matches("pr-review / extra", "pr-review")


def test_a_run_without_the_review_job_names_that_as_the_reason() -> None:
    """The reason must name the cause it observed. A run listing no job by the
    review's name is not a job that is still running — that sentence sends the
    reader looking for a job that was never there."""

    def jobs(url: str, token: str) -> object:
        return {"jobs": [{"name": "review / build", "id": 7}]}

    with pytest.raises(gate._NoLogError) as raised:
        gate._ReviewGate("o/r", "t", get_json=jobs).job_log("42", "pr-review")
    assert "pr-review" in str(raised.value)
    assert "running" not in str(raised.value)


def test_an_empty_served_log_is_not_a_withheld_one() -> None:
    """A log that was served and says nothing is the step being silent, not
    GitHub withholding a log for a job that is still running."""
    reason = gate._BotLog("").reason
    assert "empty" in reason
    assert "running" not in reason


def test_a_plain_text_log_is_reported_as_unstructured() -> None:
    """Text with no structured lines is output the extractor cannot quote.
    Saying the step produced no output would be false, and a reader who
    believes it stops looking for the line that explains the failure."""
    reason = gate._BotLog("Setting up job\nThe process completed with exit code 0").reason
    assert "plain text" in reason
    assert "no output at all" not in reason
