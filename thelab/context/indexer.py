"""Idempotent JSONL -> SQLite context indexing.

Supports two source schemas:

1. Canonical LogEntry-style events with root-level fields such as
   ``redacted_summary``, ``session_id``, ``run_id``, ``tags``.

2. The existing ``/log`` agent-session-summary shape:

   {
       "schema_version": "1.0",
       "event_id": "devlog_...",
       "timestamp": "2026-08-09T22:31:39+00:00",
       "event_type": "agent_session_summary",
       "project": "the-lab-mcp-tfg",
       "context": {"slice": "slice-3", "run_id": null},
       "outcome": {"status": "completed", "summary": "..."},
       "learning": {"topics": ["SQLite FTS5", ...]},
       "evidence": {"artifacts": [...], "source_refs": [...]},
       "privacy": {...}
   }

Malformed records are skipped and reported; they are never persisted.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thelab.contracts import ArtifactRef, EventType, PrivacyLevel

from .contracts import IndexedEntry
from .privacy import normalize_log_privacy
from .redaction import redact
from .repository import ContextRepository


def _canonical_json(data: dict[str, Any]) -> str:
    """Return a stable, hashable JSON representation."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _content_hash(data: dict[str, Any]) -> str:
    """Return SHA-256 hash of the canonical JSON."""
    return hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest()


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse a timezone-aware ISO timestamp.

    Returns None for invalid, missing, or naive (timezone-unaware) values.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed
    return None


def _is_log_event(raw: dict[str, Any]) -> bool:
    """Detect the /log agent-session-summary shape."""
    return (
        "outcome" in raw
        and isinstance(raw.get("outcome"), dict)
        and "summary" in raw["outcome"]
    )


def _is_canonical_event(raw: dict[str, Any]) -> bool:
    """Detect canonical LogEntry-style events."""
    return "redacted_summary" in raw


def _normalize_tags(raw: dict[str, Any]) -> list[str]:
    """Build a deduplicated tag list from /log or canonical events."""
    tags: list[str] = []
    seen: set[str] = set()

    def add(tag: Any) -> None:
        if isinstance(tag, str) and tag and tag not in seen:
            tags.append(tag)
            seen.add(tag)

    if _is_log_event(raw):
        context = raw.get("context") or {}
        if isinstance(context, dict):
            add(context.get("slice"))
        learning = raw.get("learning") or {}
        if isinstance(learning, dict):
            for topic in learning.get("topics") or []:
                add(topic)
    else:
        for tag in raw.get("tags") or []:
            add(tag)

    return tags


def _extract_artifact_refs(raw: dict[str, Any]) -> list[ArtifactRef]:
    """Return ArtifactRef objects only when the source already provides valid ones.

    /log ``evidence.artifacts`` and ``evidence.source_refs`` are plain strings,
    so they are intentionally not converted into ArtifactRefs.
    """
    from pathlib import Path

    refs: list[ArtifactRef] = []
    candidates = raw.get("related_artifact_refs", [])
    if not isinstance(candidates, list):
        return refs
    for item in candidates:
        try:
            normalized = dict(item) if isinstance(item, dict) else {}
            if "relative_path" in normalized and isinstance(normalized["relative_path"], str):
                normalized["relative_path"] = Path(normalized["relative_path"])
            refs.append(ArtifactRef.model_validate(normalized))
        except Exception:
            continue
    return refs


def _derive_session_id(raw: dict[str, Any]) -> str:
    """Return a non-empty session identifier."""
    session_id = raw.get("session_id")
    if isinstance(session_id, str) and session_id.strip():
        return session_id
    project = raw.get("project")
    if isinstance(project, str) and project.strip():
        return project
    event_id = raw.get("event_id")
    if isinstance(event_id, str) and event_id.strip():
        return event_id
    return "unknown-session"


