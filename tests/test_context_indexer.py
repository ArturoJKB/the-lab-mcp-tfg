import json

from thelab.context.indexer import index_source_file
from thelab.context.repository import ContextRepository


def _write_jsonl(path, lines):
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def _log_event(event_id: str, summary: str, **kwargs) -> dict:
    """Build a realistic /log agent-session-summary event."""
    return {
        "schema_version": "1.0",
        "event_id": event_id,
        "timestamp": kwargs.get("timestamp", "2026-08-09T12:00:00+00:00"),
        "event_type": kwargs.get("event_type", "agent_session_summary"),
        "project": "the-lab-mcp-tfg",
        "agent": {"platform": "opencode", "model": "kimi-k2.7-code", "role": "assistant"},
        "context": {
            "slice": kwargs.get("slice", "slice-3"),
            "run_id": kwargs.get("run_id", None),
        },
        "outcome": {"status": "completed", "summary": summary},
        "learning": {"topics": kwargs.get("topics", ["context-store"])},
        "evidence": {"artifacts": [], "source_refs": []},
        "privacy": {"redactions_applied": True, "contains_sensitive_data": False},
    }


def test_indexer_creates_entries(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {
                "event_id": "evt-1",
                "event_type": "system",
                "session_id": "session-1",
                "run_id": "run-abc",
                "tags": ["start"],
                "redacted_summary": "Run started",
                "privacy_level": "internal",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
            {
                "event_id": "evt-2",
                "event_type": "validation",
                "session_id": "session-1",
                "run_id": "run-abc",
                "tags": ["validation"],
                "redacted_summary": "Validation passed",
                "privacy_level": "internal",
                "timestamp": "2026-08-09T12:01:00+00:00",
            },
        ],
    )

    repo = ContextRepository(tmp_path / "context.db")
    result = index_source_file(source, repo)

    assert result.indexed == 2
    assert result.skipped == 0
    assert not result.errors
    assert repo.status()["entry_count"] == 2


def test_indexer_is_idempotent(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {
                "event_id": "evt-1",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Run started",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
        ],
    )

    repo = ContextRepository(tmp_path / "context.db")
    result1 = index_source_file(source, repo)
    result2 = index_source_file(source, repo)

    assert result1.indexed == 1
    assert result2.skipped == 1
    assert repo.status()["entry_count"] == 1


def test_indexer_redacts_secrets(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {
                "event_id": "evt-secret",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Using API key sk-1234567890abcdef1234567890",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
        ],
    )

    repo = ContextRepository(tmp_path / "context.db")
    index_source_file(source, repo)

    entry = repo.get("evt-secret")
    assert entry is not None
    assert "sk-1234567890abcdef" not in entry.redacted_summary
    assert "[REDACTED]" in entry.redacted_summary


def test_indexer_does_not_modify_source(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    original_text = json.dumps(
        {"event_id": "evt-1", "event_type": "system", "session_id": "s1", "redacted_summary": "Run started", "timestamp": "2026-08-09T12:00:00+00:00"}
    )
    source.write_text(original_text + "\n", encoding="utf-8")
    original_bytes = source.read_bytes()

    repo = ContextRepository(tmp_path / "context.db")
    index_source_file(source, repo)

    assert source.read_bytes() == original_bytes


def test_indexer_reports_json_errors(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    source.write_text('{"valid": true}\nnot valid json\n', encoding="utf-8")

    repo = ContextRepository(tmp_path / "context.db")
    result = index_source_file(source, repo)

    assert result.indexed == 0
    assert result.skipped == 2
    assert len(result.errors) == 2


def test_indexer_rejects_conflicting_event_id(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {
                "event_id": "evt-1",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "First version",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
        ],
    )

    repo = ContextRepository(tmp_path / "context.db")
    index_source_file(source, repo)

    source2 = tmp_path / "agent-events-v2.jsonl"
    _write_jsonl(
        source2,
        [
            {
                "event_id": "evt-1",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Second version",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
        ],
    )

    result = index_source_file(source2, repo)
    assert any("different content" in err for err in result.errors)


def test_indexer_supports_log_event_shape(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            _log_event(
                "devlog-2026-001",
                "Implemented SQLite context store with FTS5 search.",
                run_id="run-20260809-212944-785f03ac",
                slice="slice-3",
                topics=["SQLite FTS5", "context indexing"],
            ),
        ],
    )

    repo = ContextRepository(tmp_path / "context.db")
    result = index_source_file(source, repo)

    assert result.indexed == 1
    assert result.skipped == 0
    assert not result.errors

    entry = repo.get("devlog-2026-001")
    assert entry is not None
    assert entry.event_type == "agent_session_summary"
    assert entry.run_id == "run-20260809-212944-785f03ac"
    assert "SQLite FTS5" in entry.tags
    assert "context indexing" in entry.tags
    assert "slice-3" in entry.tags
    assert "Implemented SQLite context store" in entry.redacted_summary


def test_indexer_search_finds_log_summary(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            _log_event("devlog-001", "First milestone completed successfully."),
            _log_event("devlog-002", "Validation error fixed in dataset pipeline."),
        ],
    )

    repo = ContextRepository(tmp_path / "context.db")
    index_source_file(source, repo)

    results = repo.search(query="validation")
    assert len(results) == 1
    assert results[0].event_id == "devlog-002"


def test_indexer_skips_malformed_records(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {"valid": True},
            {"event_id": "evt-ok", "event_type": "system", "session_id": "s1", "redacted_summary": "Good record", "timestamp": "2026-08-09T12:00:00+00:00"},
            {"event_id": "", "event_type": "system", "redacted_summary": "Missing id", "timestamp": "2026-08-09T12:00:00+00:00"},
            {"event_id": "evt-bad-ts", "event_type": "system", "redacted_summary": "Bad timestamp", "timestamp": "not-a-timestamp"},
            {"event_id": "evt-bad-type", "event_type": "unknown_type", "redacted_summary": "Bad type", "timestamp": "2026-08-09T12:00:00+00:00"},
            {"event_id": "evt-empty-sum", "event_type": "system", "redacted_summary": "   ", "timestamp": "2026-08-09T12:00:00+00:00"},
        ],
    )

    repo = ContextRepository(tmp_path / "context.db")
    result = index_source_file(source, repo)

    assert result.indexed == 1
    assert result.skipped == 5
    assert len(result.errors) == 5
    assert repo.status()["entry_count"] == 1


