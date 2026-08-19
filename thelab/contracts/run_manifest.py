from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .artifact_ref import ArtifactRef


class RunStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    rejected = "rejected"


class ValidationStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class RunManifest(BaseModel):
    """Complete evidence record for a single training run.

    Maps to PRD Required contracts > RunManifest:
    - run_id
    - input-data hash
    - training configuration
    - random seed
    - relevant dependency versions
    - execution timestamps
    - final status
    - validation status
    - artifact references
    - error summary, if applicable
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    run_id: str
    input_hash: str
    training_config: dict[str, Any] = Field(default_factory=dict)
    random_seed: int
    dependency_versions: dict[str, str] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    final_status: RunStatus = RunStatus.pending
    validation_status: ValidationStatus = ValidationStatus.pending
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    error_summary: str | None = None
    task_spec_id: str | None = None
