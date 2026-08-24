from __future__ import annotations

from typing import Any

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .model_registry import MODEL_REGISTRY


def build_pipeline(
    model_name: str,
    seed: int,
    hyperparameters: dict[str, Any] | None = None,
) -> Pipeline:
    """Return a deterministic sklearn Pipeline for the requested model."""
    estimator = MODEL_REGISTRY.build_estimator(model_name, seed, hyperparameters=hyperparameters)
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("estimator", estimator),
        ]
    )
