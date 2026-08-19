from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator


class ArtifactRef(BaseModel):
    """Reference to a persisted artifact inside a run workspace.

    Maps to PRD Required contracts > ArtifactRef:
    - artifact identifier
    - artifact type
    - relative local path
    - content hash
    - origin
    - parent run_id
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    artifact_id: str
    artifact_type: str
    relative_path: Path
    content_hash: str
    origin: str
    parent_run_id: str

    @field_validator("relative_path")
    @classmethod
    def _must_be_relative(cls, value: Path) -> Path:
        if value.is_absolute() or ".." in value.parts:
            raise ValueError(
                "relative_path must be a relative path without parent references"
            )
        return value
