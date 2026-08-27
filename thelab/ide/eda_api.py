"""HTTP-facing EDA helpers for the IDE."""

from __future__ import annotations

from typing import Any

from thelab.eda import (
    class_balance,
    correlation_hints,
    feature_types,
    leakage_suspects,
    missing_profile,
    outlier_scan,
)
from thelab.ide.datasets import resolve_dataset_path
from thelab.run.profile import read_csv


class EdaError(ValueError):
    """Raised when EDA computation fails."""


def run_eda(dataset_id: str, target: str | None = None) -> dict[str, Any]:
    """Run the full deterministic EDA skill pack on a dataset.

    Returns a stable JSON-serializable structure. If ``target`` is provided
    and does not exist in the dataset, ``EdaError`` is raised.
    """
    # Let DatasetNotFoundError propagate so callers can return 404.
    path = resolve_dataset_path(dataset_id)

    try:
        df = read_csv(path)
    except Exception as exc:
        raise EdaError(f"cannot read dataset: {exc}") from exc

    if target is not None and target not in df.columns:
        raise EdaError(f"target column '{target}' not found")

    try:
        return {
            "dataset_id": dataset_id,
            "rows": len(df),
            "columns": len(df.columns),
            "column_names": list(df.columns),
            "feature_types": feature_types(df, target=target),
            "missing_profile": missing_profile(df, target=target),
            "class_balance": class_balance(df, target=target),
            "correlation_hints": correlation_hints(df, target=target),
            "outlier_scan": outlier_scan(df, target=target),
            "leakage_suspects": leakage_suspects(df, target=target),
        }
    except Exception as exc:
        raise EdaError(f"eda computation failed: {exc}") from exc
