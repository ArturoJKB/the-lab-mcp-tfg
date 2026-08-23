"""Read-only SQLite context reader intended for future MCP use.

``ContextReader`` intentionally mirrors a subset of ``ContextRepository``
without any write capability. It never creates directories, never executes
schema mutations, and opens every database connection with ``mode=ro`` and
``PRAGMA query_only=ON``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thelab.contracts import PrivacyLevel

from .contracts import IndexedEntry
from .filters import build_match_query, like_fallback_pattern
from .privacy import AGENT_SAFE_PRIVACY_LEVELS
from .schema import row_to_entry, validate_schema


class ContextReaderError(Exception):
    """Raised for validation or read-only access errors."""


# Defensive query bounds. These are intentionally conservative for an agent
# retrieval surface.
_MAX_QUERY_LEN = 200
_MAX_TAGS = 10
_MAX_TAG_LEN = 64
_MAX_LIMIT = 1000


@dataclass(frozen=True)
class _ReaderState:
    initialized: bool
    schema_ok: bool
    error: str | None
    fts5_available: bool | None


class ContextReader:
    """Read-only accessor for an existing Slice 3 context database."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._state = self._init_state()

    def _init_state(self) -> _ReaderState:
        try:
            if not self._db_path.is_file():
                return _ReaderState(
                    initialized=False,
                    schema_ok=False,
                    error="database does not exist or is not a regular file",
                    fts5_available=None,
                )
        except OSError as exc:
            return _ReaderState(
                initialized=False,
                schema_ok=False,
                error=f"cannot access database path: {exc}",
                fts5_available=None,
            )

        try:
            conn = self._connect_raw()
        except sqlite3.Error as exc:
            return _ReaderState(
                initialized=False,
                schema_ok=False,
                error=f"cannot open database: {exc}",
                fts5_available=None,
            )

        try:
            validate_schema(conn)
            fts5_available = self._check_fts5(conn)
        except (sqlite3.Error, ValueError) as exc:
            return _ReaderState(
                initialized=False,
                schema_ok=False,
                error=f"schema validation failed: {exc}",
                fts5_available=None,
            )
        finally:
            conn.close()

        return _ReaderState(
            initialized=True,
            schema_ok=True,
            error=None,
            fts5_available=fts5_available,
        )

    def _connect_raw(self) -> sqlite3.Connection:
        """Open a fresh read-only connection."""
        uri = f"file:{self._db_path.absolute().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        return conn

    @staticmethod
    def _check_fts5(conn: sqlite3.Connection) -> bool:
        """Return True if SQLite was compiled with FTS5 support."""
        try:
            cursor = conn.execute("PRAGMA compile_options")
            options = {row[0] for row in cursor.fetchall()}
            return "ENABLE_FTS5" in options
        except sqlite3.Error:
            return False

    @property
    def initialized(self) -> bool:
        """True when the database exists and has a compatible schema."""
        return self._state.initialized and self._state.schema_ok

    def status(self) -> dict[str, Any]:
        """Return safe logical status fields; never expose the absolute DB path."""
        result: dict[str, Any] = {
            "indexed": self.initialized,
            "entry_count": self._entry_count() if self.initialized else 0,
            "last_indexed_at": self._last_indexed_at() if self.initialized else None,
            "fts5_available": self._state.fts5_available if self.initialized else False,
        }
        if self._state.error:
            result["error"] = self._state.error
        return result

    @staticmethod
    def _agent_safe_privacy_values() -> list[str]:
        return [level.value for level in AGENT_SAFE_PRIVACY_LEVELS]

    def _entry_count(self) -> int:
        # Status counts must only include rows an agent would be allowed to see.
        privacy_values = self._agent_safe_privacy_values()
        placeholders = ",".join("?" for _ in privacy_values)
        with self._connect_raw() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM entries WHERE privacy_level IN ({placeholders})",
                privacy_values,
            ).fetchone()
            return int(row[0]) if row else 0

    def _last_indexed_at(self) -> str | None:
        # Use the latest indexed timestamp among visible rows only, matching the
        # privacy filtering applied to search/get results.
        privacy_values = self._agent_safe_privacy_values()
        placeholders = ",".join("?" for _ in privacy_values)
        with self._connect_raw() as conn:
            row = conn.execute(
                f"SELECT MAX(indexed_at) FROM entries WHERE privacy_level IN ({placeholders})",
                privacy_values,
            ).fetchone()
            value = row[0] if row else None
            return str(value) if value is not None else None

    def get(
        self,
        event_id: str,
        privacy_levels: Iterable[PrivacyLevel] = AGENT_SAFE_PRIVACY_LEVELS,
    ) -> IndexedEntry | None:
        """Return a single entry by event_id, or None if excluded by privacy."""
        if not self.initialized:
            return None

        privacy_values = self._validate_privacy_levels(privacy_levels)
        with self._connect_raw() as conn:
            row = conn.execute(
                "SELECT *, (SELECT json_group_array(tag) FROM entry_tags "
                "WHERE event_id = entries.event_id) AS tags "
                "FROM entries WHERE event_id = ? AND privacy_level IN "
                f"({','.join('?' for _ in privacy_values)})",
                (event_id, *privacy_values),
            ).fetchone()
            return row_to_entry(row) if row else None

    def search(
        self,
        query: str | None = None,
        run_id: str | None = None,
        tags: list[str] | None = None,
        event_type: str | None = None,
        since: datetime | str | None = None,
        until: datetime | str | None = None,
        limit: int = 50,
        privacy_levels: Iterable[PrivacyLevel] = AGENT_SAFE_PRIVACY_LEVELS,
        exact: bool = False,
    ) -> list[IndexedEntry]:
        """Search indexed entries using FTS5 and structured filters.

        By default only ``public`` and ``internal`` entries are returned;
        ``restricted`` and ``secret`` entries are excluded unless explicitly
        requested through ``privacy_levels``. Plain keyword queries are
        expanded into a prefix OR-query for recall; pass ``exact=True`` to
        use the raw FTS5 expression.
        """
        entries, _ = self.search_with_mode(
            query=query,
            run_id=run_id,
            tags=tags,
            event_type=event_type,
            since=since,
            until=until,
            limit=limit,
            privacy_levels=privacy_levels,
            exact=exact,
        )
        return entries

    def search_with_mode(
        self,
        query: str | None = None,
        run_id: str | None = None,
        tags: list[str] | None = None,
        event_type: str | None = None,
        since: datetime | str | None = None,
        until: datetime | str | None = None,
        limit: int = 50,
        privacy_levels: Iterable[PrivacyLevel] = AGENT_SAFE_PRIVACY_LEVELS,
        exact: bool = False,
    ) -> tuple[list[IndexedEntry], str]:
        """Search and also report how the query was matched.

        Returns ``(entries, match_mode)`` where match_mode is ``"fts"`` for
        exact/passthrough FTS5 matching, ``"expanded"`` for prefix
        OR-expansion, or ``"like"`` when a substring fallback produced the
        results.
        """
        if not self.initialized:
            return [], "fts"

        self._validate_query(query)
        self._validate_tags(tags)
        self._validate_limit(limit)
        since_str = self._normalize_timestamp(since)
        until_str = self._normalize_timestamp(until)
        privacy_values = self._validate_privacy_levels(privacy_levels)

        expression: str | None = None
        mode = "fts"
        if query:
            if exact:
                expression = query
            else:
                expression, mode = build_match_query(query)

        rows = self._execute_search(
            expression=expression,
            run_id=run_id,
            tags=tags,
            event_type=event_type,
            since_str=since_str,
            until_str=until_str,
            limit=limit,
            privacy_values=privacy_values,
        )
        if rows or not query:
            return [row_to_entry(row) for row in rows], mode

        if mode == "expanded":
            fallback = like_fallback_pattern(query)
            if fallback is not None:
                like_clause, like_params = fallback
                rows = self._execute_search(
                    expression=None,
                    run_id=run_id,
                    tags=tags,
                    event_type=event_type,
                    since_str=since_str,
                    until_str=until_str,
                    limit=limit,
                    privacy_values=privacy_values,
                    extra_condition=like_clause,
                    extra_params=like_params,
                )
                if rows:
                    return [row_to_entry(row) for row in rows], "like"

        return [], mode

    def _execute_search(
        self,
        expression: str | None,
        run_id: str | None,
        tags: list[str] | None,
        event_type: str | None,
        since_str: str | None,
        until_str: str | None,
        limit: int,
        privacy_values: list[str],
        extra_condition: str | None = None,
        extra_params: list[Any] | None = None,
    ) -> list[sqlite3.Row]:
        conditions: list[str] = []
        params: list[Any] = []

        if expression is not None:
            conditions.append("entries_fts MATCH ?")
            params.append(expression)

        privacy_placeholders = ",".join("?" for _ in privacy_values)
        conditions.append(f"e.privacy_level IN ({privacy_placeholders})")
        params.extend(privacy_values)

        if run_id is not None:
            conditions.append("e.run_id = ?")
            params.append(run_id)

        if event_type is not None:
            conditions.append("e.event_type = ?")
            params.append(event_type)

        if since_str is not None:
            conditions.append("e.timestamp >= ?")
            params.append(since_str)

        if until_str is not None:
            conditions.append("e.timestamp <= ?")
            params.append(until_str)

        where_clause = " AND ".join(conditions)

        if tags:
            tag_placeholders = ",".join("?" for _ in tags)
            where_clause += (
                f" AND e.event_id IN (SELECT event_id FROM entry_tags "
                f"WHERE tag IN ({tag_placeholders}) "
                f"GROUP BY event_id HAVING COUNT(DISTINCT tag) = ?)"
            )
            params.extend(tags)
            params.append(len(tags))

        if extra_condition is not None:
            where_clause += f" AND ({extra_condition})"
            params.extend(extra_params or [])

        order_by = "rank" if expression is not None else "e.timestamp DESC"
        sql = f"""
            SELECT
                e.*,
                (SELECT json_group_array(tag) FROM entry_tags
                 WHERE event_id = e.event_id) AS tags
            FROM entries e
            {'JOIN entries_fts ON e.rowid = entries_fts.rowid' if expression is not None else ''}
            WHERE {where_clause}
            ORDER BY {order_by}
            LIMIT ?
        """
        params.append(limit)

        with self._connect_raw() as conn:
            try:
                return conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                # Controlled result for malformed FTS5 syntax or read-only
                # conflicts. We deliberately swallow the error and return an
                # empty result set rather than propagate query-language errors.
                return []

    def _validate_query(self, query: str | None) -> None:
        if query is None:
            return
        if not isinstance(query, str):
            raise ContextReaderError("query must be a string")
        if len(query) > _MAX_QUERY_LEN:
            raise ContextReaderError(
                f"query exceeds maximum length of {_MAX_QUERY_LEN} characters"
            )

    def _validate_tags(self, tags: list[str] | None) -> None:
        if tags is None:
            return
        if not isinstance(tags, list) or len(tags) > _MAX_TAGS:
            raise ContextReaderError(
                f"tag count must be between 0 and {_MAX_TAGS}"
            )
        for tag in tags:
            if not isinstance(tag, str) or len(tag) > _MAX_TAG_LEN:
                raise ContextReaderError(
                    f"each tag must be a string of length <= {_MAX_TAG_LEN}"
                )

    def _validate_limit(self, limit: int) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 1
            or limit > _MAX_LIMIT
        ):
            raise ContextReaderError(
                f"limit must be an integer between 1 and {_MAX_LIMIT}"
            )

    def _normalize_timestamp(self, value: datetime | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ContextReaderError(f"invalid ISO timestamp: {exc}") from exc
        if not isinstance(value, datetime):
            raise ContextReaderError(
                "timestamp must be a timezone-aware datetime or ISO string"
            )
        if value.tzinfo is None:
            raise ContextReaderError("timestamp must be timezone-aware")
        return value.astimezone(UTC).isoformat()

    def _validate_privacy_levels(self, privacy_levels: Iterable[PrivacyLevel]) -> list[str]:
        try:
            levels = list(privacy_levels)
        except TypeError as exc:
            raise ContextReaderError(
                "privacy_levels must be an iterable of PrivacyLevel values"
            ) from exc
        if not levels:
            raise ContextReaderError("privacy_levels cannot be empty")
        for level in levels:
            if not isinstance(level, PrivacyLevel):
                raise ContextReaderError(
                    "privacy_levels must contain only PrivacyLevel values"
                )
        return [level.value for level in levels]