def _normalize_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a raw JSONL dict into a normalized canonical dict.

    Returns None when the record does not match any supported schema.
    """
    if not isinstance(raw, dict):
        return None

    event_id = raw.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        return None

    event_type_value = raw.get("event_type")
    if not isinstance(event_type_value, str):
        return None
    try:
        event_type = EventType(event_type_value)
    except ValueError:
        return None

    timestamp = _parse_timestamp(raw.get("timestamp"))
    if timestamp is None:
        return None

    if _is_log_event(raw):
        outcome = raw.get("outcome") or {}
        if not isinstance(outcome, dict):
            return None
        summary = outcome.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        context = raw.get("context") or {}
        run_id = context.get("run_id") if isinstance(context, dict) else None
        session_id = _derive_session_id(raw)
        tags = _normalize_tags(raw)
        related_artifact_refs: list[ArtifactRef] = []
        privacy_level_value = raw.get("privacy_level")
        if privacy_level_value is None:
            privacy_level_value = normalize_log_privacy(raw.get("privacy"))
    elif _is_canonical_event(raw):
        summary = raw.get("redacted_summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        run_id = raw.get("run_id")
        session_id = _derive_session_id(raw)
        tags = _normalize_tags(raw)
        related_artifact_refs = _extract_artifact_refs(raw)
        privacy_level_value = raw.get("privacy_level", "internal")
    else:
        return None

    try:
        privacy_level = PrivacyLevel(privacy_level_value)
    except ValueError:
        privacy_level = PrivacyLevel.internal

    redacted_summary = redact(summary)

    return {
        "event_id": event_id,
        "event_type": event_type,
        "session_id": session_id,
        "run_id": run_id,
        "tags": tags,
        "redacted_summary": redacted_summary,
        "related_artifact_refs": related_artifact_refs,
        "privacy_level": privacy_level,
        "timestamp": timestamp,
    }


def _build_indexed_entry(normalized: dict[str, Any]) -> IndexedEntry:
    """Build an IndexedEntry from a validated, normalized dict."""
    source_for_hash = {
        "event_id": normalized["event_id"],
        "event_type": normalized["event_type"].value,
        "session_id": normalized["session_id"],
        "run_id": normalized["run_id"],
        "tags": normalized["tags"],
        "redacted_summary": normalized["redacted_summary"],
        "related_artifact_refs": [
            ref.model_dump(mode="json") for ref in normalized["related_artifact_refs"]
        ],
        "privacy_level": normalized["privacy_level"].value,
        "timestamp": normalized["timestamp"].astimezone(UTC).isoformat(),
    }

    return IndexedEntry(
        event_id=normalized["event_id"],
        event_type=normalized["event_type"],
        session_id=normalized["session_id"],
        run_id=normalized["run_id"],
        tags=normalized["tags"],
        redacted_summary=normalized["redacted_summary"],
        related_artifact_refs=normalized["related_artifact_refs"],
        privacy_level=normalized["privacy_level"],
        timestamp=normalized["timestamp"],
        content_hash=_content_hash(source_for_hash),
        indexed_at=datetime.now(UTC),
    )


class IndexResult:
    """Result of an indexing run."""

    def __init__(self) -> None:
        self.indexed = 0
        self.skipped = 0
        self.errors: list[str] = []


def index_source_file(source_path: Path | str, repo: ContextRepository) -> IndexResult:
    """Index a single JSONL file into the repository.

    The source file is read but never modified. Malformed records are skipped
    and reported; they are never persisted and never cause content-conflict
    errors.
    """
    source_path = Path(source_path)
    result = IndexResult()

    if not source_path.exists():
        return result

    with source_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                result.errors.append(f"line {line_number}: invalid JSON: {exc}")
                result.skipped += 1
                continue

            normalized = _normalize_event(raw)
            if normalized is None:
                result.errors.append(
                    f"line {line_number}: unsupported or malformed record"
                )
                result.skipped += 1
                continue

            try:
                entry = _build_indexed_entry(normalized)
                inserted = repo.upsert(entry)
                if inserted:
                    result.indexed += 1
                else:
                    result.skipped += 1
            except Exception as exc:
                result.errors.append(f"line {line_number}: {exc}")
                result.skipped += 1

    return result
