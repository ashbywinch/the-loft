# spike-word-segmentation — the VLM word-segmentation spike's artifacts

Everything the spike (`docs/PLAN/vlm-word-segmentation-spike.md`) produces
that a human or a future agent might want to look at: renders, gold maps,
saved model responses, scores. Inputs live in
`tests/fixtures/page01-wordseg/` (README there); the scan is read from the
archive batch by path.

| Path | What |
|---|---|
| `evidence/` | Renders for the user's checkpoints, one per finding (e.g. `snapshot-diff.png`, `detection-confirm.png`) |
| `gold/` | The trace-derived gold: segments, types, injection points, the attribution map render |
| `responses/` | The VLM's saved JSON per attempt (sha-keyed; re-runs reuse `tools/vlm_cache.py`) |
| `scores/` | The scored comparisons vs the gold |

Naming: `<artifact>-<strategy>.png|json` (e.g. `page01-wholepage`, `page01-ytile-2`).
The LAN preview server (if running) serves this directory at
http://192.168.1.251:8833/ — evidence files are shown to the user there.