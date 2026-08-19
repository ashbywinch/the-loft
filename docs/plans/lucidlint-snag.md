# lucidlint snag log

Issues encountered while integrating lucidlint (github.com/ashbywinch/lucidlint)
into the-loft repo. For feeding back to the maintainer.

## Why not pip-installable

The tool bundles a Rust binary inside a tar.gz — there is no PyPI package.
The bundle contains `lucidlint.py` (thin Python orchestrator), `fix_engine.py`
(the AST rewrite core), and `bin/lucidlint` (Rust scan engine). The Rust
binary is the real scanner; the Python scripts orchestrate and apply fixes.

To install: download the tar.gz from GitHub Releases, verify SHA256, extract,
and point at `lucidlint.py`. The Makefile's `install-lucidlint` target does
this. A `pip install lucidlint` would need a PyPI package that either:
- includes a prebuilt Rust binary for each platform (heavy, unusual)
- builds from source (requires Rust toolchain)
For now the tar.gz distribution is the only path.

## Scanning own dist directory

lucidlint by default scans every `.py` file under `--repo`, including the
extracted bundle directory (`lucidlint-dist/`). This flags dozens of minor
issues in the tool's own code (loop-pipeline, magic-number, detached-method,
broad-except). Those findings are noise for the repo maintainer.

Suggested fix: add `lucidlint-dist/` to the tool's internal exclusion list,
or let the repo-level `.lucidlint.toml` exclude directories (it currently
only supports rule-level suppressions). Currently the repo's `.gitignore`
covers it, but lucidlint doesn't read gitignore.

## `stale-suppression` autofix removes `#` comment prefix

The `--fix --kind stale-suppression` machinery correctly removes the directive
but strips the `#` from the comment that follows, turning it into bare prose
on an otherwise-code line. This breaks the file.

Example:
```
    # lucidlint: ignore special-case a missing person is an error to raise
```
becomes:
```
     a missing person is an error to raise
```
instead of:
```
    # a missing person is an error to raise
```

The fix engine should preserve the `#` when removing a suppression directive
from a line that has trailing comment content.

## `magic-number` fix requires manual name

The fix suggestion `--name <CONST>` requires the user to supply a constant
name. For numbers that are obviously "the number of X" (e.g. `3` at line 1286
in `_baseline_identity`, or `86400` = seconds in a day), the tool could
suggest a name or skip the finding for self-documenting constants. The
current workflow requires the user to either name every number (tedious) or
ignore the whole rule (too broad).

## `loop-pipeline` on collection-building loops is often correct but noisy

Many collection-building loops are genuinely clearer as loops — especially
when they filter, transform, and collect in one pass, or when the collection
has side effects. The warning fires on any loop that builds a list, even when
a comprehension would be less readable. Could use a heuristic for "complex
loop body" (more than one if/for/try inside) to suppress the warning.

## Baseline locks the repo but is hard to diff

The baseline JSON is a flat set of action keys (e.g. `AGENTS.md:0`). There's
no diff format — to see what changed between two runs, you diff the baseline
files. A human-readable summary (`--report`) would help.

## First run is slow

The first `--repo` scan takes ~5 seconds (git history analysis, co-change
graph, coverage correlation). Subsequent scans with a warmed cache would be
faster, but there's no `--refresh-coverage` caching visible in the output.

## Doc edge-tracking doesn't understand indirect reachability

The `docs` rule checks that every `.md` file is reachable from `AGENTS.md`
by following doc-to-doc links. This assumes AGENTS.md is a complete index
of every doc the reader might need.

In practice, AGENTS.md is a bootloader — it points the reader (or an agent)
in the right direction based on what they're trying to do. Specialised design
docs (e.g. `docs/archive-concurrency-plan.md`) are linked from the docs that
ARE in AGENTS.md's tree (e.g. TECH-SPEC, PRD), not directly from AGENTS.md
itself. Every doc being reachable from AGENTS.md in 0 hops is not the right
invariant — an indirect hop through a doc the reader already chose is fine.

Suggested fix: allow an N-hop (e.g. 2-hop) threshold for reachability, or
let AGENTS.md entries that point to "hub" docs (TECH-SPEC, coding-standards)
implicitly grant reachability to everything those docs link to.