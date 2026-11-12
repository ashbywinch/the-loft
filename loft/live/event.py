"""The event log's hash recipe — one frozen column list, never `SELECT *`.

TECHSPEC/05 §18.2: `hash = sha256(canonical(event))` over the fifteen frozen
columns, with the *stored* payload string (not a re-serialisation). Adding a
column in a migration leaves historical hashes valid.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


class EventHash:
    """The one frozen column list the event hash is taken over."""

    COLUMNS: tuple[str, ...] = (
        "event_id",
        "change_id",
        "entity_kind",
        "entity_id",
        "event_no",
        "entity_version",
        "event_type",
        "payload",
        "payload_schema",
        "recorded_at",
        "actor_kind",
        "actor_id",
        "command_id",
        "app_version",
        "prev_hash",
    )


def canonical_event(record: Mapping[str, Any]) -> str:
    """The canonical JSON the hash is taken over — sorted keys, no spaces."""
    return json.dumps(
        {column: record[column] for column in EventHash.COLUMNS},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def event_hash(record: Mapping[str, Any]) -> str:
    """The event's sha256 over the frozen columns."""
    return hashlib.sha256(canonical_event(record).encode("utf-8")).hexdigest()
