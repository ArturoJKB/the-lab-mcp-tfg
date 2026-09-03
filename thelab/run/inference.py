"""Shared inference helpers used by the HTTP service and MCP registry."""

from __future__ import annotations

import math
from typing import Any


def feature_columns(data_profile: dict[str, Any], target: str) -> list[str]:
    """Derive feature columns from a data profile, excluding the target."""
    columns = (
        data_profile.get("column_names")
        or (data_profile.get("schema_summary") or {}).get("columns")
        or []
    )
    return [col for col in columns if col != target]


def normalize_features(features: Any, feature_columns: list[str]) -> list[list[float]]:
    """Normalize a list of feature records/rows into a 2-D float matrix.

    Raises ``ValueError`` with a clear message when columns are missing or
    values are not finite floats.
    """
    if not isinstance(features, list):
        raise ValueError("features must be a list")
    if not feature_columns:
        raise ValueError("feature_columns must not be empty")

    rows: list[list[float]] = []
    for row in features:
        if isinstance(row, dict):
            values = []
            for col in feature_columns:
                if col not in row:
                    raise ValueError(f"missing feature column: {col}")
                value = row[col]
                try:
                    fvalue = float(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"feature '{col}' is not numeric: {value!r}") from exc
                if not math.isfinite(fvalue):
                    raise ValueError(f"feature '{col}' is not finite: {value!r}")
                values.append(fvalue)
            rows.append(values)
        elif isinstance(row, list):
            if len(row) != len(feature_columns):
                raise ValueError(
                    f"feature row length {len(row)} does not match {len(feature_columns)}"
                )
            values = []
            for idx, value in enumerate(row):
                try:
                    fvalue = float(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"feature at index {idx} is not numeric: {value!r}") from exc
                if not math.isfinite(fvalue):
                    raise ValueError(f"feature at index {idx} is not finite: {value!r}")
                values.append(fvalue)
            rows.append(values)
        else:
            raise ValueError("each feature row must be a dict or list")
    return rows


def predict_features(model: Any, normalized: Any, feature_columns: list[str]) -> Any:
    """Predict on a normalized matrix, preserving feature names when fitted with them.

    Models are trained on ``DataFrame[feature_columns]``, so inference with a
    plain ndarray triggers sklearn's feature-name UserWarning. Rebuilding the
    frame fixes that; if the persisted model's fitted names differ (older
    artifacts), fall back to the ndarray path so behavior never changes.
    """
    try:
        import pandas as pd

        frame = pd.DataFrame(normalized, columns=feature_columns)
        return model.predict(frame)
    except Exception:
        return model.predict(normalized)
