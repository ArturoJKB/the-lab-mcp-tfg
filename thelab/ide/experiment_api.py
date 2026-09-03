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
    agentic_round: bool = False,
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
            "agentic_round": bool(agentic_round),
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

    # The HTTP call itself is the human approval (the UI click); record it
    # through the single approval gate before the job is queued. A rejected
    # proposal is never executed.
    from thelab.agents.approval import ApprovalDenied, record_human_approval

    try:
        record_human_approval(proposal_store, proposal_id, principal="ui")
    except ApprovalDenied as exc:
        raise ValueError(str(exc)) from exc

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


async def approve_agentic_round(experiment_id: str, principal: str = "ui") -> dict[str, Any]:
    """Record the human approval of an agentic-round proposal and queue execution.

    The gate records the UI principal; the execution job itself never approves.
    """
    experiment, store = _load_or_raise(experiment_id)
    round_info = experiment.plan.get("agentic_round") or {}
    proposal_id = round_info.get("proposal_id")
    if not proposal_id:
        raise ValueError(f"experiment {experiment_id} has no agentic-round proposal")

    from thelab.agents.approval import ApprovalDenied, record_human_approval
    from thelab.agents.worker import ProposalStore

    proposal_store = ProposalStore(os.environ.get("THELAB_PROPOSALS_DIR", "proposals"))
    if not proposal_store.exists(proposal_id):
        raise ValueError(f"round proposal not found: {proposal_id}")
    try:
        record_human_approval(proposal_store, proposal_id, principal=principal)
    except ApprovalDenied as exc:
        raise ValueError(str(exc)) from exc

    manager = get_job_manager()
    job = await manager.submit(
        "agentic_round_execute",
        {"experiment_id": experiment_id, "proposal_id": proposal_id},
    )
    # Rotate the streamed job so the UI SSE stream follows the execution.
    previous_job_ids = [j for j in experiment.plan.get("previous_job_ids", []) if j]
    old_job_id = experiment.plan.get("job_id")
    if old_job_id and old_job_id != job.job_id and old_job_id not in previous_job_ids:
        previous_job_ids.append(old_job_id)
    experiment.plan["job_id"] = job.job_id
    experiment.plan["previous_job_ids"] = previous_job_ids
    experiment.plan["agentic_round"]["execution_job_id"] = job.job_id
    experiment.plan["agentic_round"]["status"] = "approved"
    experiment.update_state(ExperimentState.TRAINING)
    store.save(experiment)
    return {
        "experiment_id": experiment_id,
        "proposal_id": proposal_id,
        "job_id": job.job_id,
        "state": experiment.state.value,
    }


async def reject_agentic_round(
    experiment_id: str, principal: str = "ui", reason: str = ""
) -> dict[str, Any]:
    """Reject the agentic-round proposal; the deterministic result stands."""
    experiment, store = _load_or_raise(experiment_id)
    round_info = experiment.plan.get("agentic_round") or {}
    proposal_id = round_info.get("proposal_id")
    if not proposal_id:
        raise ValueError(f"experiment {experiment_id} has no agentic-round proposal")

    from thelab.agents.worker import ProposalStore

    proposal_store = ProposalStore(os.environ.get("THELAB_PROPOSALS_DIR", "proposals"))
    if not proposal_store.exists(proposal_id):
        raise ValueError(f"round proposal not found: {proposal_id}")
    proposal_store.reject(proposal_id, principal=principal, reason=reason)

    round_info["status"] = "rejected"
    round_info["rejection_reason"] = reason
    experiment.plan["agentic_round"] = round_info
    # Rejection is a first-class outcome: the deterministic result stands.
    experiment.update_state(ExperimentState.COMPLETED)
    store.save(experiment)
    return {
        "experiment_id": experiment_id,
        "proposal_id": proposal_id,
        "state": experiment.state.value,
        "status": "rejected",
    }


async def get_agentic_round(experiment_id: str) -> dict[str, Any]:
    """Return the agentic-round record (brief, transform, proposal, comparison)."""
    experiment, _ = _load_or_raise(experiment_id)
    experiments_dir = Path(os.environ.get("THELAB_EXPERIMENTS_DIR", Path(".thelab") / "experiments"))
    record_path = experiments_dir / f"{experiment_id}.agentic_round.json"
    record = None
    if record_path.is_file():
        import json

        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            record = None
    return {
        "experiment_id": experiment_id,
        "plan": experiment.plan.get("agentic_round", {}),
        "state": experiment.state.value,
        "record": record,
    }
