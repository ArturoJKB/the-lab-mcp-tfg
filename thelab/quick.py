"""Lightweight Python API for exploratory work in notebooks or scripts.

This module wraps the deterministic runner with a simpler interface. It is
intentionally separate from the CLI so that notebooks can import a small,
obvious API without pulling in argparse.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .run.inputs import TaskTypeArg
from .run.model_registry import MODEL_REGISTRY
from .run.prediction import predict
from .run.runner import run_model

__all__ = [
    "Experiment",
    "compare",
    "experiment",
    "list_models",
    "predict",
    "run_model",
    "try_all_models",
]


class Experiment:
    """Result of a quick experiment."""

    def __init__(self, result: dict[str, Any], workspace_root: Path | str | None = None):
        self._result = result
        self._workspace_root = Path(workspace_root) if workspace_root else None

    @property
    def run_id(self) -> str:
        return str(self._result["run_id"])

    @property
    def status(self) -> str:
        return str(self._result["status"])

    @property
    def model(self) -> str:
        return str(self._result["model"])

    @property
    def metrics(self) -> dict[str, Any]:
        metrics: dict[str, Any] = self._result.get("metrics", {})
        return metrics

    @property
    def run_dir(self) -> Path | None:
        rd = self._result.get("run_dir")
        return Path(rd) if rd else None

    def predict(self, features: list[Any]) -> list[Any]:
        """Predict using the trained run.

        Only works when the experiment was persisted (i.e. not a dry run).
        """
        if self.run_dir is None:
            raise ValueError("cannot predict from a dry-run experiment")
        result = predict(self.run_id, [features], workspace_root=self._workspace_root)
        predictions: list[Any] = result["predictions"]
        return predictions

    def __repr__(self) -> str:
        return f"Experiment(run_id={self.run_id!r}, model={self.model!r}, status={self.status!r})"


def experiment(
    dataset: Path | str,
    target: str,
    model: str = "logistic_regression",
    seed: int = 42,
    output: str = "runs",
    dry_run: bool = False,
    workspace_root: Path | str | None = None,
    task_type: TaskTypeArg = "auto",
) -> Experiment:
    """Train a model and return a lightweight Experiment handle.

    Example::

        from thelab.quick import experiment

        exp = experiment("examples/iris.csv", target="species", model="svc")
        print(exp.metrics["test_accuracy"])
        print(exp.predict([5.1, 3.5, 1.4, 0.2]))
    """
    result = run_model(
        dataset=dataset,
        target=target,
        model=model,
        seed=seed,
        output=output,
        dry_run=dry_run,
        workspace_root=workspace_root,
        task_type=task_type,
    )
    return Experiment(result, workspace_root=workspace_root)


def compare(
    dataset: Path | str,
    target: str,
    seed: int = 42,
    workspace_root: Path | str | None = None,
    task_type: TaskTypeArg = "auto",
) -> list[Experiment]:
    """Train every registered model and return the results.

    Runs are executed in dry-run mode so nothing is persisted. This is useful
    for quickly picking a promising model before running a full experiment.
    """
    results = try_all_models(
        dataset=dataset,
        target=target,
        seed=seed,
        dry_run=True,
        workspace_root=workspace_root,
        task_type=task_type,
    )
    return [Experiment(r, workspace_root=workspace_root) for r in results]


def list_models() -> list[str]:
    """Return all registered model names."""
    return MODEL_REGISTRY.list_models()


def try_all_models(
    dataset: Path | str,
    target: str,
    seed: int = 42,
    output: str = "scratch",
    workspace_root: Path | str | None = None,
    dry_run: bool = True,
    task_type: TaskTypeArg = "auto",
) -> list[dict[str, Any]]:
    """Train every registered model and return raw result dicts, best first.

    Results are sorted best-first by task-appropriate metric. Prefer
    :func:`compare` for ``Experiment`` handles; this thin wrapper exposes the
    runner API.
    """
    from .run.runner import try_all_models as _try_all

    return _try_all(
        dataset=dataset,
        target=target,
        seed=seed,
        output=output,
        workspace_root=workspace_root,
        dry_run=dry_run,
        task_type=task_type,
    )
