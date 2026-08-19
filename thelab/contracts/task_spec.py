from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .artifact_ref import ArtifactRef


class TaskState(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    rejected = "rejected"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TaskSpec(BaseModel):
    """Orchestrator-owned task definition.

    Maps to PRD Required contracts > TaskSpec:
    - task identifier
    - objective
    - input references
    - constraints
    - responsible agent
    - task state
    - artifact references
    - creation and update timestamps
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    objective: str
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    responsible_agent: str = "orchestrator"
    task_state: TaskState = TaskState.pending
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
