from datetime import UTC, datetime

import pytest

from thelab.context.contracts import IndexedEntry
from thelab.context.repository import ContentMismatchError, ContextRepository
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


def test_repository_creates_schema(tmp_path):
    db = tmp_path / "context.db"
    assert ContextRepository(db) is not None
    assert db.exists()


def test_upsert_and_get(tmp_path):
    repo = ContextRepository(tmp_path / "context.db")
    entry = _make_entry("evt-1", "Run started")
    assert repo.upsert(entry) is True
    found = repo.get("evt-1")
    assert found is not None
    assert found.event_id == "evt-1"
    assert found.redacted_summary == "Run started"


def test_upsert_is_idempotent(tmp_path):
    repo = ContextRepository(tmp_path / "context.db")
    entry = _make_entry("evt-1", "Run started")
    assert repo.upsert(entry) is True
    assert repo.upsert(entry) is False
    assert len(repo.search()) == 1


def test_upsert_rejects_content_mismatch(tmp_path):
    repo = ContextRepository(tmp_path / "context.db")
    entry = _make_entry("evt-1", "Run started", content_hash="hash-a")
    repo.upsert(entry)

    conflicting = _make_entry("evt-1", "Run failed", content_hash="hash-b")
    with pytest.raises(ContentMismatchError):
        repo.upsert(conflicting)


def test_fts5_search(tmp_path):
    repo = ContextRepository(tmp_path / "context.db")
    repo.upsert(_make_entry("evt-1", "Dataset validation error occurred"))
    repo.upsert(_make_entry("evt-2", "Training completed successfully"))
    repo.upsert(_make_entry("evt-3", "Another error in pipeline"))

    results = repo.search(query="error")
    assert len(results) == 2
    assert {r.event_id for r in results} == {"evt-1", "evt-3"}


def test_search_with_run_id_filter(tmp_path):
    repo = ContextRepository(tmp_path / "context.db")
    repo.upsert(_make_entry("evt-1", "Run started", run_id="run-a"))
    repo.upsert(_make_entry("evt-2", "Run started", run_id="run-b"))

    results = repo.search(run_id="run-a")
    assert len(results) == 1
    assert results[0].run_id == "run-a"


def test_search_with_tag_filter(tmp_path):
    repo = ContextRepository(tmp_path / "context.db")
    repo.upsert(_make_entry("evt-1", "Run started", tags=["tag-a"]))
    repo.upsert(_make_entry("evt-2", "Run started", tags=["tag-a", "tag-b"]))
    repo.upsert(_make_entry("evt-3", "Run started", tags=["tag-b"]))

    results = repo.search(tags=["tag-a", "tag-b"])
    assert len(results) == 1
    assert results[0].event_id == "evt-2"


def test_search_with_event_type_filter(tmp_path):
    repo = ContextRepository(tmp_path / "context.db")
    repo.upsert(_make_entry("evt-1", "Run started", event_type="system"))
    repo.upsert(_make_entry("evt-2", "Validation passed", event_type="validation"))

    results = repo.search(event_type="validation")
    assert len(results) == 1
    assert results[0].event_id == "evt-2"


def test_search_with_date_range(tmp_path):
    repo = ContextRepository(tmp_path / "context.db")
    t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    t3 = datetime(2026, 12, 1, 12, 0, 0, tzinfo=UTC)

    repo.upsert(_make_entry("evt-1", "Early", timestamp=t1))
    repo.upsert(_make_entry("evt-2", "Mid", timestamp=t2))
    repo.upsert(_make_entry("evt-3", "Late", timestamp=t3))

    results = repo.search(since=t2, until=t3)
    assert len(results) == 2
    assert {r.event_id for r in results} == {"evt-2", "evt-3"}


def test_artifact_refs_round_trip(tmp_path):
    from pathlib import Path

    from thelab.contracts import ArtifactRef

    repo = ContextRepository(tmp_path / "context.db")
    ref = ArtifactRef(
        artifact_id="ref-1",
        artifact_type="model_card",
        relative_path=Path("run-abc/model_card.md"),
        content_hash="abc123",
        origin="trainer",
        parent_run_id="run-abc",
    )
    entry = _make_entry("evt-refs", "Run with artifacts", related_artifact_refs=[ref])
    repo.upsert(entry)

    found = repo.get("evt-refs")
    assert found is not None
    assert len(found.related_artifact_refs) == 1
    assert found.related_artifact_refs[0].artifact_id == "ref-1"
    assert str(found.related_artifact_refs[0].relative_path) == "run-abc/model_card.md"

    search_results = repo.search(query="artifacts")
    assert len(search_results) == 1
    assert len(search_results[0].related_artifact_refs) == 1


def test_status_report(tmp_path):
    repo = ContextRepository(tmp_path / "context.db")
    repo.upsert(_make_entry("evt-1", "Run started"))
    status = repo.status()
    assert status["entry_count"] == 1
    assert status["fts5_available"] is True
    assert "db_path" in status
    assert "last_indexed_at" in status
