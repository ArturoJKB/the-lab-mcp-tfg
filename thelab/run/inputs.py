from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from .errors import RejectedRunError
from .model_registry import MODEL_REGISTRY


def _reject_unsafe_path(value: Path, field_name: str, root: Path) -> Path:
    """Reject absolute paths, parent-directory traversal, and symlink escapes.

    Paths must be relative to the workspace root, must not contain ``..``
    components, and must resolve to a location inside the workspace. This keeps
    every persisted run output under the workspace.
    """
    if value.is_absolute():
        raise ValueError(f"{field_name} must be a relative path: {value}")
    if ".." in value.parts:
        raise ValueError(f"{field_name} must not contain '..' components: {value}")
    resolved = (root / value).resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"{field_name} resolves outside workspace: {value}") from exc
    return value


class RunInputs(BaseModel):
    """Normalized, validated CLI inputs for a `thelab run model` invocation."""

    model_config = ConfigDict(strict=True, extra="forbid")

    dataset: Path
    target: str
    model: str
    seed: int
    output: Path
    workspace_root: Path = Field(default_factory=Path.cwd)

    @field_validator("dataset", "output", "workspace_root", mode="before")
    @classmethod
    def _resolve_path(cls, value: Any) -> Path:
        return Path(value)

    @field_validator("dataset", "output")
    @classmethod
    def _relative_path(cls, value: Path, info: ValidationInfo) -> Path:
        root = info.data.get("workspace_root") or Path.cwd()
        return _reject_unsafe_path(value, str(info.field_name), Path(root))

    @field_validator("model")
    @classmethod
    def _supported_model(cls, value: str) -> str:
        base_models = MODEL_REGISTRY.list_models()
        probability_variants = [
            f"{name}_probability"
            for name in base_models
            if MODEL_REGISTRY.supports_probability(name)
        ]
        supported = set(base_models) | set(probability_variants)
        if value not in supported:
            raise ValueError(
                f"unsupported model '{value}'. Supported models: {', '.join(sorted(supported))}"
            )
        return value

    def validate_dataset_exists(self) -> None:
        dataset_path = self.workspace_root / self.dataset
        if not dataset_path.exists():
            raise RejectedRunError(f"dataset not found: {self.dataset}")
        if not dataset_path.is_file():
            raise RejectedRunError(f"dataset path is not a file: {self.dataset}")

    def safe_dict(self) -> dict[str, Any]:
        """Return a JSON-safe, user-home-free representation of the inputs."""
        return {
            "dataset": str(self.dataset),
            "target": self.target,
            "model": self.model,
            "seed": self.seed,
            "output": str(self.output),
        }
