# The test port ledger

Every test that covers a user requirement survives the rewrite. This ledger
maps each existing suite to its new home and the increment that ports it. The
rule is `REWRITE-PLAN.md` "Test first, port first".

## Dispositions

| Disposition | Meaning |
|---|---|
| **keep** | The suite stays where it is. It is the oracle the rewrite must not break; it moves only when its package moves (E1). |
| **port** | Every scenario in the suite moves to the new home in the named increment. The old copy stays green until then. |
| **replace** | The mechanism disappears; every scenario is covered by a named new test. The old copy is deleted only when the new one passes. |

A `replace` row must name the covering test. A `port` row cannot close while a
scenario has no new home. A suite is never deleted for being inconvenient.

## The ledger

| Area | Existing suites | Disposition | Ports in | New home |
|---|---|---|---|---|
| The archive facade and the file store | `tests/test_archive.py`, `tests/test_store.py`, `tests/pipeline/test_store.py` | port | A1–A2, B1–B3 | `tests/live/`, `tests/archive/` |
| The live database | `tests/live/test_*.py` | keep (the new home; it grows into the contract suite) | A1–A2 | `tests/live/` |
| The domain records | `tests/test_records.py` | keep | E1 move | same |
| The CLI surface | `tests/test_cli.py` | port (the path moves in A0; the commands port with their surfaces) | A0, then B1–B6 | `tests/cli/` |
| The live service API | `tests/pipeline/test_server.py`, `tests/pipeline/test_sync.py`, `tests/test_sync.py`, `tests/test_review.py`, `tests/test_approval.py`, `tests/test_review_scoring.py` | port | B3, B4, B7 | `tests/app/api/` |
| The projection and publish | `tests/test_publish.py` | port | B7 | `tests/archive/` |
| The pipeline stages and the scanner | `tests/pipeline/test_adopt.py`, `tests/pipeline/test_classify.py`, `tests/pipeline/test_orient.py`, `tests/pipeline/test_chain.py`, `tests/pipeline/test_grouping.py`, `tests/pipeline/test_worker.py`, `tests/pipeline/test_reconcile_plan.py`, `tests/pipeline/test_identify.py`, `tests/test_scan.py` | port | B6, B8, C2 | `tests/pipeline/` (same names, DB-backed fixtures) |
| The reading, rows and document model | `tests/pipeline/test_reader.py`, `tests/pipeline/test_rows.py`, `tests/pipeline/test_ruler.py`, `tests/pipeline/test_layout.py`, `tests/pipeline/test_render.py`, `tests/pipeline/test_transcripts.py`, `tests/pipeline/test_printed_stage.py`, `tests/pipeline/test_mention.py`, `tests/document/*` | keep (pure domain; no storage) | E1 move | same |
| The model client and its spikes | `tests/pipeline/test_ai_client.py`, `tests/pipeline/test_spike_vlm_contract.py`, `tests/test_vlm.py` | keep | — | same |
| The CI review-post check | `tests/pipeline/test_check_review_posted.py` | keep | — | same |
| Memory and the evals | `tests/test_memory.py`, `tests/test_eval_memory.py`, `tests/test_evals.py`, `tests/test_eval_postcard.py`, `tests/test_eval_scoring.py`, `tests/pipeline/test_eval_review.py`, `tests/pipeline/test_eval_geometry.py` | port the memory scenarios; keep the eval conditions with their module | B5, D7 | `tests/records/`, `tests/evals/` |
| Auth | `tests/pipeline/test_auth.py` | port | C6, D1 | `tests/app/auth/` |
| Archive quality | `tests/test_2060.py`, `tests/test_completeness.py`, `tests/test_attested_edges.py`, `tests/test_content_language.py`, `tests/test_descriptions.py`, `tests/test_place_notes.py`, `tests/test_story_dates.py`, `tests/test_gedcom_document.py`, `tests/test_no_pii_in_repo.py`, `tests/test_pii_markers.py` | port | A8, C7, E3 | `tests/archive/`, `tests/verify/` |
| Boundaries and meta | `tests/test_architecture.py`, `tests/test_architecture_layers.py`, `tests/test_docs_links.py`, `tests/test_standards.py`, `tests/test_prompt_hygiene.py`, `tests/test_placeholders.py`, `tests/test_scaffold.py`, `tests/test_word_numbering.py`, `tests/test_port_ledger.py` | keep (extend the architecture rules) | A1, E1 | same |
| The app | `app/tests/**/*.test.js` | keep; extend for the API and the remote | D3, D10 | `app/tests/` |
| The walk | `tests/test_review_serve_walk.py` | keep (the product-works check every increment) | — | same |

## The gate

- `make test` runs the old and the new suites until E2.
- An increment's PR updates the rows for the surface it moved; a `port` row
  that is still open means the increment is not done.
- E2 retires an old home only when every row for it is `port`ed or
  `replace`d with a passing covering test.
- The review at each milestone checks the ledger against the suite; a suite
  missing from the ledger is a finding.
