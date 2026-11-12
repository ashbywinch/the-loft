"""The one-shot migration — the four importers in order, and the A7 gate.

TECHSPEC/11 §The order: identities, items/content, imports/review sessions,
then the pipeline (registry, pages, readings, documents). The run is a dry-run
plan first when verifying, then the real import; the gate compares the two
operation lists and checks the store against the old tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loft.live.import_identity import IdentityReport, import_identities
from loft.live.import_items import ItemReport, import_items
from loft.live.import_pipeline import PipelineReport, import_pipeline
from loft.live.import_reviews import ReviewReport, import_reviews
from loft.live.store import LiveStore
from loft.live.verify import Verification, VerificationReport, tree_digest


@dataclass(frozen=True)
class MigrationRun:
    """What one migration pass did — the four reports and their operations."""

    identities: IdentityReport
    items: ItemReport
    reviews: ReviewReport
    pipeline: PipelineReport
    dry_run: bool = False

    @property
    def operations(self) -> tuple[str, ...]:
        return tuple(
            [f"identity {operation}" for operation in self.identities.operations]
            + list(self.items.operations)
            + list(self.reviews.operations)
            + list(self.pipeline.operations)
        )

    @property
    def mismatches(self) -> tuple[str, ...]:
        return self.identities.mismatches + self.items.mismatches + self.reviews.mismatches + self.pipeline.mismatches

    @property
    def counts(self) -> dict[str, int]:
        merged: dict[str, int] = {}
        for prefix, report in (
            ("identities", self.identities.counts),
            ("items", self.items.counts),
            ("reviews", self.reviews.counts),
            ("pipeline", self.pipeline.counts),
        ):
            for key, value in report.items():
                merged[f"{prefix}.{key}"] = value
        return merged


@dataclass(frozen=True)
class VerificationInputs:
    """The sources and before-state the gate compares against."""

    archive_dir: Path
    workspace: Path
    dry_operations: tuple[str, ...]
    tree_before: str


def migrate(
    store: LiveStore,
    *,
    archive_dir: Path,
    workspace: Path,
    backup_marker: Path,
    dry_run: bool = False,
) -> MigrationRun:
    """Run the four importers in the migration's order."""
    return MigrationRun(
        identities=import_identities(store, archive_dir, backup_marker=backup_marker, dry_run=dry_run),
        items=import_items(store, archive_dir, backup_marker=backup_marker, dry_run=dry_run),
        reviews=import_reviews(store, archive_dir, backup_marker=backup_marker, dry_run=dry_run),
        pipeline=import_pipeline(store, workspace, backup_marker=backup_marker, dry_run=dry_run),
        dry_run=dry_run,
    )


def verify(store: LiveStore, run: MigrationRun, inputs: VerificationInputs) -> VerificationReport:
    """The A7 gate: counts, versions, bytes, records, sample, rebuild, tree."""
    tree_after = tree_digest((inputs.archive_dir, inputs.workspace / "registry", inputs.workspace / "work"))
    return Verification(store, archive_dir=inputs.archive_dir, workspace=inputs.workspace).findings_for(
        dry_operations=inputs.dry_operations,
        executed_operations=run.operations,
        tree_before=inputs.tree_before,
        tree_after=tree_after,
    )
