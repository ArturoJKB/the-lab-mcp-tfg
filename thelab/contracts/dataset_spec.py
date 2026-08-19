from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DatasetSpec(BaseModel):
    """Typed specification for a local tabular dataset.

    Maps to PRD Required contracts > DatasetSpec:
    - source
    - expected schema
    - target column
    - data-quality rules
    - train/test split configuration
    - privacy classification
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    source: str
    expected_schema: dict[str, str] = Field(default_factory=dict)
    target_column: str
    data_quality_rules: dict[str, Any] = Field(default_factory=dict)
    train_test_split: dict[str, Any] = Field(default_factory=dict)
    privacy_classification: str = "internal"
