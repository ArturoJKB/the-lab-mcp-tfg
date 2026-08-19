"""Shared schema metadata and row normalization for the context store.

This module is imported by both the write-side ``ContextRepository`` and the
read-only ``ContextReader`` so both agree on the expected SQLite shape.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from thelab.contracts import ArtifactRef, EventType, PrivacyLevel

from .contracts import IndexedEntry

# Tables that must exist for the context store to be considered initialized.
EXPECTED_TABLES: set[str] = {"entries", "entry_tags", "entries_fts"}

# Columns that must exist on the ``entries`` table.
EXPECTED_ENTRY_COLUMNS: set[str] = {
    "rowid",
    "event_id",
    "event_type",
    "session_id",
    "run_id",
    "redacted_summary",
    "related_artifact_refs",
    "privacy_level",
    "timestamp",
    "content_hash",
    "indexed_at",
}


def row_to_entry(row: sqlite3.Row) -> IndexedEntry:
    """Convert an SQLite result row into an ``IndexedEntry``."""
    refs_raw = row["related_artifact_refs"]
    refs: list[ArtifactRef] = []
    if refs_raw:
        try:
            for item in json.loads(refs_raw):
                if isinstance(item, dict) and isinstance(item.get("relative_path"), str):
                    item = {**item, "relative_path": Path(item["relative_path"])}
                refs.append(ArtifactRef.model_validate(item))
        except Exception:
            refs = []

    return IndexedEntry(
        event_id=row["event_id"],
        event_type=EventType(row["event_type"]),
        session_id=row["session_id"],
        run_id=row["run_id"],
        tags=json.loads(row["tags"]) if row["tags"] else [],
        redacted_summary=row["redacted_summary"],
        related_artifact_refs=refs,
        privacy_level=PrivacyLevel(row["privacy_level"]),
        timestamp=datetime.fromisoformat(row["timestamp"]),
        content_hash=row["content_hash"],
        indexed_at=datetime.fromisoformat(row["indexed_at"]),
    )


def validate_schema(conn: sqlite3.Connection) -> None:
    """Raise ``ValueError`` if the database schema is incompatible.

    This is a read-only check: it queries ``sqlite_master`` and
    ``PRAGMA table_info`` but never creates, alters, or drops objects.
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?)",
        tuple(EXPECTED_TABLES),
    )
    found_tables = {row[0] for row in cursor.fetchall()}
    missing_tables = EXPECTED_TABLES - found_tables
    if missing_tables:
        raise ValueError(f"missing required tables: {sorted(missing_tables)}")

    cursor = conn.execute("PRAGMA table_info(entries)")
    found_columns = {row["name"] for row in cursor.fetchall()}
    missing_columns = EXPECTED_ENTRY_COLUMNS - found_columns
    if missing_columns:
        raise ValueError(f"missing required columns in entries: {sorted(missing_columns)}")
