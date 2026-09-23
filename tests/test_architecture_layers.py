"""The architecture layers — enforced, not hoped (the repo self-check, §3b).

Layer patterns are ABSOLUTE, derived from the repo root at runtime —
relative or ./-anchored globs match nothing against absolute paths and make
the check pass vacuously (skill://archunitpython-glob-rules).

The layers as designed today (git log records the older rules):
- foundation — the durable contract: the model, the append-only store, and
  the layout/registry seams. Nothing machine- or user-facing above it may
  leak downward into it; it depends only on itself.
- pipeline — the machine stages (reading, layout, transcription).
- server — the app-side services (archive, review, sync, capture...).
- evals — the standalone evaluation harnesses: nothing outside them may
  import one (an eval harness in a production path is a mistake).
"""

from pathlib import Path

from archunitpython import assert_passes, project_layers

ROOT = str(Path(__file__).resolve().parents[1])

FOUNDATION = ("atomic", "loft_paths", "pipeline_store", "records", "registry", "schemas", "store")
PIPELINE = (
    "adopt",
    "ai_client",
    "box",
    "boxjig",
    "boxrows",
    "boxrows_render",
    "classify",
    "gates",
    "grouping",
    "ink",
    "layout",
    "layout_apply_selfreport",
    "layout_detect",
    "layout_stage",
    "line",
    "mark",
    "ocr",
    "page",
    "pagescale",
    "pipeline",
    "reader",
    "reading",
    "rectangle",
    "row",
    "rows",
    "scan",
    "segment_page",
    "selfreport",
    "selfreport_driver",
    "spike_vlm_contract",
    "strip_measure",
    "text",
    "trace",
    "vlm",
    "vlm_cache",
    "word_numbering",
)
SERVER = (
    "archive",
    "attestation",
    "auth",
    "document_capture",
    "gedcom_document",
    "memory",
    "review",
    "server",
    "sync",
    "walk_review",
)
EVALS = (
    "affected_evals",
    "eval_crop_grid",
    "eval_geometry",
    "eval_htr_trial",
    "eval_memory",
    "eval_regions",
    "eval_review",
    "eval_scoring",
    "eval_transkribus",
)


def _build_layers(la):
    for name, modules in (("foundation", FOUNDATION), ("pipeline", PIPELINE), ("server", SERVER), ("evals", EVALS)):
        for module in modules:
            la = la.layer(name).defined_by(f"{ROOT}/tools/{module}.py")
    return la


def test_architecture_layers():
    la = _build_layers(project_layers(ROOT))
    la = la.where_layer("foundation").may_not_depend_on_layers("pipeline", "server", "evals")
    la = la.where_layer("pipeline").may_not_depend_on_layers("evals")
    la = la.where_layer("server").may_not_depend_on_layers("evals")
    assert_passes(la)
