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
        runs.append({
            "run_id": run_id,
            "dataset": inputs.get("dataset"),
            "target": inputs.get("target"),
            "model": inputs.get("model"),
            "seed": inputs.get("seed"),
            "test_accuracy": metrics.get("test_accuracy"),
            "test_f1_macro": metrics.get("test_f1_macro"),
        })
    return runs


def format_comparison(runs: list[dict[str, Any]]) -> str:
    """Format a run comparison as a Markdown table."""
    if not runs:
        return "No completed/approved runs found."

    lines = [
        "| Run ID | Dataset | Target | Model | Seed | Test Accuracy | Test F1 Macro |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in runs:
        acc = f"{r['test_accuracy']:.6f}" if r.get("test_accuracy") is not None else "N/A"
        f1 = f"{r['test_f1_macro']:.6f}" if r.get("test_f1_macro") is not None else "N/A"
        lines.append(
            f"| {r['run_id']} | {r.get('dataset', 'N/A')} | {r.get('target', 'N/A')} | "
            f"{r.get('model', 'N/A')} | {r.get('seed', 'N/A')} | {acc} | {f1} |"
        )
    return "\n".join(lines)
