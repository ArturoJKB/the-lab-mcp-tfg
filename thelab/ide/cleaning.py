"""Deterministic dataset cleaning helpers for the IDE.

Creates a cleaned copy of a dataset suitable for the deterministic training
pipeline. The cleaning policy is:

1. Drop rows with a missing target.
2. Drop empty columns.
3. Parse datetime-looking string columns into year/month/day/dayofweek
   features (the original column is replaced by its components).
4. Categorical columns: impute missing values (mode or ``missing``), then
   one-hot encode low-cardinality columns (nunique <= threshold) and
   frequency-encode high-cardinality ones (e.g. ticker, firm) so wide
   real-world datasets cannot explode into tens of thousands of dummy
   columns.
5. Impute missing numeric values with the configured strategy.

Every action taken is recorded in a ``cleaning_report`` returned with the
cleaned dataset, keeping the transformation auditable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from .datasets import get_uploads_root, resolve_dataset_path

DEFAULT_ONEHOT_MAX_CARDINALITY = 20


def _onehot_max_cardinality() -> int:
    env = os.environ.get("THELAB_ONEHOT_MAX_CARDINALITY")
    if env and env.isdigit():
        return int(env)
    return DEFAULT_ONEHOT_MAX_CARDINALITY


def _datetime_features(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Replace a datetime-like column with numeric calendar components."""
    parsed = pd.to_datetime(df[column], errors="coerce", format="mixed", utc=True)
    out = pd.DataFrame(index=df.index)
    out[f"{column}_year"] = parsed.dt.year.astype("float64")
    out[f"{column}_month"] = parsed.dt.month.astype("float64")
    out[f"{column}_day"] = parsed.dt.day.astype("float64")
    out[f"{column}_dayofweek"] = parsed.dt.dayofweek.astype("float64")
    # Keep a rough cyclical hint for time-of-day when present.
    hour = parsed.dt.hour
    if hour.notna().any():
        out[f"{column}_hour"] = hour.astype("float64")
    return out


def _column_is_datetime(df: pd.DataFrame, column: str, sample_size: int = 200) -> bool:
    """Return True if a non-numeric column parses as datetimes for most rows."""
    series = df[column]
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return False
    sample = series.dropna().head(sample_size)
    if sample.empty:
        return False
    parsed = pd.to_datetime(sample, errors="coerce", format="mixed", utc=True)
    return bool(parsed.notna().mean() >= 0.95)


def clean_dataset(
    dataset_id: str,
    target: str,
    drop_missing_target: bool = True,
    drop_empty_columns: bool = True,
    one_hot_encode: bool = True,
    numeric_impute_strategy: str = "median",
    categorical_impute_strategy: str = "mode",
    parse_datetimes: bool = True,
    onehot_max_cardinality: int | None = None,
) -> dict[str, Any]:
    """Create a cleaned CSV from ``dataset_id`` and return metadata.

    The cleaned file is stored alongside the original upload with a
    ``_cleaned`` suffix. Only uploaded datasets can be cleaned; fixtures are
    read-only. The returned metadata includes a per-column ``cleaning_report``
    describing exactly which policy was applied to which column.
    """
    source_path = resolve_dataset_path(dataset_id)
    if not isinstance(dataset_id, str) or not dataset_id.startswith("uploads/"):
        raise ValueError("only uploaded datasets can be cleaned")

    df = pd.read_csv(source_path)
    if target not in df.columns:
        raise ValueError(f"target column '{target}' not found")

    original_rows = len(df)
    original_columns = len(df.columns)
    report: dict[str, Any] = {
        "dataset_id": dataset_id,
        "target": target,
        "actions": [],
        "columns": {},
    }

    if drop_missing_target:
        missing_target = int(df[target].isna().sum())
        if missing_target:
            df = df.dropna(subset=[target])
            report["actions"].append(f"dropped {missing_target} rows with missing target")

    if drop_empty_columns:
        empty_cols = [c for c in df.columns if df[c].isna().all()]
        if empty_cols:
            df = df.drop(columns=empty_cols)
            report["actions"].append(f"dropped empty columns: {', '.join(sorted(empty_cols))}")

    if len(df) == 0:
        raise ValueError("dataset is empty after dropping rows with missing target")

    # Datetime detection and feature extraction (before categorical handling).
    if parse_datetimes:
        for col in [c for c in df.columns if c != target]:
            if _column_is_datetime(df, col):
                parts = _datetime_features(df, col)
                df = pd.concat([df.drop(columns=[col]), parts], axis=1)
                report["actions"].append(
                    f"parsed datetime column '{col}' into numeric features"
                )

    max_card = onehot_max_cardinality if onehot_max_cardinality is not None else _onehot_max_cardinality()

    # Impute categoricals BEFORE encoding so NaN cannot become all-zero rows.
    categorical_cols = df.select_dtypes(exclude="number").columns.tolist()
    categorical_cols = [c for c in categorical_cols if c != target]
    for col in categorical_cols:
        if df[col].isna().any():
            if categorical_impute_strategy == "mode":
                mode = df[col].mode()
                fill_value = mode.iloc[0] if not mode.empty else "missing"
            else:
                fill_value = "missing"
            df[col] = df[col].fillna(fill_value)
            report["actions"].append(f"imputed categorical column '{col}' ({categorical_impute_strategy})")

    onehot_cols: list[str] = []
    frequency_cols: list[str] = []
    if one_hot_encode:
        for col in list(categorical_cols):
            if col not in df.columns:
                continue  # replaced by datetime parts
            n_unique = int(df[col].nunique(dropna=True))
            if n_unique <= max_card:
                onehot_cols.append(col)
            else:
                frequency_cols.append(col)
        if onehot_cols:
            # dtype=int keeps one-hot columns numeric (bool columns are
            # rejected by the pipeline's numeric-feature validation).
            df = pd.get_dummies(df, columns=onehot_cols, drop_first=False, dtype=int)
            report["actions"].append(
                f"one-hot encoded {len(onehot_cols)} low-cardinality column(s): {', '.join(sorted(onehot_cols))}"
            )
        for col in frequency_cols:
            n_unique = int(df[col].nunique(dropna=True))
            counts = df[col].value_counts(normalize=True)
            df[f"{col}_frequency"] = df[col].map(counts)
            df = df.drop(columns=[col])
            report["actions"].append(
                f"frequency-encoded high-cardinality column '{col}' (nunique={n_unique})"
            )

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
            report["actions"].append(f"imputed numeric column '{col}' ({numeric_impute_strategy})")

    # Ensure target is the last column for readability.
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

    report["actions"].append(f"wrote {cleaned_path.name}")

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
        "cleaning_report": report,
    }