def test_indexer_mixed_reindex_is_deterministic(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            _log_event("devlog-001", "Valid log entry."),
            {"event_id": "bad-1", "event_type": "system"},  # missing summary/timestamp
        ],
    )

    repo = ContextRepository(tmp_path / "context.db")
    result1 = index_source_file(source, repo)
    result2 = index_source_file(source, repo)

    assert result1.indexed == 1
    assert result1.skipped == 1
    assert result2.indexed == 0
    assert result2.skipped == 2
    assert repo.status()["entry_count"] == 1


def test_indexer_preserves_artifact_refs(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    ref = {
        "artifact_id": "ref-1",
        "artifact_type": "model_card",
        "relative_path": "run-abc/model_card.md",
        "content_hash": "abc123",
        "origin": "trainer",
        "parent_run_id": "run-abc",
    }
    _write_jsonl(
        source,
        [
            {
                "event_id": "evt-refs",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Run with artifacts",
                "timestamp": "2026-08-09T12:00:00+00:00",
                "related_artifact_refs": [ref],
            },
        ],
    )

    repo = ContextRepository(tmp_path / "context.db")
    result = index_source_file(source, repo)

    assert result.indexed == 1
    entry = repo.get("evt-refs")
    assert entry is not None
    assert len(entry.related_artifact_refs) == 1
    assert entry.related_artifact_refs[0].artifact_id == "ref-1"
    assert str(entry.related_artifact_refs[0].relative_path) == "run-abc/model_card.md"


def test_indexer_does_not_invent_artifact_refs_from_log_strings(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    event = _log_event("devlog-artifacts", "Run completed.")
    event["evidence"]["artifacts"] = ["run-abc/model_card.md"]
    event["evidence"]["source_refs"] = ["docs/SLICE3_CONTEXT.md"]
    _write_jsonl(source, [event])

    repo = ContextRepository(tmp_path / "context.db")
    index_source_file(source, repo)

    entry = repo.get("devlog-artifacts")
    assert entry is not None
    assert entry.related_artifact_refs == []


def test_indexer_maps_log_privacy_level(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    event = _log_event("devlog-restricted", "Sensitive discussion.")
    event["privacy"] = {"level": "restricted"}
    _write_jsonl(source, [event])

    repo = ContextRepository(tmp_path / "context.db")
    result = index_source_file(source, repo)

    assert result.indexed == 1
    entry = repo.get("devlog-restricted")
    assert entry is not None
    assert entry.privacy_level == "restricted"


def test_indexer_defaults_log_privacy_to_internal_when_unspecified(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    event = _log_event("devlog-default", "Default privacy.")
    # No privacy object at all.
    event.pop("privacy", None)
    _write_jsonl(source, [event])

    repo = ContextRepository(tmp_path / "context.db")
    index_source_file(source, repo)

    entry = repo.get("devlog-default")
    assert entry is not None
    assert entry.privacy_level == "internal"


def test_indexer_defaults_log_privacy_to_internal_for_unknown_level(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    event = _log_event("devlog-unknown", "Unknown privacy.")
    event["privacy"] = {"level": "top-secret"}
    _write_jsonl(source, [event])

    repo = ContextRepository(tmp_path / "context.db")
    index_source_file(source, repo)

    entry = repo.get("devlog-unknown")
    assert entry is not None
    assert entry.privacy_level == "internal"
