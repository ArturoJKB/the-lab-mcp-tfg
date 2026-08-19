import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from thelab.context.contracts import IndexedEntry
from thelab.context.reader import ContextReader, ContextReaderError
from thelab.context.repository import ContextRepository
from thelab.contracts import EventType, PrivacyLevel


def _make_entry(event_id: str, summary: str, **kwargs) -> IndexedEntry:
    return IndexedEntry(
        event_id=event_id,
        event_type=EventType(kwargs.get("event_type", "system")),
        session_id=kwargs.get("session_id", "session-1"),
        run_id=kwargs.get("run_id"),
        tags=kwargs.get("tags", []),
        redacted_summary=summary,
        related_artifact_refs=kwargs.get("related_artifact_refs", []),
        privacy_level=PrivacyLevel(kwargs.get("privacy_level", "internal")),
        timestamp=kwargs.get("timestamp", datetime.now(UTC)),
        content_hash=kwargs.get("content_hash", f"hash-{event_id}"),
    )


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reader_does_not_create_missing_db_or_parent(tmp_path):
    missing_parent = tmp_path / "does" / "not" / "exist"
    missing_db = missing_parent / "context.db"
    reader = ContextReader(missing_db)

    assert reader.status()["indexed"] is False
    assert reader.search("anything") == []
    assert reader.get("anything") is None

    assert not missing_db.exists()
    assert not missing_parent.exists()


def test_reader_queries_do_not_modify_db_byte_for_byte(tmp_path):
    db = tmp_path / "context.db"
    repo = ContextRepository(db)
    repo.upsert(_make_entry("evt-1", "hello world"))

    before = _hash_file(db)
    reader = ContextReader(db)

    assert reader.status()["indexed"] is True
    reader.search("hello")
    reader.search("world")
    reader.get("evt-1")
    reader.get("missing")
    reader.search(None, limit=10)

    after = _hash_file(db)
    assert before == after


def test_status_does_not_expose_db_path(tmp_path):
    db = tmp_path / "context.db"
    repo = ContextRepository(db)
    repo.upsert(_make_entry("evt-1", "hello"))

    reader = ContextReader(db)
    status = reader.status()
    assert "db_path" not in status
    assert status["indexed"] is True
    assert status["entry_count"] == 1
    assert "last_indexed_at" in status
    assert "fts5_available" in status


def test_status_reports_uninitialized_state(tmp_path):
    reader = ContextReader(tmp_path / "missing.db")
    status = reader.status()
    assert status["indexed"] is False
    assert status["entry_count"] == 0
    assert status["last_indexed_at"] is None
    assert status["fts5_available"] is False
    assert "error" in status


def test_status_reports_incompatible_schema(tmp_path):
    db = tmp_path / "not-context.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    reader = ContextReader(db)
    status = reader.status()
    assert status["indexed"] is False
    assert "error" in status
    assert "schema" in status["error"].lower()


def test_malformed_fts_query_returns_empty(tmp_path):
    db = tmp_path / "context.db"
    repo = ContextRepository(db)
    repo.upsert(_make_entry("evt-1", "hello world"))

    reader = ContextReader(db)
    # Unmatched double quote is invalid FTS5 syntax.
    assert reader.search('"unmatched') == []


def test_limit_bounds(tmp_path):
    db = tmp_path / "context.db"
    repo = ContextRepository(db)
    repo.upsert(_make_entry("evt-1", "hello"))
    reader = ContextReader(db)

    with pytest.raises(ContextReaderError):
        reader.search(limit=0)
    with pytest.raises(ContextReaderError):
        reader.search(limit=-1)
    with pytest.raises(ContextReaderError):
        reader.search(limit=1001)
    with pytest.raises(ContextReaderError):
        reader.search(limit=True)  # bool is a subclass of int

    assert len(reader.search(limit=1)) == 1


def test_query_length_bound(tmp_path):
    db = tmp_path / "context.db"
    repo = ContextRepository(db)
    repo.upsert(_make_entry("evt-1", "hello"))
    reader = ContextReader(db)

    long_query = "a" * 201
    with pytest.raises(ContextReaderError):
        reader.search(long_query)
    assert reader.search("a" * 200) == []


