from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .artifact_ref import ArtifactRef


class EventType(StrEnum):
    system = "system"
    user = "user"
    pipeline = "pipeline"
    validation = "validation"
    error = "error"
    decision = "decision"
    agent_session_summary = "agent_session_summary"


class PrivacyLevel(StrEnum):
    public = "public"
    internal = "internal"
    restricted = "restricted"
    secret = "secret"


class LogEntry(BaseModel):
    """Structured, auditable log entry.

    Maps to PRD Required contracts > LogEntry:
    - event type
    - session identifier
    - tags
    - redacted summary
    - related artifact references
    - privacy level
    - timestamp
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    event_type: EventType
    session_id: str
    tags: list[str] = Field(default_factory=list)
    redacted_summary: str
    related_artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    privacy_level: PrivacyLevel = PrivacyLevel.internal
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
