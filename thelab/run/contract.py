from __future__ import annotations

from typing import Any

import pandas as pd


def build_dataset_contract(
    df: pd.DataFrame,
    dataset_path: Any,
    target_column: str,
    feature_columns: list[str],
    dataset_fingerprint: str,
) -> dict[str, Any]:
    """Build a typed dataset contract for the run."""
    expected_schema = {
        col: str(dtype) for col, dtype in df[feature_columns + [target_column]].dtypes.items()
    }
    constraints = {
        "target_column": target_column,
        "feature_columns": feature_columns,
        "required_columns": feature_columns + [target_column],
        "target_type": str(df[target_column].dtype),
        "features_numeric": df[feature_columns].select_dtypes(include="number").shape[1]
        == len(feature_columns),
    }
    rejected_fields = [
        col for col in df.columns if col not in feature_columns and col != target_column
    ]

    return {
        "target_column": target_column,
        "feature_columns": feature_columns,
        "expected_input_schema": expected_schema,
        "basic_constraints": constraints,
        "dataset_fingerprint": dataset_fingerprint,
        "rejected_fields": rejected_fields,
        "unsupported_fields": [],
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
    }
