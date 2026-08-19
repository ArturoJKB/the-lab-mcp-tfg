from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .errors import RejectedRunError


def read_csv(dataset_path: Any) -> pd.DataFrame:
    """Read a CSV file into a DataFrame."""
    path = Path(dataset_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise RejectedRunError("dataset file is empty or has no header")
    header = lines[0].split(",")
    seen: set[str] = set()
    dupes = []
    for col in header:
        if col in seen:
            dupes.append(col)
        seen.add(col)
    if dupes:
        raise RejectedRunError(f"duplicate column names found: {dupes}")
    return pd.read_csv(dataset_path)


def profile_dataframe(df: pd.DataFrame, target_column: str) -> dict[str, Any]:
    """Build a concise, JSON-serializable data profile."""
    missing = df.isna().sum().to_dict()
    dtypes = {col: str(dtype) for col, dtype in df.dtypes.items()}
    schema_summary = {
        "columns": list(df.columns),
        "inferred_dtypes": dtypes,
        "numeric_columns": df.select_dtypes(include="number").columns.tolist(),
    }
    target_distribution = {}
    if target_column in df.columns:
        target_distribution = df[target_column].value_counts().to_dict()
        # Convert keys to strings for JSON safety.
        target_distribution = {str(k): int(v) for k, v in target_distribution.items()}

    duplicate_row_count = int(df.duplicated().sum())
    duplicate_rate = round(duplicate_row_count / len(df), 6) if len(df) > 0 else 0.0

    return {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "column_names": list(df.columns),
        "inferred_dtypes": dtypes,
        "missing_value_counts": {col: int(v) for col, v in missing.items()},
        "duplicate_row_count": duplicate_row_count,
        "duplicate_rate": duplicate_rate,
        "target_distribution": target_distribution,
        "schema_summary": schema_summary,
    }
