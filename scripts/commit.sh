#!/bin/bash
# Commit through the formatter, and prove the commit landed.
#
# Two failures this exists for, both measured on 2026-11-26/27:
#
#   1. a pre-commit hook reformats a staged file, the commit is refused, and the
#      next command runs against the OLD head — so a push sends a branch whose
#      head is still main. `make format` first leaves the hook nothing to fix;
#   2. `git commit … | tail -1` reports the plumbing's exit status, not the
#      commit's, so a refusal reads as success. The subject is read back from
#      HEAD afterwards, and a mismatch is an error.
#
# Usage: scripts/commit.sh "<subject>" ["<body file>"]
set -euo pipefail

[ $# -ge 1 ] || { echo "usage: scripts/commit.sh <subject> [body-file]" >&2; exit 2; }
subject="$1"
body="${2:-}"

cd "$(git rev-parse --show-toplevel)"

make format >/dev/null
git add -A

if git diff --cached --quiet; then
    echo "nothing to commit — the tree matches HEAD"
    exit 0
fi

if [ -n "$body" ]; then
    git commit -q -F "$body" || { echo "commit refused — read the hook output above" >&2; exit 1; }
else
    git commit -q -m "$subject" || { echo "commit refused — read the hook output above" >&2; exit 1; }
fi

landed="$(git log -1 --format=%s)"
if [ "$landed" != "$subject" ]; then
    echo "the commit did not land — HEAD is '$landed'" >&2
    exit 1
fi
echo "committed: $(git log -1 --oneline)"
