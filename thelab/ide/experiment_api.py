"""HTTP-facing experiment endpoints for the IDE.

Starts agent-orchestrated experiments as background jobs, reports their
status, streams events, records user feedback for iteration, and returns
final results. Experiment state is persisted via ``ExperimentStore``; the
heavy work runs through the shared ``JobManager``.
"""

from __future__ import annotations

from typing import Any

from thelab.ide.datasets import resolve_dataset_path
from thelab.ide.experiment import Experiment, ExperimentState, ExperimentStore, create_experiment
from thelab.ide.jobs import get_job_manager


async def start_experiment(
    goal: str,
    dataset_id: str,
    target: str,
    feedback: str | None = None,
    provider_name: str = "mock",
) -> dict[str, Any]:
    """Create an experiment and queue its orchestration as a background job."""
    resolve_dataset_path(dataset_id)

    experiment, store = create_experiment(
        goal=goal,
        dataset_id=dataset_id,
        target=target,
        feedback=feedback,
    )

    manager = get_job_manager()
    job = await manager.submit(
        "experiment",
        {
            "experiment_id": experiment.experiment_id,
            "goal": goal,
            "dataset_id": dataset_id,
            "target": target,
            "feedback": feedback,
            "provider": provider_name,
        },
    )
    experiment.plan["job_id"] = job.job_id
    store.save(experiment)

    return {
        "experiment_id": experiment.experiment_id,
        "job_id": job.job_id,
        "state": experiment.state.value,
        "goal": goal,
        "dataset_id": dataset_id,
        "target": target,
    }


def _load_or_raise(experiment_id: str) -> tuple[Experiment, ExperimentStore]:
    store = ExperimentStore()
    experiment = store.load(experiment_id)
    if experiment is None:
        raise ValueError(f"experiment not found: {experiment_id}")
    return experiment, store


async def get_experiment_status(experiment_id: str) -> dict[str, Any]:
    """Return full experiment state plus its current job status."""
    experiment, _ = _load_or_raise(experiment_id)
    manager = get_job_manager()
    job_id = experiment.plan.get("job_id")
    job = await manager.get(job_id) if job_id else None
    data = experiment.to_dict()
    data["job"] = job.to_dict() if job is not None else None
    return data


async def get_experiment_events(experiment_id: str) -> str | None:
    """Return the job id whose event stream backs the experiment, if any."""
    experiment, _ = _load_or_raise(experiment_id)
    return experiment.plan.get("job_id")


async def add_experiment_feedback(experiment_id: str, feedback: str) -> dict[str, Any]:
    """Record user feedback and queue a new orchestration iteration."""
    if not feedback or not feedback.strip():
        raise ValueError("feedback must be a non-empty string")

    experiment, store = _load_or_raise(experiment_id)
    experiment.feedback = feedback.strip()
    experiment.update_state(ExperimentState.ITERATING)
    previous_job_id = experiment.plan.get("job_id")
    experiment.plan["previous_job_ids"] = [
        j for j in [previous_job_id, *experiment.plan.get("previous_job_ids", [])] if j
    ]
    store.save(experiment)

    manager = get_job_manager()
    job = await manager.submit(
        "experiment",
        {
            "experiment_id": experiment.experiment_id,
            "goal": experiment.goal,
            "dataset_id": experiment.dataset_id,
            "target": experiment.target,
            "feedback": experiment.feedback,
        },
    )
    experiment.plan["job_id"] = job.job_id
    store.save(experiment)

    return {
        "experiment_id": experiment.experiment_id,
        "job_id": job.job_id,
        "state": experiment.state.value,
        "feedback": experiment.feedback,
    }


async def get_experiment_results(experiment_id: str) -> dict[str, Any]:
    """Return experiment results: best run, metrics, and sub-agent findings."""
    experiment, _ = _load_or_raise(experiment_id)
    manager = get_job_manager()
    job_id = experiment.plan.get("job_id")
    job = await manager.get(job_id) if job_id else None

    data = experiment.to_dict()
    if job is not None and job.result is not None:
        data["training_results"] = job.result.get("training_results", [])
    data["job"] = job.to_dict() if job is not None else None
    return data


async def list_experiments(limit: int = 50) -> list[dict[str, Any]]:
    """List recent experiments."""
    return ExperimentStore().list_experiments(limit=limit)
