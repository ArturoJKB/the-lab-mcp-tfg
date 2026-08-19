from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelSpec(BaseModel):
    """Deterministic training configuration for an allowed model.

    Maps to PRD Required contracts > ModelSpec:
    - allowed algorithm
    - hyperparameters
    - target metric
    - random seed
    - approval rules
    - model version
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    algorithm: str = "logistic_regression"
    hyperparameters: dict[str, Any] = Field(default_factory=dict)
    target_metric: str = "accuracy"
    random_seed: int = 42
    approval_rules: dict[str, Any] = Field(default_factory=dict)
    model_version: str = "0.1.0"
