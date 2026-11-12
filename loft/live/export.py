"""The human archive — the dated document leg, its views and its manifest.

TECHSPEC/07 §18.8: one `item.json` per catalogued item, the confirmed text as
plain UTF-8, the confirmed identity tables with basis/confidence, the readable
views, `README.md`, and `manifest.json` + `manifest.sha256`. The images are
never copied: item page refs and the manifest record the scan area's paths and
hashes, and the manifest verifies the document leg.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from loft.live.errors import LiveError
from loft.live.identity_map import date_value
from loft.live.store import LiveStore
from tools.loft_paths import LoftPaths
from tools.records import Item, Org, Person, Place, Relationship
from tools.theme import Theme


class ExportError(LiveError):
    """The human archive cannot be written to this path or is incomplete."""


@dataclass(frozen=True)
class ExportReport:
    """What the export wrote and the counts a reader sees."""

    out: Path
    counts: dict[str, int]
    files: int


@dataclass(frozen=True)
class ExportVerification:
    """The export's self-check: findings, and the counts it compared."""

    findings: tuple[str, ...]
    counts: dict[str, int]

    @property
    def ok(self) -> bool:
        return not self.findings


class HumanArchive:
    """The human archive: the document leg, the views and the manifest."""

    SCHEMA: ClassVar[int] = 2
    SPLIT_AT: ClassVar[int] = 200
    MIN_SIDE: ClassVar[float] = 0.4
    LIVE_ROOTS: ClassVar[tuple[Path, ...]] = (
        LoftPaths.ARCHIVE_DIR,
        LoftPaths.WORKSPACE / "archive",
        LoftPaths.WORKSPACE / "backup",
    )
    VIEWER_EXTRA: ClassVar[tuple[str, ...]] = (
        "told_by",
        "recorded",
        "created",
        "sources",
        "comment_on",
        "clarification",
        "evidence",
        "reflection",
        "kind",
        "facts",
    )
    CONTENT_KINDS: ClassVar[dict[str, str]] = {"story": "story.txt", "transcription": "transcription.txt"}

    def __init__(self, store: LiveStore, out: Path) -> None:
        self.store = store
        self.out = out
        self._items: tuple[Item, ...] = ()
        self._tree: DateTree | None = None

    def write(self) -> ExportReport:
        """Write the human archive to the scratch path."""
        self._check_out()
        self._items = tuple(item for item in self.store.items.all() if item.status == "catalogued")
        self._tree = DateTree(self._items)
        self.out.mkdir(parents=True, exist_ok=True)
        counts = self._write_items()
        counts.update(self._write_identities())
        self._write_views()
        self._write_readme()
        counts["files"] = self._write_manifest()
        return ExportReport(out=self.out, counts=counts, files=counts["files"])

    def verify(self) -> ExportVerification:
        """Verify every file, the counts, and that no draft text was exported."""
        findings: list[str] = []
        self._items = tuple(item for item in self.store.items.all() if item.status == "catalogued")
        self._tree = DateTree(self._items)
        counts = {
            "items": len(self._items),
            "people": sum(1 for person in self.store.people.all() if person.status == "confirmed"),
            "places": sum(1 for place in self.store.places.all() if place.status == "confirmed"),
            "orgs": sum(1 for org in self.store.orgs.all() if org.status == "confirmed"),
            "themes": sum(1 for theme in self.store.themes.all() if self._theme_confirmed(theme)),
            "relationships": len(self._confirmed_relationships()),
        }
        if not (self.out / "manifest.sha256").is_file():
            return ExportVerification(findings=("manifest.sha256 is missing",), counts=counts)
        findings.extend(self._verify_manifest())
        findings.extend(self._verify_items())
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        for key, value in counts.items():
            if manifest.get("counts", {}).get(key) != value:
                findings.append(f"manifest {key} count does not match the store")
        return ExportVerification(findings=tuple(findings), counts=counts)

    # -- the document leg --------------------------------------------------

    def _check_out(self) -> None:
        out = self.out.resolve()
        for root in self.LIVE_ROOTS:
            live = root.resolve()
            if out == live or out.is_relative_to(live) or live.is_relative_to(out):
                raise ExportError(f"refusing to write the human archive inside the live tree: {out}")
        if out.exists() and any(out.iterdir()):
            raise ExportError(f"{out} is not an empty scratch directory")

    def _write_items(self) -> dict[str, int]:
        counts = {"items": 0}
        for item in self._items:
            leaf = self._tree.leaf(item) if self._tree is not None else "All Time"
            directory = self.out / "documents" / leaf / item.id
            directory.mkdir(parents=True, exist_ok=True)
            self._write_json(directory / "item.json", self._item_json(item, directory))
            counts["items"] += 1
        return counts

    def _item_json(self, item: Item, directory: Path) -> dict[str, Any]:
        raw = item.raw
        value = date_value(item.date, item.date_precision, raw.get("date2")) if item.date else None
        data: dict[str, Any] = {
            "schema": self.SCHEMA,
            "id": item.id,
            "type": item.type,
            "title": item.title,
            "date": value,
            "date_text": date_text(value),
            "description": item.description,
            "source": item.source,
            "provenance": item.provenance,
            "sensitive": item.sensitive,
            "people": self._refs(item.id, "person"),
            "places": self._refs(item.id, "place"),
            "orgs": self._refs(item.id, "org"),
            "themes": self._refs(item.id, "theme"),
            "items": self._refs(item.id, "item"),
            "assets": self._asset_refs(item),
        }
        for kind, filename in self.CONTENT_KINDS.items():
            content = next((row for row in self.store.items.contents(item.id) if row.kind == kind), None)
            if content is None:
                continue
            if content.trust == "confirmed":
                data[kind] = filename
                (directory / filename).write_bytes(self.store.items.content(item.id, kind) or b"")
            else:
                data[kind] = "pending"
        for key in self.VIEWER_EXTRA:
            if key in raw:
                data[key] = raw[key]
        return data

    def _refs(self, item_id: str, kind: str) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for ref in self.store.items.refs(item_id):
            if ref.kind != kind or ref.status != "confirmed":
                continue
            entry: dict[str, Any] = {"id": ref.ref_id, "status": "confirmed"}
            entry.update(self._ref_name(kind, ref.ref_id))
            if ref.basis:
                entry["basis"] = ref.basis.get("basis")
                entry["confidence"] = ref.basis.get("confidence")
                for field_name in ("text", "by", "when"):
                    if ref.basis.get(field_name):
                        entry[f"basis_{field_name}"] = ref.basis[field_name]
            refs.append(entry)
        return refs

    def _ref_name(self, kind: str, ref_id: str) -> dict[str, str]:
        if kind == "person":
            person = self.store.people.get(ref_id)
            return {"name": person.name if person else ref_id}
        if kind == "place":
            place = self.store.places.get(ref_id)
            return {"name": place.name if place else ref_id}
        if kind == "org":
            org = self.store.orgs.get(ref_id)
            return {"name": org.name if org else ref_id}
        if kind == "theme":
            theme = self.store.themes.get(ref_id)
            return {"title": theme.title if theme else ref_id}
        item = self.store.items.get(ref_id)
        return {"title": item.title if item else ref_id}

    def _asset_refs(self, item: Item) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for asset in self.store.items.assets(item.id):
            record = self.store.items.asset(asset.asset_id)
            if record is None or record.kind in self.CONTENT_KINDS:
                continue
            if record.sha256 in seen:
                continue
            seen.add(record.sha256)
            refs.append(
                {
                    "kind": record.kind,
                    "file": asset.file,
                    "sha256": record.sha256,
                    "caption": asset.caption,
                    "path": record.path,
                }
            )
        for document in self.store.documents.all():
            if document.item_id != item.id:
                continue
            for page in self.store.documents.pages(document.document_id):
                page_state = self.store.pages.get(page.page_id)
                if page_state is None or page_state.sha256 in seen:
                    continue
                seen.add(page_state.sha256)
                batch_id, _, page_file = page.page_id.partition("/")
                refs.append(
                    {
                        "kind": "page",
                        "file": page_file,
                        "batch": batch_id,
                        "sha256": page_state.sha256,
                        "caption": "",
                    }
                )
        return refs

    # -- the identity tables and views -------------------------------------

    def _write_identities(self) -> dict[str, int]:
        people = [person for person in self.store.people.all() if person.status == "confirmed"]
        places = [place for place in self.store.places.all() if place.status == "confirmed"]
        orgs = [org for org in self.store.orgs.all() if org.status == "confirmed"]
        themes = [theme for theme in self.store.themes.all() if self._theme_confirmed(theme)]
        relationships = self._confirmed_relationships()
        self._write_json(self.out / "people.json", {"people": [self._person(p) for p in people]})
        self._write_json(self.out / "places.json", {"places": [self._place(p) for p in places]})
        self._write_json(self.out / "orgs.json", {"orgs": [self._org(o) for o in orgs]})
        self._write_json(self.out / "themes.json", {"themes": [self._theme(t) for t in themes]})
        self._write_json(
            self.out / "relationships.json",
            {"relationships": [self._relationship(edge) for edge in relationships]},
        )
        return {
            "people": len(people),
            "places": len(places),
            "orgs": len(orgs),
            "themes": len(themes),
            "relationships": len(relationships),
        }

    def _confirmed_relationships(self) -> list[Relationship]:
        return [edge for edge in self.store.relationships.all() if edge.status in (None, "", "confirmed")]

    @staticmethod
    def _with_display(record: dict[str, Any], basis: dict[str, Any] | None) -> dict[str, Any]:
        if basis and basis.get("basis") in ("recollection", "inference") and basis.get("confidence") != "certain":
            record["estimated"] = True
        return record

    def _person(self, person: Person) -> dict[str, Any]:
        record = person.to_dict()
        record.pop("email", None)
        record["status"] = "confirmed"
        return self._with_display(record, person.basis)

    def _place(self, place: Place) -> dict[str, Any]:
        record = place.to_dict()
        record["status"] = "confirmed"
        return self._with_display(record, place.basis)

    @staticmethod
    def _org(org: Org) -> dict[str, Any]:
        record = org.to_dict()
        record["status"] = "confirmed"
        return record

    @staticmethod
    def _theme_confirmed(theme: Theme) -> bool:
        return str(theme.to_dict().get("status", "confirmed")) == "confirmed"

    @staticmethod
    def _theme(theme: Theme) -> dict[str, Any]:
        record = theme.to_dict()
        record["status"] = "confirmed"
        return record

    @staticmethod
    def _relationship(edge: Relationship) -> dict[str, Any]:
        record = edge.to_dict()
        record["status"] = "confirmed"
        return record

    def _write_views(self) -> None:
        people = [person for person in self.store.people.all() if person.status == "confirmed"]
        places = [place for place in self.store.places.all() if place.status == "confirmed"]
        orgs = [org for org in self.store.orgs.all() if org.status == "confirmed"]
        themes = [theme for theme in self.store.themes.all() if self._theme_confirmed(theme)]
        self._write(self.out / "PEOPLE.md", self._people_view(people))
        self._write(self.out / "PLACES.md", self._places_view(places))
        self._write(self.out / "THEMES.md", self._themes_view(themes))
        self._write(self.out / "ORGS.md", self._orgs_view(orgs))
        self._write(self.out / "RELATIONSHIPS.md", self._relationships_view(self._confirmed_relationships()))
        self._write(self.out / "INDEX.md", self._index_view())

    def _people_view(self, people: list[Person]) -> str:
        lines = ["# The people", "", "The cast, as the archive holds them.", ""]
        for person in people:
            lines.extend([f"## {person.name}", ""])
            if person.years and person.years != "—":
                lines.append(f"- Years: {person.years}")
            if person.relation:
                lines.append(f"- Relation: {person.relation}")
            if person.bio:
                lines.append(f"- {person.bio}")
            if person.aliases:
                lines.append(f"- Also known as: {', '.join(person.aliases)}")
            if person.occupations:
                lines.append(f"- Occupations: {', '.join(person.occupations)}")
            if person.residence:
                places = []
                for residence in person.residence:
                    place = self.store.places.get(str(residence.get("place", "")))
                    places.append(place.name if place else str(residence.get("place", "")))
                lines.append(f"- Lived at: {', '.join(places)}")
            lines.extend([""])
        return "\n".join(lines)

    def _places_view(self, places: list[Place]) -> str:
        lines = ["# The places", "", ""]
        for place in places:
            lines.extend([f"## {place.name}", ""])
            if place.address:
                lines.append(f"- Address: {place.address}")
            if place.note:
                lines.append(f"- {place.note}")
            if place.precision:
                lines.append(f"- Precision: {place.precision}")
            lines.append("")
        return "\n".join(lines)

    def _themes_view(self, themes: list[Theme]) -> str:
        lines = ["# The story doors", "", ""]
        for theme in themes:
            lines.extend([f"## {theme.title}", ""])
            subtitle = str(theme.to_dict().get("subtitle", ""))
            if subtitle:
                lines.append(subtitle)
                lines.append("")
            for entry in theme.to_dict().get("items") or []:
                item = self.store.items.get(str(entry.get("id", "")))
                lines.append(f"- {item.title if item else entry.get('id', '')}")
            lines.append("")
        return "\n".join(lines)

    def _orgs_view(self, orgs: list[Org]) -> str:
        lines = ["# The organisations", "", ""]
        for org in orgs:
            lines.extend([f"## {org.name}", ""])
            if org.address:
                lines.append(f"- Address: {org.address}")
            if org.branch:
                lines.append(f"- Branch: {org.branch}")
            if org.note:
                lines.append(f"- {org.note}")
            lines.append("")
        return "\n".join(lines)

    def _relationships_view(self, edges: list[Relationship]) -> str:
        lines = ["# The family edges", "", ""]
        for edge in edges:
            a = self.store.people.get(edge.a)
            b = self.store.people.get(edge.b)
            labels = " / ".join(label for label in (edge.label_a, edge.label_b) if label)
            suffix = f" ({labels})" if labels else ""
            lines.append(f"- {a.name if a else edge.a} — {edge.kind} — {b.name if b else edge.b}{suffix}")
        lines.append("")
        return "\n".join(lines)

    def _index_view(self) -> str:
        lines = ["# The archive", "", "The dated index; open a leaf to read the words.", ""]
        by_year: dict[str, list[Item]] = {}
        for item in self._items:
            year = item.date[:4] if len(item.date) >= 4 else "Undated"
            by_year.setdefault(year, []).append(item)
        for year in sorted(by_year):
            lines.extend([f"## {year}", ""])
            for item in sorted(by_year[year], key=lambda entry: (entry.date, entry.title)):
                leaf = self._tree.leaf(item) if self._tree is not None else "All Time"
                content = next(
                    (row for row in self.store.items.contents(item.id) if row.kind in self.CONTENT_KINDS), None
                )
                target = (
                    f"documents/{leaf}/{item.id}/{self.CONTENT_KINDS[content.kind]}"
                    if content is not None and content.trust == "confirmed"
                    else f"documents/{leaf}/{item.id}/item.json"
                )
                label = item.date or "Undated"
                lines.append(f"- {label} — [{item.title}](<{target}>)")
            lines.append("")
        return "\n".join(lines)

    # -- the manifest and the README ---------------------------------------

    def _write_readme(self) -> None:
        self._write(
            self.out / "README.md",
            "\n".join(
                [
                    "# The Loft — the human archive",
                    "",
                    "This is the family archive as a person reads it. It is the **document leg**:",
                    "the dated `documents/` tree, the confirmed text, the identity tables and the",
                    "readable views. The **image leg** is the scan area; the page references in",
                    "`item.json` and `manifest.json` name each scan by batch, path and sha256.",
                    "",
                    "## Read it",
                    "",
                    "- `INDEX.md` — the dated index, linking into `documents/`.",
                    "- `documents/` — one folder per item: `item.json` (who, where, when) and the",
                    "  confirmed `transcription.txt` or `story.txt` when the words are confirmed.",
                    "- `PEOPLE.md`, `PLACES.md`, `THEMES.md`, `ORGS.md`, `RELATIONSHIPS.md` — the",
                    "  human renders of the JSON tables beside them.",
                    "",
                    "JSON is the machine form; Markdown is the human form. Both are generated from",
                    "the live database; edit neither by hand.",
                    "",
                    "## Verify it",
                    "",
                    "Run `sha256sum -c manifest.sha256` in this folder. `manifest.json` records the",
                    "exported point, the counts and every page's current path and hash. A moved",
                    "scan is re-found by its sha256.",
                    "",
                    "No app, no database and no network are needed to read this tree.",
                    "",
                    "## Restore the system",
                    "",
                    "This is a publication, not a backup. The **operational backup** (`db.sql`,",
                    "`content/`, `events/`, the schema and the manifest) restores the full system,",
                    "including drafts and history. See its `README.md`.",
                    "",
                ]
            ),
        )

    def _write_manifest(self) -> int:
        pages: list[dict[str, Any]] = []
        for batch in self.store.batches.all():
            for scan in self.store.batches.scans(batch.batch_id):
                pages.append(
                    {
                        "batch": batch.batch_id,
                        "page": scan.page_id.partition("/")[2],
                        "path": scan.path,
                        "sha256": scan.sha256,
                    }
                )
        assets: dict[str, dict[str, Any]] = {}
        for item in self._items:
            for asset in self.store.items.assets(item.id):
                record = self.store.items.asset(asset.asset_id)
                if record is not None and record.kind not in self.CONTENT_KINDS:
                    assets[record.path] = {"path": record.path, "sha256": record.sha256, "kind": record.kind}
        manifest = {
            "schema": self.SCHEMA,
            "exported_through": int(
                self.store.connection.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]
            ),
            "exported_at": datetime.now(UTC).isoformat(),
            "counts": {
                "items": len(self._items),
                "people": sum(1 for person in self.store.people.all() if person.status == "confirmed"),
                "places": sum(1 for place in self.store.places.all() if place.status == "confirmed"),
                "orgs": sum(1 for org in self.store.orgs.all() if org.status == "confirmed"),
                "themes": sum(1 for theme in self.store.themes.all() if self._theme_confirmed(theme)),
                "relationships": len(self._confirmed_relationships()),
                "pages": len(pages),
                "assets": len(assets),
            },
            "pages": pages,
            "assets": list(assets.values()),
        }
        self._write_json(self.out / "manifest.json", manifest)
        files = sorted(
            path.relative_to(self.out).as_posix()
            for path in self.out.rglob("*")
            if path.is_file() and path.name != "manifest.sha256"
        )
        lines = [f"{_sha(self.out / name)}  {name}" for name in files]
        self._write(self.out / "manifest.sha256", "\n".join(lines) + "\n")
        return len(files) + 1

    # -- checks ------------------------------------------------------------

    def _verify_manifest(self) -> list[str]:
        findings: list[str] = []
        listed: set[str] = set()
        for line in (self.out / "manifest.sha256").read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            digest, _, name = line.partition("  ")
            listed.add(name)
            path = self.out / name
            if not path.is_file():
                findings.append(f"manifest lists a missing file: {name}")
            elif _sha(path) != digest:
                findings.append(f"{name} does not match its sha256")
        actual = {
            path.relative_to(self.out).as_posix()
            for path in self.out.rglob("*")
            if path.is_file() and path.name != "manifest.sha256"
        }
        if actual - listed:
            findings.append(f"files not in manifest.sha256: {sorted(actual - listed)}")
        return findings

    def _verify_items(self) -> list[str]:
        findings: list[str] = []
        exported = {path.parent.name for path in (self.out / "documents").rglob("item.json")}
        expected = {item.id for item in self._items}
        if exported != expected:
            findings.append(
                f"item leaves differ: missing {sorted(expected - exported)}, extra {sorted(exported - expected)}"
            )
        for item in self._items:
            directory = self._leaf_dir(item)
            if not (directory / "item.json").is_file():
                findings.append(f"item {item.id} has no item.json")
                continue
            data = json.loads((directory / "item.json").read_text(encoding="utf-8"))
            for kind, filename in self.CONTENT_KINDS.items():
                content = next((row for row in self.store.items.contents(item.id) if row.kind == kind), None)
                if content is None:
                    continue
                if content.trust == "confirmed":
                    if data.get(kind) != filename or not (directory / filename).is_file():
                        findings.append(f"item {item.id} {kind} was not exported as confirmed text")
                elif data.get(kind) != "pending" or (directory / filename).is_file():
                    findings.append(f"item {item.id} {kind} was exported despite being a draft")
        return findings

    def _leaf_dir(self, item: Item) -> Path:
        leaf = self._tree.leaf(item) if self._tree is not None else "All Time"
        return self.out / "documents" / leaf / item.id

    # -- file helpers ------------------------------------------------------

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")


