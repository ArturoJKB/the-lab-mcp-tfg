"""SQLite + FTS5 repository for local context entries."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import IndexedEntry
from .filters import build_match_query
from .schema import row_to_entry


class ContextRepositoryError(Exception):
    """Base exception for context repository failures."""


class ContentMismatchError(ContextRepositoryError):
    """Raised when the same event_id is indexed with different content."""


class FTS5NotAvailableError(ContextRepositoryError):
    """Raised when the SQLite build does not include FTS5."""


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entries (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    event_type TEXT NOT NULL,
    session_id TEXT NOT NULL,
    run_id TEXT,
    redacted_summary TEXT NOT NULL,
    related_artifact_refs TEXT NOT NULL DEFAULT '[]',
    privacy_level TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    redacted_summary,
    content='entries',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS entries_fts_insert AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, redacted_summary) VALUES (new.rowid, new.redacted_summary);
END;

CREATE TRIGGER IF NOT EXISTS entries_fts_update AFTER UPDATE ON entries BEGIN
    UPDATE entries_fts SET redacted_summary = new.redacted_summary WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS entries_fts_delete AFTER DELETE ON entries BEGIN
    DELETE FROM entries_fts WHERE rowid = old.rowid;
END;

CREATE TABLE IF NOT EXISTS entry_tags (
    event_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (event_id, tag),
    FOREIGN KEY (event_id) REFERENCES entries(event_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_entries_run_id ON entries(run_id);
CREATE INDEX IF NOT EXISTS idx_entries_event_type ON entries(event_type);
CREATE INDEX IF NOT EXISTS idx_entries_timestamp ON entries(timestamp);
"""


def _check_fts5(conn: sqlite3.Connection) -> None:
    """Raise FTS5NotAvailableError if FTS5 is not available."""
    try:
        conn.execute("CREATE VIRTUAL TABLE _fts5_probe USING fts5(x)")
    except sqlite3.OperationalError as exc:
        raise FTS5NotAvailableError("SQLite FTS5 extension is not available") from exc
    else:
        conn.execute("DROP TABLE _fts5_probe")


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply additive schema migrations to existing Slice 3 databases.

    Migrations are additive only. Removed columns (e.g., an old ``visibility``
    column) are left untouched in existing databases; they are simply no longer
    read or written.
    """
    # Ensure related_artifact_refs column exists (added after initial Slice 3).
    cursor = conn.execute("PRAGMA table_info(entries)")
    columns = {row["name"] for row in cursor.fetchall()}
    if "related_artifact_refs" not in columns:
        conn.execute(
            "ALTER TABLE entries ADD COLUMN related_artifact_refs TEXT NOT NULL DEFAULT '[]'"
        )


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class ContextRepository:
    """SQLite repository for indexed context entries with FTS5 search."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._ensure_db()

    def _ensure_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            _check_fts5(conn)
            conn.executescript(_SCHEMA_SQL)
            _migrate(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def upsert(self, entry: IndexedEntry) -> bool:
        """Insert or skip *entry* based on event_id and content_hash.

        Returns True if a row was inserted/updated, False if the same event was
        already present with identical content.

        Raises ContentMismatchError if the same event_id exists with a different
        content_hash.
        """
        conn = self._connect()
        try:
            with conn:
                existing = conn.execute(
                    "SELECT content_hash FROM entries WHERE event_id = ?",
                    (entry.event_id,),
                ).fetchone()
                if existing is not None:
                    if existing["content_hash"] == entry.content_hash:
                        return False
                    raise ContentMismatchError(
                        f"event_id {entry.event_id!r} already exists with different content"
                    )

                conn.execute(
                    """
                    INSERT INTO entries (
                        event_id, event_type, session_id, run_id, redacted_summary,
                        related_artifact_refs, privacy_level, timestamp, content_hash, indexed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.event_id,
                        entry.event_type,
                        entry.session_id,
                        entry.run_id,
                        entry.redacted_summary,
                        json.dumps(
                            [ref.model_dump(mode="json") for ref in entry.related_artifact_refs]
                        ),
                        entry.privacy_level,
                        entry.timestamp.astimezone(UTC).isoformat(),
                        entry.content_hash,
                        _utcnow_iso(),
                    ),
                )
                for tag in entry.tags:
                    conn.execute(
                        "INSERT OR IGNORE INTO entry_tags (event_id, tag) VALUES (?, ?)",
                        (entry.event_id, tag),
                    )
                return True
        finally:
            conn.close()

    def get(self, event_id: str) -> IndexedEntry | None:
        """Return the indexed entry for *event_id*, or None."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT *, (SELECT json_group_array(tag) FROM entry_tags WHERE event_id = entries.event_id) AS tags "
                "FROM entries WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            return row_to_entry(row) if row else None
        finally:
            conn.close()

    def search(
        self,
        query: str | None = None,
        run_id: str | None = None,
        tags: list[str] | None = None,
        event_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> list[IndexedEntry]:
        """Search indexed entries using FTS5 and structured filters."""
        tags = tags or []
        conditions: list[str] = []
        params: list[Any] = []

        if query:
            expression, _mode = build_match_query(query)
            conditions.append("entries_fts MATCH ?")
            params.append(expression)

        if run_id is not None:
            conditions.append("e.run_id = ?")
            params.append(run_id)

        if event_type is not None:
            conditions.append("e.event_type = ?")
            params.append(event_type)

        if since is not None:
            conditions.append("e.timestamp >= ?")
            params.append(since.isoformat())

        if until is not None:
            conditions.append("e.timestamp <= ?")
            params.append(until.isoformat())

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        if tags:
            tag_placeholders = ",".join("?" for _ in tags)
            where_clause += (
                f" AND e.event_id IN (SELECT event_id FROM entry_tags WHERE tag IN ({tag_placeholders})"
                f" GROUP BY event_id HAVING COUNT(DISTINCT tag) = ?)"
            )
            params.extend(tags)
            params.append(len(tags))

        order_by = "rank" if query else "e.timestamp DESC"
        sql = f"""
            SELECT
                e.*,
                (SELECT json_group_array(tag) FROM entry_tags WHERE event_id = e.event_id) AS tags
            FROM entries e
            {'JOIN entries_fts ON e.rowid = entries_fts.rowid' if query else ''}
            WHERE {where_clause}
            ORDER BY {order_by}
            LIMIT ?
        """
        params.append(limit)

        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [row_to_entry(row) for row in rows]
        finally:
            conn.close()

    def status(self) -> dict[str, Any]:
        """Return repository status metadata.

        The database path is redacted to a relative or basename form so that
        absolute filesystem paths are not leaked to agents or UI consumers.
        """
        conn = self._connect()
        try:
            entry_count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            indexed_at = conn.execute("SELECT MAX(indexed_at) FROM entries").fetchone()[0]
            return {
                "db_path": str(self.db_path.name),
                "entry_count": entry_count,
                "last_indexed_at": indexed_at,
                "fts5_available": True,
            }
        finally:
            conn.close()
