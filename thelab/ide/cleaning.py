"""Deterministic dataset cleaning helpers for the IDE.

Creates a cleaned copy of a dataset suitable for the deterministic training
pipeline: drops rows with missing targets, drops empty columns, one-hot encodes
categorical features, and imputes missing numeric values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .datasets import get_uploads_root, resolve_dataset_path


def clean_dataset(
    dataset_id: str,
    target: str,
    drop_missing_target: bool = True,
    drop_empty_columns: bool = True,
    one_hot_encode: bool = True,
    numeric_impute_strategy: str = "median",
) -> dict[str, Any]:
    """Create a cleaned CSV from ``dataset_id`` and return metadata.

    The cleaned file is stored alongside the original upload with a
    ``_cleaned`` suffix. Only uploaded datasets can be cleaned; fixtures are
    read-only.
    """
    source_path = resolve_dataset_path(dataset_id)
    if not isinstance(dataset_id, str) or not dataset_id.startswith("uploads/"):
        raise ValueError("only uploaded datasets can be cleaned")

    df = pd.read_csv(source_path)
    if target not in df.columns:
        raise ValueError(f"target column '{target}' not found")

    original_rows = len(df)
    original_columns = len(df.columns)

    if drop_missing_target:
        df = df.dropna(subset=[target])

    if drop_empty_columns:
        df = df.dropna(axis=1, how="all")

    if len(df) == 0:
        raise ValueError("dataset is empty after dropping rows with missing target")

    # One-hot encode categorical features (exclude target).
    categorical_cols = df.select_dtypes(exclude="number").columns.tolist()
    categorical_cols = [c for c in categorical_cols if c != target]
    if one_hot_encode and categorical_cols:
        df = pd.get_dummies(df, columns=categorical_cols, drop_first=False)

    # Impute missing numeric values.
    numeric_cols = [c for c in df.select_dtypes(include="number").columns if c != target]
    for col in numeric_cols:
        if df[col].isna().any():
            if numeric_impute_strategy == "median":
                fill_value = df[col].median()
            elif numeric_impute_strategy == "mean":
                fill_value = df[col].mean()
            else:
                fill_value = 0
            df[col] = df[col].fillna(fill_value)

    # Ensure target is at the end for readability (optional).
    cols = [c for c in df.columns if c != target] + [target]
    df = df[cols]

    # Save cleaned file.
    uploads_root = get_uploads_root()
    basename = source_path.name
    stem = Path(basename).stem
    suffix = Path(basename).suffix
    cleaned_basename = f"{stem}_cleaned{suffix}"
    cleaned_path = uploads_root / cleaned_basename

    # Avoid overwriting an existing cleaned file by appending a counter.
    if cleaned_path.exists():
        counter = 1
        while True:
            candidate = uploads_root / f"{stem}_cleaned_{counter}{suffix}"
            if not candidate.exists():
                cleaned_path = candidate
                break
            counter += 1

    df.to_csv(cleaned_path, index=False)

    return {
        "dataset_id": f"uploads/{cleaned_path.name}",
        "source_dataset_id": dataset_id,
        "filename": cleaned_path.name,
        "source": "upload",
        "rows": len(df),
        "columns": len(df.columns),
        "original_rows": original_rows,
        "original_columns": original_columns,
        "dropped_rows": original_rows - len(df),
        "target": target,
    }
