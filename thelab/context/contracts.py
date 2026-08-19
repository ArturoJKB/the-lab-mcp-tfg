"""Pydantic contracts for the local context store."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from thelab.contracts import ArtifactRef, EventType, PrivacyLevel


class IndexedEntry(BaseModel):
    """A context entry as stored in the SQLite-derived index.

    Extends the canonical ``LogEntry`` with indexing metadata and an explicit
    ``event_id`` used for deduplication and lookup.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    event_id: str
    event_type: EventType
    session_id: str
    run_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    redacted_summary: str
    related_artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    privacy_level: PrivacyLevel = PrivacyLevel.internal
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def canonical_json(self) -> str:
        """Return a canonical JSON representation for content hashing.

        The JSON excludes derived/indexing fields so that re-indexing the same
        source event produces the same hash.
        """
        data = self.model_dump(
            mode="json",
            include={
                "event_id",
                "event_type",
                "session_id",
                "run_id",
                "tags",
                "redacted_summary",
                "related_artifact_refs",
                "privacy_level",
                "timestamp",
            },
        )
        return json.dumps(data, sort_keys=True, default=str)
