"""Deterministic task-type inference for tabular ML."""

from __future__ import annotations

from typing import Literal

import pandas as pd

TaskType = Literal["classification", "regression"]

_CLASSIFICATION_MAX_CLASSES = 20


def infer_task_type(
    df: pd.DataFrame,
    target_column: str,
    max_classes: int = _CLASSIFICATION_MAX_CLASSES,
) -> TaskType:
    """Infer whether the target column represents a classification or regression task.

    Rules (in order):
    1. If the target column is missing, default to ``classification``.
    2. Non-numeric targets are classification.
    3. Numeric targets with at most ``max_classes`` distinct values are classification.
    4. Otherwise regression.
    """
    if target_column not in df.columns:
        return "classification"

    series = df[target_column]
    if not pd.api.types.is_numeric_dtype(series):
        return "classification"

    n_unique = series.nunique(dropna=True)
    if n_unique <= max_classes:
        return "classification"

    return "regression"
