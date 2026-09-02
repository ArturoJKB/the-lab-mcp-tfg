"""HTTP-facing dataset preview and run comparison helpers for the IDE."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from thelab.mcp.common import discover_run_ids, get_runs_root, load_json_artifact

from .datasets import read_tabular, resolve_dataset_path

DEFAULT_PREVIEW_LIMIT = 100
MAX_PREVIEW_LIMIT = 1000


def _json_safe(value: Any) -> Any:
    """Convert pandas/numpy values into JSON-safe primitives."""
    if value is None:
        return None
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (int, str, bool)):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def preview_dataset(dataset_id: str, limit: int = DEFAULT_PREVIEW_LIMIT) -> dict[str, Any]:
    """Return a bounded preview of a dataset as JSON rows."""
    bounded_limit = max(1, min(limit, MAX_PREVIEW_LIMIT))
    path = resolve_dataset_path(dataset_id)
    try:
        df = read_tabular(path)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"cannot read dataset: {exc}") from exc

    columns = list(df.columns)
    total_rows = len(df)
    sliced = df.head(bounded_limit)

    column_types = {
        col: ("numeric" if pd.api.types.is_numeric_dtype(df[col]) else "text")
        for col in columns
    }

    rows = [
        {col: _json_safe(row.get(col)) for col in columns}
        for row in sliced.to_dict(orient="records")
    ]

    return {
        "dataset_id": dataset_id,
        "columns": [
            {"name": col, "dtype": column_types[col]}
            for col in columns
        ],
        "rows": rows,
        "total_rows": total_rows,
        "returned_rows": len(rows),
        "truncated": total_rows > len(rows),
    }


def compare_runs() -> dict[str, Any]:
    """Return a metrics comparison across completed runs."""
    runs_root = get_runs_root()
    entries: list[dict[str, Any]] = []
    for run_id in discover_run_ids(runs_root):
        manifest = load_json_artifact(runs_root, run_id, "manifest.json")
        if manifest is None or manifest.get("final_status") != "completed":
            continue
        inputs = load_json_artifact(runs_root, run_id, "inputs.json") or {}
        metrics = load_json_artifact(runs_root, run_id, "metrics.json") or {}
        entries.append(
            {
                "run_id": run_id,
                "model": inputs.get("model"),
                "target": inputs.get("target"),
                "task_type": manifest.get("task_type")
                or inputs.get("task_type")
                or "classification",
                "seed": inputs.get("seed"),
                "validation_status": manifest.get("validation_status"),
                # Sanitize NaN/Inf so Starlette's strict JSON encoder never 500s.
                "metrics": {
                    key: _json_safe(metrics.get(key))
                    for key in (
                        "test_accuracy",
                        "test_f1_macro",
                        "test_rmse",
                        "test_mae",
                        "test_r2",
                    )
                },
            }
        )

    entries.sort(key=lambda e: e["run_id"], reverse=True)
    return {"total": len(entries), "runs": entries}