def test_tag_count_and_length_bounds(tmp_path):
    db = tmp_path / "context.db"
    repo = ContextRepository(db)
    repo.upsert(_make_entry("evt-1", "hello"))
    reader = ContextReader(db)

    with pytest.raises(ContextReaderError):
        reader.search(tags=["t"] * 11)
    with pytest.raises(ContextReaderError):
        reader.search(tags=["a" * 65])

    assert reader.search(tags=["hello"]) == []


def test_naive_timestamp_rejected(tmp_path):
    db = tmp_path / "context.db"
    repo = ContextRepository(db)
    repo.upsert(_make_entry("evt-1", "hello"))
    reader = ContextReader(db)

    naive = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ContextReaderError):
        reader.search(since=naive)


def test_timezone_aware_timestamp_normalized_to_utc(tmp_path):
    db = tmp_path / "context.db"
    repo = ContextRepository(db)
    t = datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    repo.upsert(_make_entry("evt-1", "hello", timestamp=t))
    reader = ContextReader(db)

    # The entry is at 12:00 UTC. Searching since 13:00+02:00 (11:00 UTC) finds it.
    results = reader.search(since="2026-01-01T13:00:00+02:00")
    assert len(results) == 1

    # Searching since 13:00 UTC does not find it.
    results = reader.search(since="2026-01-01T13:00:00+00:00")
    assert len(results) == 0

    # Naive ISO string is rejected.
    with pytest.raises(ContextReaderError):
        reader.search(since="2026-01-01T13:00:00")


def test_default_privacy_filter_excludes_restricted_and_secret(tmp_path):
    db = tmp_path / "context.db"
    repo = ContextRepository(db)
    repo.upsert(_make_entry("evt-public", "hello", privacy_level="public"))
    repo.upsert(_make_entry("evt-internal", "hello", privacy_level="internal"))
    repo.upsert(_make_entry("evt-restricted", "hello", privacy_level="restricted"))
    repo.upsert(_make_entry("evt-secret", "hello", privacy_level="secret"))

    reader = ContextReader(db)
    results = reader.search("hello")
    assert {r.event_id for r in results} == {"evt-public", "evt-internal"}

    assert reader.get("evt-public") is not None
    assert reader.get("evt-internal") is not None
    assert reader.get("evt-restricted") is None
    assert reader.get("evt-secret") is None

    # Explicit override can retrieve restricted entries.
    assert (
        reader.get(
            "evt-restricted",
            privacy_levels=[PrivacyLevel.public, PrivacyLevel.internal, PrivacyLevel.restricted],
        )
        is not None
    )


def test_get_existing_entry(tmp_path):
    db = tmp_path / "context.db"
    repo = ContextRepository(db)
    repo.upsert(_make_entry("evt-1", "hello world"))

    reader = ContextReader(db)
    entry = reader.get("evt-1")
    assert entry is not None
    assert entry.event_id == "evt-1"
    assert entry.redacted_summary == "hello world"


def test_search_run_id_and_event_type_filters(tmp_path):
    db = tmp_path / "context.db"
    repo = ContextRepository(db)
    repo.upsert(_make_entry("evt-1", "hello", run_id="run-a", event_type="system"))
    repo.upsert(_make_entry("evt-2", "hello", run_id="run-b", event_type="validation"))

    reader = ContextReader(db)
    assert {r.event_id for r in reader.search(run_id="run-a")} == {"evt-1"}
    assert {r.event_id for r in reader.search(event_type="validation")} == {"evt-2"}


def test_status_counts_and_last_indexed_are_privacy_aware(tmp_path):
    db = tmp_path / "context.db"
    repo = ContextRepository(db)
    public_ts = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)
    internal_ts = datetime(2026, 8, 9, 12, 1, 0, tzinfo=UTC)
    restricted_ts = datetime(2026, 8, 9, 12, 2, 0, tzinfo=UTC)

    repo.upsert(
        _make_entry(
            "evt-public", "hello", privacy_level="public", timestamp=public_ts
        )
    )
    repo.upsert(
        _make_entry(
            "evt-internal", "hello", privacy_level="internal", timestamp=internal_ts
        )
    )
    repo.upsert(
        _make_entry(
            "evt-restricted",
            "hello",
            privacy_level="restricted",
            timestamp=restricted_ts,
        )
    )

    reader = ContextReader(db)
    status = reader.status()
    assert status["entry_count"] == 2
    # last_indexed_at reflects indexing time, not event timestamp, and must be
    # a valid ISO string from the visible entries.
    assert status["last_indexed_at"] is not None
    datetime.fromisoformat(status["last_indexed_at"])
