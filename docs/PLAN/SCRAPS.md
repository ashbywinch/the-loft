# Scraps — loose ends outside the two plans

| Item | State |
|---|---|
| AGENTS.md's "Finishing the §16.17 single-pass landing" routing row — the plan is complete; the row should go | PR #41 (`docs/remove-routing-row`) is open for it |
| The spike-named modules in the product path — `tools/spike_vlm_contract.py`, `tools/word_numbering.py` (the VLM-segmentation spike's; the row-migration rule: no "spike" naming in `tools/`) | fold/rename when WORK-PLAN 1.1 carries the kind/injection vocabulary |
| `docs/PLAN/ocr-verification-research.md` — synthesis record; its rec/Transkribus directions are ruled out (status banner added 2026-09-22) | done as a record |
| The AI review never runs on a harness push: `the-pr-agent` skips the `synchronize` event when the pusher is a bot ("Skipping synchronize: bot commit detected"), so the workflow's fail-loud check (`pipeline/evals/check_review_posted.py`) fails every PR whose head is a harness-pushed commit | open — the head needs a push from the user's own account for a reviewed head, or the workflow/pusher identity changes |