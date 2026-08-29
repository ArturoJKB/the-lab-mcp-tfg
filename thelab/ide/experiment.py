"""Experiment state machine and persistence."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class ExperimentState(StrEnum):
    """States in the experiment lifecycle."""

    PENDING = "pending"           # Created, waiting for approval
    PLANNING = "planning"         # Orchestrator analyzing/creating plan
    CLEANING = "cleaning"         # FeatureEngineer running cleaning
    TRAINING = "training"         # ModelSelector running training
    EVALUATING = "evaluating"     # EDAAnalyst reviewing results
    COMPLETED = "completed"       # Best model found, experiment done
    ITERATING = "iterating"       # User gave feedback, re-planning
    FAILED = "failed"             # Experiment failed
    CANCELLED = "cancelled"       # Stopped by user request


class Experiment:
    """Represents an experiment with full state tracking."""

    def __init__(
        self,
        experiment_id: str,
        goal: str,
        dataset_id: str,
        target: str,
        feedback: str | None = None,
        state: ExperimentState = ExperimentState.PENDING,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        plan: dict[str, Any] | None = None,
        sub_agent_results: dict[str, Any] | None = None,
        best_run_id: str | None = None,
        best_metrics: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.experiment_id = experiment_id
        self.goal = goal
        self.dataset_id = dataset_id
        self.target = target
        self.feedback = feedback
        self.state = state
        self.created_at = created_at or datetime.now(UTC)
        self.updated_at = updated_at or datetime.now(UTC)
        self.plan = plan or {}
        self.sub_agent_results = sub_agent_results or {}
        self.best_run_id = best_run_id
        self.best_metrics = best_metrics
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "goal": self.goal,
            "dataset_id": self.dataset_id,
            "target": self.target,
            "feedback": self.feedback,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "plan": self.plan,
            "sub_agent_results": self.sub_agent_results,
            "best_run_id": self.best_run_id,
            "best_metrics": self.best_metrics,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Experiment:
        return cls(
            experiment_id=data["experiment_id"],
            goal=data["goal"],
            dataset_id=data["dataset_id"],
            target=data["target"],
            feedback=data.get("feedback"),
            state=ExperimentState(data["state"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            plan=data.get("plan", {}),
            sub_agent_results=data.get("sub_agent_results", {}),
            best_run_id=data.get("best_run_id"),
            best_metrics=data.get("best_metrics"),
            error=data.get("error"),
        )

    def update_state(self, state: ExperimentState) -> None:
        self.state = state
        self.updated_at = datetime.now(UTC)

    def add_sub_agent_result(self, agent_type: str, result: dict[str, Any]) -> None:
        self.sub_agent_results[agent_type] = result
        self.updated_at = datetime.now(UTC)


class ExperimentStore:
    """Persists experiments to disk."""

    def __init__(self, experiments_dir: Path | str | None = None) -> None:
        env_path = os.environ.get("THELAB_EXPERIMENTS_DIR")
        if env_path:
            self.experiments_dir = Path(env_path)
        elif experiments_dir:
            self.experiments_dir = Path(experiments_dir)
        else:
            self.experiments_dir = Path(".thelab") / "experiments"
        self.experiments_dir.mkdir(parents=True, exist_ok=True)

    def _experiment_path(self, experiment_id: str) -> Path:
        return self.experiments_dir / f"{experiment_id}.json"

    def save(self, experiment: Experiment) -> Path:
        """Persist an experiment and return its path."""
        experiment.updated_at = datetime.now(UTC)
        path = self._experiment_path(experiment.experiment_id)
        path.write_text(json.dumps(experiment.to_dict(), indent=2), encoding="utf-8")
        return path

    def load(self, experiment_id: str) -> Experiment | None:
        """Load an experiment by id."""
        path = self._experiment_path(experiment_id)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Experiment.from_dict(data)

    def exists(self, experiment_id: str) -> bool:
        return self._experiment_path(experiment_id).is_file()

    def list_experiments(self, limit: int = 50) -> list[dict[str, Any]]:
        """List recent experiments."""
        experiments = []
        for path in sorted(self.experiments_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                experiments.append({
                    "experiment_id": data["experiment_id"],
                    "goal": data["goal"],
                    "dataset_id": data["dataset_id"],
                    "target": data["target"],
                    "state": data["state"],
                    "created_at": data["created_at"],
                    "updated_at": data["updated_at"],
                    "best_run_id": data.get("best_run_id"),
                })
                if len(experiments) >= limit:
                    break
            except Exception:
                continue
        return experiments


def generate_experiment_id() -> str:
    return f"exp-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def create_experiment(
    goal: str,
    dataset_id: str,
    target: str,
    feedback: str | None = None,
    experiments_dir: Path | str | None = None,
) -> tuple[Experiment, ExperimentStore]:
    """Factory to create a new experiment with its store."""
    store = ExperimentStore(experiments_dir)
    experiment_id = f"exp-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    experiment = Experiment(
        experiment_id=experiment_id,
        goal=goal,
        dataset_id=dataset_id,
        target=target,
        feedback=feedback,
        state=ExperimentState.PENDING,
    )
    store.save(experiment)
    return experiment, store
