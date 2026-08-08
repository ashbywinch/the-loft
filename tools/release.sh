#!/usr/bin/env bash
# The one public-release step (2026-08-08, user): gate, rebuild the public
# root commit, and push ONLY the-loft. The private repo (family-history-album)
# is frozen with its full history — nothing here pushes to it, the origin
# remote is removed so a private push cannot happen again, and the script
# refuses to run if origin is ever re-added.
set -euo pipefail
cd "$(dirname "$0")/.."

BRANCH="$(git branch --show-current)"
if [ "$BRANCH" != "prep/public-release" ]; then
  echo "release: run from prep/public-release (on $BRANCH)" >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "release: working tree is dirty — commit or stash first" >&2
  exit 1
fi
if ! git remote | grep -qx loft; then
  echo "release: the loft remote is missing (git remote add loft https://github.com/ashbywinch/the-loft.git)" >&2
  exit 1
fi
if git remote | grep -qx origin; then
  echo "release: the private origin remote is still configured — refusing to risk a private push" >&2
  exit 1
fi

# the gate runs the full suite + the no-PII guard before anything ships
make test

# rebuild the public root commit from this exact tree (no history), push ONLY loft
git branch -D loft-release 2>/dev/null || true
git checkout --orphan loft-release
git commit --no-verify -m "The loft — a family-history album web app

An explorable, evidence-first family archive: letters, stories,
photographs, people and places, with a document-import pipeline (GEDCOM 7
round-trip) and Google sign-in. The real family content lives in a
private dataset that never ships — the public tree carries code, docs
and synthetic fixtures only; the no-PII guard (tests/test_no_pii_in_repo.py)
loads its markers from the dataset at runtime and refuses the build if
any identifying name, id, date or coordinate leaks into tracked files."
git push -f loft loft-release:main
git checkout prep/public-release

# the public main must carry exactly this tree — any drift is a failed release
if [ -n "$(git diff loft-release prep/public-release)" ]; then
  echo "release: the-loft main drifted from this tree — NOT released" >&2
  exit 1
fi
echo "released to the-loft (main): $(git rev-parse loft-release)"
