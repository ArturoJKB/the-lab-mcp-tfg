"""One-off prediction helper for the CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import joblib

from thelab.mcp.common import get_runs_root, load_json_artifact, safe_run_dir

from .inference import feature_columns, normalize_features


def _parse_features(raw: str, feature_columns: list[str]) -> list[list[float]]:
    """Parse a CLI feature string into a normalized feature matrix."""
    raw = raw.strip()
    if raw.startswith("["):
        parsed = json.loads(raw)
    else:
        values = [v.strip() for v in raw.split(",")]
        parsed = values if len(values) != 1 else values[0]
    return normalize_features([parsed], feature_columns)


def predict(run_id: str, features: list[Any], workspace_root: Path | str | None = None) -> dict[str, Any]:
    """Load an approved run and predict on the supplied features.

    Raises ``ValueError`` if the run is not approved/completed or the model
    cannot be loaded.
    """
    runs_root = get_runs_root() if workspace_root is None else Path(workspace_root) / "runs"

    manifest = load_json_artifact(runs_root, run_id, "manifest.json")
    if manifest is None:
        raise ValueError(f"manifest not found for run_id: {run_id}")
    if manifest.get("final_status") != "completed":
        raise ValueError(f"run {run_id} is not completed")
    if manifest.get("validation_status") != "approved":
        raise ValueError(f"run {run_id} is not approved")

    run_path = safe_run_dir(runs_root, run_id)
    if run_path is None:
        raise ValueError(f"run not found or unsafe: {run_id}")

    model_path = run_path / "model.joblib"
    if not model_path.is_file():
        raise ValueError(f"model.joblib not found for run_id: {run_id}")

    inputs = load_json_artifact(runs_root, run_id, "inputs.json") or {}
    target = inputs.get("target")
    if not target:
        raise ValueError(f"target column not found for run_id: {run_id}")

    data_profile = load_json_artifact(runs_root, run_id, "data_profile.json") or {}
    cols = feature_columns(data_profile, target)
    if not cols:
        raise ValueError(f"could not determine feature columns for run_id: {run_id}")

    normalized = normalize_features(features, cols)
    model = joblib.load(model_path)
    predictions = model.predict(normalized)

    return {
        "run_id": run_id,
        "model": inputs.get("model"),
        "target": target,
        "feature_columns": cols,
        "predictions": predictions.tolist() if hasattr(predictions, "tolist") else list(predictions),
    }


def predict_cli(run_id: str, features_raw: str, json_output: bool = False) -> int:
    """CLI wrapper for predict."""
    runs_root = get_runs_root()
    manifest = load_json_artifact(runs_root, run_id, "manifest.json")
    if manifest is None:
        print(f"Error: manifest not found for run_id: {run_id}", file=sys.stderr)
        return 1

    inputs = load_json_artifact(runs_root, run_id, "inputs.json") or {}
    target = inputs.get("target")
    data_profile = load_json_artifact(runs_root, run_id, "data_profile.json") or {}
    cols = feature_columns(data_profile, target) if target else []
    if not cols:
        print(f"Error: could not determine feature columns for run_id: {run_id}", file=sys.stderr)
        return 1

    try:
        features = _parse_features(features_raw, cols)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        result = predict(run_id, features)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        print(f"Prediction: {result['predictions']}")
    return 0
