import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

DOC_FILES: tuple[Path, ...] = (
    REPO_ROOT / "AGENTS.md",
    *sorted((REPO_ROOT / "docs").rglob("*.md")),
)


def _relative_links(md_file: Path) -> list[tuple[str, Path]]:
    """The doc's (text, resolved target) pairs for relative links — one
    link's contribution to the check."""
    text = md_file.read_text(encoding="utf-8")
    links: list[tuple[str, Path]] = []
    for match in LINK_RE.finditer(text):
        url = match.group(2).strip()
        if url.startswith("http://") or url.startswith("https://") or url.startswith("#"):
            continue
        if "=" in url or " " in url:
            continue
        # Skip template variables ($1, $2, $ARGUMENTS) used in command files
        if "#$" in url:
            continue
        if "#" in url:
            url = url[: url.index("#")]
        links.append((match.group(1), (md_file.parent / url).resolve()))
    return links


def _link_failure(link_text: str, target: Path, md_file: Path) -> str | None:
    """One link's failure description — None when the link resolves."""
    if not target.is_relative_to(REPO_ROOT):
        return f"{md_file.relative_to(REPO_ROOT)}: link '{link_text}' -> {target} (outside repo)"
    if not target.exists():
        rel_target = target.relative_to(REPO_ROOT)
        return f"{md_file.relative_to(REPO_ROOT)}: link '{link_text}' -> {rel_target}"
    return None


class TestDocLinks(unittest.TestCase):
    # lucidlint: ignore fakefs deterministic tmp_path test — the house testing standard (no pyfakefs)
    def test_all_relative_links_resolve(self):
        failures = [
            failure
            for md_file in DOC_FILES
            for link_text, target in _relative_links(md_file)
            if (failure := _link_failure(link_text, target, md_file)) is not None
        ]
        self.assertEqual(failures, [], f"\n{chr(10)}".join(failures))
