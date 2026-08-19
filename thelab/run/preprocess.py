from __future__ import annotations

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .model_registry import MODEL_REGISTRY


def build_pipeline(model_name: str, seed: int) -> Pipeline:
    """Return a deterministic sklearn Pipeline for the requested model."""
    estimator = MODEL_REGISTRY.build_estimator(model_name, seed)
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("classifier", estimator),
        ]
    )
