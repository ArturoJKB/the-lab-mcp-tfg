"""HTTP-facing agent iteration helper for the IDE.

Given a completed run, build a grounded improvement goal and ask the worker
agent to propose a follow-up experiment using deterministic EDA and prior-run
metrics.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from thelab.mcp.common import get_runs_root, load_json_artifact

from .datasets import DatasetNotFoundError, resolve_dataset_path
from .worker_api import generate_proposal


def _workspace_root() -> Path:
    return Path(os.environ.get("THELAB_WORKSPACE_ROOT", "."))


def _path_to_dataset_id(dataset_path: str | None) -> str | None:
    """Convert a workspace-relative dataset path to a stable dataset_id."""
    if not dataset_path:
        return None
    path = _workspace_root() / dataset_path
    try:
        resolved = path.resolve()
    except OSError:
        return None
    uploads_root = Path(os.environ.get("THELAB_UPLOADS_DIR", "data/uploads"))
    if not uploads_root.is_absolute():
        uploads_root = _workspace_root() / uploads_root
    fixtures_root = Path(os.environ.get("THELAB_FIXTURES_DIR", "data/fixtures"))
    if not fixtures_root.is_absolute():
        fixtures_root = _workspace_root() / fixtures_root
    try:
        resolved.relative_to(uploads_root.resolve())
        return f"uploads/{resolved.name}"
    except ValueError:
        pass
    try:
        resolved.relative_to(fixtures_root.resolve())
        return f"fixtures/{resolved.name}"
    except ValueError:
        pass
    return None


def _load_run_summary(run_id: str) -> dict[str, Any]:
    """Load manifest and inputs for a run, returning a summary or raising."""
    runs_root = Path(get_runs_root())
    manifest = load_json_artifact(runs_root, run_id, "manifest.json")
    if manifest is None:
        raise ValueError(f"run not found: {run_id}")
    if manifest.get("final_status") != "completed":
        raise ValueError(f"run is not completed: {run_id}")
    inputs = load_json_artifact(runs_root, run_id, "inputs.json") or {}
    metrics = load_json_artifact(runs_root, run_id, "metrics.json") or {}
    return {
        "run_id": run_id,
        "dataset_path": inputs.get("dataset"),
        "target": inputs.get("target"),
        "model": inputs.get("model"),
        "task_type": manifest.get("task_type") or inputs.get("task_type") or "classification",
        "metrics": metrics,
    }


def _build_iteration_goal(summary: dict[str, Any]) -> str:
    """Build a grounded goal prompt for the worker agent."""
    task_type = summary["task_type"]
    if task_type == "regression":
        primary = f"RMSE={summary['metrics'].get('test_rmse')}"
    else:
        primary = f"accuracy={summary['metrics'].get('test_accuracy')}"
    return (
        f"Improve on run {summary['run_id']} ({summary['model']}) "
        f"which achieved {primary} predicting '{summary['target']}'. "
        "Propose a better experiment."
    )


async def iterate_on_run(run_id: str, goal: str | None = None) -> dict[str, Any]:
    """Create an improvement proposal for a completed run."""
    summary = _load_run_summary(run_id)
    dataset_id = _path_to_dataset_id(summary.get("dataset_path"))
    if dataset_id is None:
        raise DatasetNotFoundError(f"could not resolve dataset for run: {run_id}")
    # Validate that the dataset still exists.
    resolve_dataset_path(dataset_id)

    target = summary["target"]
    if not target:
        raise ValueError(f"target not found for run: {run_id}")

    resolved_goal = goal or _build_iteration_goal(summary)
    proposal = await generate_proposal(
        dataset_id=dataset_id,
        target=target,
        goal=resolved_goal,
    )
    return proposal
