"""Compare metrics across completed runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from thelab.mcp.common import discover_run_ids, get_runs_root, load_json_artifact


def compare_runs(runs_root: Path | None = None) -> list[dict[str, Any]]:
    """Return a list of completed/approved runs with key metrics."""
    if runs_root is None:
        runs_root = get_runs_root()

    runs: list[dict[str, Any]] = []
    for run_id in discover_run_ids(runs_root):
        manifest = load_json_artifact(runs_root, run_id, "manifest.json")
        if manifest is None:
            continue
        if manifest.get("final_status") != "completed":
            continue
        if manifest.get("validation_status") != "approved":
            continue

        inputs = load_json_artifact(runs_root, run_id, "inputs.json") or {}
        metrics = load_json_artifact(runs_root, run_id, "metrics.json") or {}
        task_type = manifest.get("task_type") or inputs.get("task_type") or "classification"
        runs.append({
            "run_id": run_id,
            "dataset": inputs.get("dataset"),
            "target": inputs.get("target"),
            "model": inputs.get("model"),
            "seed": inputs.get("seed"),
            "task_type": task_type,
            "test_accuracy": metrics.get("test_accuracy"),
            "test_f1_macro": metrics.get("test_f1_macro"),
            "test_rmse": metrics.get("test_rmse"),
            "test_mae": metrics.get("test_mae"),
            "test_r2": metrics.get("test_r2"),
        })
    return runs


def format_comparison(runs: list[dict[str, Any]]) -> str:
    """Format a run comparison as a Markdown table grouped by task type."""
    if not runs:
        return "No completed/approved runs found."

    classification_runs = [r for r in runs if r["task_type"] == "classification"]
    regression_runs = [r for r in runs if r["task_type"] == "regression"]

    lines: list[str] = []

    if classification_runs:
        lines.extend([
            "## Classification runs",
            "",
            "| Run ID | Dataset | Target | Model | Seed | Test Accuracy | Test F1 Macro |",
            "|---|---|---|---|---|---|---|",
        ])
        for r in classification_runs:
            acc = f"{r['test_accuracy']:.6f}" if r.get("test_accuracy") is not None else "N/A"
            f1 = f"{r['test_f1_macro']:.6f}" if r.get("test_f1_macro") is not None else "N/A"
            lines.append(
                f"| {r['run_id']} | {r.get('dataset', 'N/A')} | {r.get('target', 'N/A')} | "
                f"{r.get('model', 'N/A')} | {r.get('seed', 'N/A')} | {acc} | {f1} |"
            )
        lines.append("")

    if regression_runs:
        lines.extend([
            "## Regression runs",
            "",
            "| Run ID | Dataset | Target | Model | Seed | Test RMSE | Test MAE | Test R2 |",
            "|---|---|---|---|---|---|---|---|",
        ])
        for r in regression_runs:
            rmse = f"{r['test_rmse']:.6f}" if r.get("test_rmse") is not None else "N/A"
            mae = f"{r['test_mae']:.6f}" if r.get("test_mae") is not None else "N/A"
            r2 = f"{r['test_r2']:.6f}" if r.get("test_r2") is not None else "N/A"
            lines.append(
                f"| {r['run_id']} | {r.get('dataset', 'N/A')} | {r.get('target', 'N/A')} | "
                f"{r.get('model', 'N/A')} | {r.get('seed', 'N/A')} | {rmse} | {mae} | {r2} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip()
