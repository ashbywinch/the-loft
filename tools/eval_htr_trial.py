"""The HTR head-to-head (2026-08-26): existing tools vs our pipeline on
the SAME real pages. The user's challenge — "are you sure we shouldn't
be using existing tools?" — gets an empirical answer: same pages, same
reference, normalized outputs, honest table. Engines: tesseract (local,
traditional OCR — the faithfulness baseline), kraken (open HTR, trained
on historical scripts), and OUR stored pipeline output (the served
layouts). Transkribus needs the user's cloud account — noted, not run.

Usage: PYTHONPATH=. .venv/bin/python -m tools.eval_htr_trial
Writes work/eval-htr/<page>.<engine>.json and prints the table.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.loft_paths import WORK_DIR

OUT_DIR = WORK_DIR / "eval-htr"

PAGES: list[tuple[str, str, str]] = [
    # (batch, page stem, why representative)
    ("adopt-20260813-201004", "page-03", "cursive letter, our best case"),
    ("adopt-20260813-201004", "page-10", "cursive letter, newly clean"),
    (
        "adopt-20260813-201024",
        "1697568038221-787c9ba9-6924-48e3-a703-9ea9135998fd",
        "postcard: rotated message + print",
    ),
    ("adopt-20260813-201024", "1781706279582-ff480f6a-5ae8-41fc-b606-b42ccc49cbfd", "birth cert: printed form + fills"),
    ("adopt-20260813-201024", "1698767885327-9371821c-1681-4893-89f7-76bff11b3151", "photo pencil captions"),
]


def run_tesseract(image: Path) -> dict:
    """tesseract TSV: per-word text, confidence, and box — the engine's
    own quality signal, available free."""
    out = subprocess.run(
        ["tesseract", str(image), "stdout", "--psm", "11", "tsv"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    words: list[dict] = []
    for line in out.stdout.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) != 12:
            continue
        left, top, width, height, conf, text = parts[6], parts[7], parts[8], parts[9], parts[10], parts[11]
        if not text or text.strip() == "":
            continue
        try:
            words.append(
                {
                    "text": text,
                    "conf": float(conf),
                    "box": [int(left), int(top), int(left) + int(width), int(top) + int(height)],
                }
            )
        except ValueError:
            continue
    return {
        "engine": "tesseract",
        "words": words,
        "mean_conf": sum(w["conf"] for w in words) / len(words) if words else None,
        "n": len(words),
    }


def run_kraken(image: Path, python: Path) -> dict:
    """kraken recognition: line boxes + per-line text (no confidence
    exposed by the CLI). The default segmenter requires a bi-level
    image, so a binarized copy is made first."""
    # lucidlint: ignore inline-import this trial tool is removed in the
    # stacked top PR (pr/remove-trial-code) — its findings are moot
    from PIL import Image as PILImage

    binary = OUT_DIR / f"{image.stem}.bin.png"
    with PILImage.open(image) as im:
        im.convert("L").point(lambda p: 0 if p < 128 else 255).convert("1").save(binary)
    model = "/home/ashby/.local/share/htrmopo/760422c2-087c-59b1-a75a-a24cd07000ea/Tridis_Medieval_EarlyModern.mlmodel"
    out_txt = OUT_DIR / f"{image.stem}.kraken.txt"
    run = subprocess.run(
        [str(python.parent / "kraken"), "-i", str(binary), str(out_txt), "segment", "ocr", "-m", model],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if run.returncode != 0:
        return {"engine": "kraken", "error": run.stderr[-300:]}
    if not out_txt.is_file():
        return {"engine": "kraken", "error": "no output file; stderr: " + run.stderr[-200:]}
    lines = [ln for ln in out_txt.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return {"engine": "kraken", "lines": lines, "n": len(lines)}


def load_ours(batch: str, page: str) -> dict:
    """Our pipeline's served output: the stored layout's transcription."""
    layout_path = WORK_DIR / batch / "ocr-guess" / f"{page}.layout.json"
    if not layout_path.is_file():
        return {"engine": "ours", "lines": [], "n": 0, "note": "no stored layout"}
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    lines = [ln.get("text", "") for ln in layout.get("lines", []) if ln.get("text")]
    return {"engine": "ours", "lines": lines, "n": len(lines)}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    kraken_python = Path(".venv-kraken/bin/python")
    results: list[dict] = []
    for batch, page, why in PAGES:
        image = WORK_DIR / batch / "oriented" / f"{page}.jpg"
        row: dict = {"page": page[:26], "why": why}
        for engine, fn in [
            ("tesseract", lambda img=image: run_tesseract(img)),
            ("kraken", lambda img=image, kp=kraken_python: run_kraken(img, kp)),
            ("ours", lambda b=batch, p=page: load_ours(b, p)),
        ]:
            try:
                out = fn()
                (OUT_DIR / f"{page}.{engine}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
                row[engine] = out
            # lucidlint: ignore swallow one engine failing must not sink
            # the whole comparison — its row carries the error text
            except Exception as exc:
                row[engine] = {"engine": engine, "error": str(exc)[:200]}
        results.append(row)
        print(f"done {page[:26]}", file=sys.stderr)
    (OUT_DIR / "summary.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
