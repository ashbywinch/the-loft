"""The HTR head-to-head: existing tools vs our pipeline on
the SAME real pages. The user's challenge — "are you sure we shouldn't
be using existing tools?" — gets an empirical answer: same pages, same
reference, normalized outputs, honest table. Engines: tesseract (local,
traditional OCR — the faithfulness baseline), kraken (open HTR, trained
on historical scripts), and OUR stored pipeline output (the served
layouts). Transkribus needs the user's cloud account — noted, not run.

Each engine's run over a page is a record — the words or lines it read, or
why it read nothing — and one page's trial is the record its summary row
holds. The records own the JSON in work/eval-htr: a key there is a named
field here, and a run writes only the fields it carries.

Usage: PYTHONPATH=. .venv/bin/python -m pipeline.evals.eval_htr_trial
Writes work/eval-htr/<page>.<engine>.json and prints the table.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from document.rectangle import Rectangle
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


@dataclass(frozen=True)
class OcrWord:
    """One word an engine read: its text, its confidence, and its box."""

    text: str
    conf: float
    box: Rectangle

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OcrWord:
        """The word a written run's ``words`` entry holds."""
        x0, y0, x1, y1 = raw["box"]
        return cls(text=str(raw["text"]), conf=float(raw["conf"]), box=Rectangle(int(x0), int(y0), int(x1), int(y1)))

    def to_dict(self) -> dict[str, Any]:
        """The word as the engine's own record — the box as the four numbers
        the engine states for it, in its order (left, top, right, bottom)."""
        return {"text": self.text, "conf": self.conf, "box": list(self.box)}


@dataclass(frozen=True)
class EngineRun:
    """One engine's run over one page: the words it read, the lines it read,
    or why it read nothing. A field the run does not carry stays off its
    file — that is what keeps tesseract's words, kraken's lines and a
    failure's error text one record."""

    engine: str
    words: list[OcrWord] | None = None
    lines: list[str] | None = None
    error: str | None = None
    note: str | None = None

    @property
    def n(self) -> int:
        """How many records the run read: its words, else its lines."""
        return len(self.words) if self.words is not None else len(self.lines or [])

    @property
    def mean_conf(self) -> float | None:
        """The mean confidence of the words read — None when it read none."""
        if not self.words:
            return None
        return sum(word.conf for word in self.words) / len(self.words)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EngineRun:
        """The run a written engine file holds."""
        words = raw.get("words")
        return cls(
            engine=str(raw["engine"]),
            words=[OcrWord.from_dict(word) for word in words] if words is not None else None,
            lines=raw.get("lines"),
            error=raw.get("error"),
            note=raw.get("note"),
        )

    def to_dict(self) -> dict[str, Any]:
        """The run as its engine's own file — only the fields it carries."""
        out: dict[str, Any] = {"engine": self.engine}
        if self.error is not None:
            out["error"] = self.error
        if self.words is not None:
            out["words"] = [word.to_dict() for word in self.words]
            out["mean_conf"] = self.mean_conf
        if self.lines is not None:
            out["lines"] = list(self.lines)
        if self.words is not None or self.lines is not None:
            out["n"] = self.n
        if self.note is not None:
            out["note"] = self.note
        return out


@dataclass
class PageTrial:
    """One page's trial: why it was picked, and what each engine made of it."""

    page: str
    why: str
    runs: dict[str, EngineRun] = field(default_factory=dict)

    def record(self, run: EngineRun) -> None:
        """File one engine's run under the engine's own name."""
        self.runs[run.engine] = run

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PageTrial:
        """The trial a summary row holds — each engine's run under the
        engine's own key."""
        trial = cls(page=str(raw["page"]), why=str(raw["why"]))
        for run in raw.values():
            if isinstance(run, dict):
                trial.record(EngineRun.from_dict(run))
        return trial

    def to_dict(self) -> dict[str, Any]:
        """The trial as its summary row."""
        out: dict[str, Any] = {"page": self.page, "why": self.why}
        for engine, run in self.runs.items():
            out[engine] = run.to_dict()
        return out


def run_tesseract(image: Path) -> EngineRun:
    """tesseract TSV: per-word text, confidence, and box — the engine's
    own quality signal, available free."""
    out = subprocess.run(
        ["tesseract", str(image), "stdout", "--psm", "11", "tsv"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    words: list[OcrWord] = []
    for line in out.stdout.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) != 12:
            continue
        left, top, width, height, conf, text = parts[6], parts[7], parts[8], parts[9], parts[10], parts[11]
        if not text or text.strip() == "":
            continue
        try:
            words.append(
                OcrWord(
                    text=text,
                    conf=float(conf),
                    box=Rectangle(int(left), int(top), int(left) + int(width), int(top) + int(height)),
                )
            )
        except ValueError:
            continue
    return EngineRun(engine="tesseract", words=words)


def run_kraken(image: Path, python: Path) -> EngineRun:
    """kraken recognition: line boxes + per-line text (no confidence
    exposed by the CLI). The default segmenter requires a bi-level
    image, so a binarized copy is made first."""
    # lucidlint: ignore inline-import this trial tool is removed in the stacked top PR — its findings are moot
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
        return EngineRun(engine="kraken", error=run.stderr[-300:])
    if not out_txt.is_file():
        return EngineRun(engine="kraken", error="no output file; stderr: " + run.stderr[-200:])
    lines = [ln for ln in out_txt.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return EngineRun(engine="kraken", lines=lines)


def load_ours(batch: str, page: str) -> EngineRun:
    """Our pipeline's served output: the stored layout's transcription."""
    layout_path = WORK_DIR / batch / "ocr-guess" / f"{page}.layout.json"
    if not layout_path.is_file():
        return EngineRun(engine="ours", lines=[], note="no stored layout")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    lines = [ln.get("text", "") for ln in layout.get("lines", []) if ln.get("text")]
    return EngineRun(engine="ours", lines=lines)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    kraken_python = Path(".venv-kraken/bin/python")
    trials: list[PageTrial] = []
    for batch, page, why in PAGES:
        image = WORK_DIR / batch / "oriented" / f"{page}.jpg"
        trial = PageTrial(page=page[:26], why=why)
        for engine, fn in [
            ("tesseract", lambda img=image: run_tesseract(img)),
            ("kraken", lambda img=image, kp=kraken_python: run_kraken(img, kp)),
            ("ours", lambda b=batch, p=page: load_ours(b, p)),
        ]:
            try:
                run = fn()
                (OUT_DIR / f"{page}.{engine}.json").write_text(json.dumps(run.to_dict(), indent=1), encoding="utf-8")
                trial.record(run)
            # lucidlint: ignore swallow one engine failing must not sink the comparison — its row carries the error text
            except Exception as exc:
                trial.record(EngineRun(engine=engine, error=str(exc)[:200]))
        trials.append(trial)
        print(f"done {page[:26]}", file=sys.stderr)
    summary = [trial.to_dict() for trial in trials]
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
