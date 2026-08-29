"""HTTP-facing deterministic training endpoint for the IDE.

Runs a single model directly through ``thelab.run.runner`` without going
through the agent proposal/approval flow.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from thelab.run.inputs import TaskTypeArg
from thelab.run.runner import run_model

from .datasets import DatasetNotFoundError, dataset_id_to_relative_path


def _workspace_root() -> Path:
    return Path(os.environ.get("THELAB_WORKSPACE_ROOT", "."))


def train_model(
    dataset_id: str,
    target: str,
    model: str,
    seed: int = 42,
    task_type: TaskTypeArg = "auto",
    hyperparameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Train a single model deterministically and return the run outcome."""
    try:
        dataset_path = dataset_id_to_relative_path(dataset_id)
    except DatasetNotFoundError as exc:
        raise DatasetNotFoundError(str(exc)) from exc

    outcome = run_model(
        dataset=dataset_path,
        target=target,
        model=model,
        seed=seed,
        output="runs",
        workspace_root=_workspace_root(),
        task_type=task_type,
        hyperparameters=hyperparameters or None,
    )
    return outcome
