"""Quick dataset inspection without creating a full run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .profile import profile_dataframe, read_csv


def inspect_dataset(dataset_path: Path | str, target_column: str | None = None) -> dict[str, Any]:
    """Read a CSV and return a concise profile.

    This is the exploratory counterpart to a full ``run_model`` call: it
    validates the file can be read and prints dataset shape, types, target
    distribution, and validation-style red flags without training anything.
    """
    path = Path(dataset_path)
    df = read_csv(path)
    profile = profile_dataframe(df, target_column or "")

    feature_columns = [col for col in df.columns if col != target_column]

    checks: list[dict[str, Any]] = []
    checks.append({
        "check": "dataset_not_empty",
        "passed": len(df) > 0,
        "message": "OK" if len(df) > 0 else "dataset has no rows",
    })
    checks.append({
        "check": "at_least_one_feature",
        "passed": len(feature_columns) > 0,
        "message": "OK" if len(feature_columns) > 0 else "no feature columns",
    })
    if target_column:
        checks.append({
            "check": "target_column_exists",
            "passed": target_column in df.columns,
            "message": f"target column '{target_column}' not found" if target_column not in df.columns else "OK",
        })

    numeric_features = df[feature_columns].select_dtypes(include="number").columns.tolist() if feature_columns else []
    checks.append({
        "check": "features_numeric",
        "passed": len(numeric_features) == len(feature_columns),
        "message": "OK" if len(numeric_features) == len(feature_columns) else f"non-numeric features: {[c for c in feature_columns if c not in numeric_features]}",
    })

    return {
        "path": str(path),
        "target": target_column,
        "features": feature_columns,
        "profile": profile,
        "checks": checks,
    }


def format_inspect(result: dict[str, Any]) -> str:
    """Return a human-readable string for an inspect result."""
    profile = result["profile"]
    lines = [
        f"Dataset: {result['path']}",
        f"Rows: {profile.get('row_count', 'N/A')}",
        f"Columns: {profile.get('column_count', 'N/A')}",
        f"Features: {', '.join(result['features'])}",
    ]
    if result.get("target"):
        lines.append(f"Target: {result['target']}")
        target_dist = profile.get("target_distribution", {})
        if target_dist:
            lines.append("Target distribution:")
            for cls, count in target_dist.items():
                lines.append(f"  - {cls}: {count}")
    lines.append("Checks:")
    for check in result["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        lines.append(f"  [{status}] {check['check']}: {check['message']}")
    return "\n".join(lines)