class DateTree:
    """The date partitioner: `All Time` split at 200 items, never recomputed."""

    def __init__(self, items: tuple[Item, ...]) -> None:
        self.leaves: dict[str, str] = {}
        self._split("All Time", list(items))

    def leaf(self, item: Item) -> str:
        return self.leaves.get(item.id, "All Time")

    def _split(self, prefix: str, items: list[Item]) -> None:
        if len(items) <= HumanArchive.SPLIT_AT:
            self._assign(prefix, items)
            return
        dated = [item for item in items if item.date]
        undated = [item for item in items if not item.date]
        self._assign(prefix, undated)
        if len(dated) <= 1:
            self._assign(prefix, dated)
            return
        dates = sorted(item.date for item in dated)
        median = dates[len(dates) // 2]
        label = f"{median[:7]}-01" if len(median) >= 7 else median
        left = [item for item in dated if item.date < label]
        right = [item for item in dated if item.date >= label]
        if len(left) / len(dated) < HumanArchive.MIN_SIDE or len(right) / len(dated) < HumanArchive.MIN_SIDE:
            label = median
            left = [item for item in dated if item.date < label]
            right = [item for item in dated if item.date >= label]
        if len(left) / len(dated) < HumanArchive.MIN_SIDE or len(right) / len(dated) < HumanArchive.MIN_SIDE:
            self._assign(prefix, dated)
            return
        self._split(f"{prefix}/Before {label}", left)
        self._split(f"{prefix}/On or after {label}", right)

    def _assign(self, prefix: str, items: list[Item]) -> None:
        for item in items:
            self.leaves[item.id] = prefix


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def date_text(value: dict[str, Any] | None) -> str:
    """The display form of a DateValue — a person reads '14 May 1963'."""
    if not value:
        return ""
    if value.get("phrase"):
        return str(value["phrase"])
    qualifier = value.get("qualifier")
    range_kind = value.get("range")
    if range_kind == "before":
        return f"before {_parts_text(value.get('to'))}"
    if range_kind == "after":
        return f"after {_parts_text(value.get('from'))}"
    if range_kind == "between":
        return f"between {_parts_text(value.get('from'))} and {_parts_text(value.get('to'))}"
    text = _parts_text(value.get("from"))
    if qualifier == "about":
        return f"about {text}"
    if qualifier in ("estimated", "calculated"):
        return f"{text} ({qualifier})"
    return text


def _parts_text(parts: dict[str, int] | None) -> str:
    if not parts:
        return ""
    year = parts.get("year", "")
    month = parts.get("month")
    day = parts.get("day")
    months = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )
    if day and month:
        return f"{day} {months[month - 1]} {year}"
    if month:
        return f"{months[month - 1]} {year}"
    return str(year)
