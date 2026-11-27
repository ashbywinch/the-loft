#!/bin/bash
# Commit through the formatter, and prove the commit landed.
#
# Usage: scripts/commit.sh "<subject>" [path ...]
#
# Stage only what you name: with no paths the script stages TRACKED changes
# (`git add -u`); a new file must be named, so an untracked artefact in the tree
# cannot ride along. The hooks reformat the whole Python tree, so the formatter
# runs first — a commit refused after a reformat leaves HEAD where it was.
#
# The script ends by reading HEAD back: a refused commit and a made one are
# indistinguishable from a pipeline's status.
set -euo pipefail

[ $# -ge 1 ] || { echo "usage: scripts/commit.sh <subject> [path ...]" >&2; exit 2; }
subject="$1"
shift

cd "$(git rev-parse --show-toplevel)"

# captured, not redirected to a file: a temporary file is one more path to
# trust, and the output only matters when the step fails
if ! format_output="$(make format 2>&1)"; then
    printf '%s\n' "$format_output" >&2
    echo "make format failed — nothing was committed" >&2
    exit 1
fi

if [ $# -gt 0 ]; then
    git add -- "$@"
else
    git add -u
fi

if git diff --cached --quiet; then
    echo "nothing to commit — the staged tree matches HEAD"
    exit 0
fi

before="$(git rev-parse HEAD)"
git commit -m "$subject"

if [ "$(git rev-parse HEAD)" = "$before" ]; then
    echo "the commit did not land — HEAD is still $(git log -1 --oneline)" >&2
    exit 1
fi

landed="$(git log -1 --format=%s | sed 's/[[:space:]]*$//')"
wanted="$(printf '%s' "$subject" | sed 's/[[:space:]]*$//')"
if [ "$landed" != "$wanted" ]; then
    echo "the commit landed as '$landed', not '$wanted'" >&2
    exit 1
fi
git log -1 --oneline
