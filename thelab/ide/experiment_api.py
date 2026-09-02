"""HTTP-facing experiment endpoints for the IDE.

Starts agent-orchestrated experiments as background jobs, reports their
status, streams events, records user feedback for iteration, and returns
final results. Experiment state is persisted via ``ExperimentStore``; the
heavy work runs through the shared ``JobManager``.
"""

from __future__ import annotations

import os
from pathlib import Path
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
    model: str | None = None,
) -> dict[str, Any]:
    """Create an experiment and queue its orchestration as a background job."""
    resolve_dataset_path(dataset_id)
    from thelab.agents.chat import create_provider

    try:
        create_provider(provider_name)  # fail fast on misconfigured providers
    except Exception as exc:
        raise ValueError(f"provider '{provider_name}' is not usable: {exc}") from exc


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
            "model": model,
        },
    )
    experiment.plan["job_id"] = job.job_id
    experiment.plan["provider"] = provider_name
    experiment.plan["model"] = model
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
            "provider": experiment.plan.get("provider", "mock"),
            "model": experiment.plan.get("model"),
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


async def run_proposal_as_experiment(proposal_id: str, principal: str = "ui") -> dict[str, Any]:
    """Approve a proposal and execute it as a first-class, SSE-visible experiment."""

    from thelab.agents.worker import ProposalStore

    proposals_dir = Path(os.environ.get("THELAB_PROPOSALS_DIR", "proposals"))
    proposal_store = ProposalStore(proposals_dir)
    if not proposal_store.exists(proposal_id):
        raise ValueError(f"proposal not found: {proposal_id}")

    proposal = proposal_store.load(proposal_id)
    experiment, store = create_experiment(
        goal=proposal.goal or f"Run proposal {proposal_id}",
        dataset_id=proposal.dataset,
        target=proposal.target,
    )
    experiment.sub_agent_results["Proposal"] = {
        "rationale": proposal.rationale,
        "model_grid": proposal.model_grid,
        "seeds": proposal.seeds,
        "proposal_id": proposal_id,
    }

    manager = get_job_manager()
    job = await manager.submit(
        "proposal_experiment",
        {"experiment_id": experiment.experiment_id, "proposal_id": proposal_id},
    )
    experiment.plan["job_id"] = job.job_id
    experiment.plan["proposal_id"] = proposal_id
    experiment.plan["principal"] = principal
    store.save(experiment)

    return {
        "experiment_id": experiment.experiment_id,
        "job_id": job.job_id,
        "state": experiment.state.value,
        "proposal_id": proposal_id,
    }


async def list_experiments(limit: int = 50) -> list[dict[str, Any]]:
    """List recent experiments."""
    return ExperimentStore().list_experiments(limit=limit)
