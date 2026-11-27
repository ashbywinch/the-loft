#!/bin/bash
# Commit through the formatter, and prove the commit landed.
#
# The hooks reformat the whole Python tree, so a commit that stages first is
# refused after the formatter rewrote it — and a refused commit leaves HEAD
# where it was, so the next push sends the old head. Formatting first leaves the
# hooks nothing to fix.
#
# A pipeline's exit status is its last stage's, so a caller cannot tell a
# refused commit from a made one; this ends by reading the subject back from
# HEAD and fails when they differ.
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
