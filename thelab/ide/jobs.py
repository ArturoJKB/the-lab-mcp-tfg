"""Background job manager for the IDE.

Jobs are executed asynchronously so the UI remains responsive while training
or batch runs execute. Each job gets a stable ID, an in-memory event stream,
and a persisted summary under ``.thelab/jobs/``.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thelab.ide.experiment import ExperimentState, ExperimentStore
from thelab.ide.orchestrator import (
    ExperimentOrchestrator,
    OrchestrationCancelled,
    OrchestrationFailed,
)
from thelab.ide.proposals_api import run_proposal
from thelab.ide.train_api import train_model
from thelab.mcp.common import load_json_artifact


class JobError(ValueError):
    """Raised when a job submission or lookup fails."""


def _json_safe(value: Any) -> Any:
    """Recursively convert job results into JSON-safe primitives.

    Non-finite floats become None; numpy/pandas scalars fall back to str.
    """
    import math

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


class JobCancelled(RuntimeError):
    """Raised internally when a cooperative cancellation completes a job."""


@dataclass
class JobEvent:
    """A single event emitted by a background job."""

    timestamp: str
    level: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
            "data": self.data,
        }


@dataclass
class Job:
    """In-memory representation of a background job."""

    job_id: str
    job_type: str
    payload: dict[str, Any]
    status: str = "pending"
    created_at: str = ""
    updated_at: str = ""
    events: list[JobEvent] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    cancel_requested: bool = False
    _event_queue: asyncio.Queue[JobEvent] = field(default_factory=asyncio.Queue)
    _event_subscribers: list[asyncio.Queue[JobEvent]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _utcnow_iso()
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "events": [e.to_dict() for e in self.events],
            "result": self.result,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
        }

    def emit(self, level: str, message: str, data: dict[str, Any] | None = None) -> None:
        event = JobEvent(timestamp=_utcnow_iso(), level=level, message=message, data=data or {})
        self.events.append(event)
        self.updated_at = event.timestamp
        self._event_queue.put_nowait(event)
        for queue in list(self._event_subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue[JobEvent]:
        queue: asyncio.Queue[JobEvent] = asyncio.Queue(maxsize=256)
        self._event_subscribers.append(queue)
        # Replay existing events so the client does not miss history.
        for event in self.events:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                break
        return queue

    def unsubscribe(self, queue: asyncio.Queue[JobEvent]) -> None:
        if queue in self._event_subscribers:
            self._event_subscribers.remove(queue)


class JobManager:
    """Async job queue with in-memory state and persisted summaries."""

    def __init__(self, jobs_dir: Path | str | None = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()
        self._jobs_dir = Path(jobs_dir) if jobs_dir else Path(".thelab") / "jobs"

    def _ensure_dir(self) -> None:
        self._jobs_dir.mkdir(parents=True, exist_ok=True)

    def _persist(self, job: Job) -> None:
        self._ensure_dir()
        path = self._jobs_dir / f"{job.job_id}.json"
        try:
            path.write_text(json.dumps(job.to_dict(), indent=2, default=str), encoding="utf-8")
        except OSError:
            pass

    async def submit(self, job_type: str, payload: dict[str, Any]) -> Job:
        """Validate and enqueue a background job."""
        if job_type not in {
            "train",
            "batch",
            "experiment",
            "try_all",
            "proposal_experiment",
            "agentic_round_execute",
        }:
            raise JobError(f"unsupported job type: {job_type}")

        job_id = _generate_job_id()
        job = Job(job_id=job_id, job_type=job_type, payload=payload)
        job.emit("info", f"Job {job_id} queued ({job_type})")

        async with self._lock:
            self._jobs[job_id] = job

        self._persist(job)
        # The event loop only keeps a weak reference to tasks; retain a strong
        # one so a running job cannot be garbage-collected mid-flight.
        task = asyncio.create_task(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def cancel(self, job_id: str) -> Job | None:
        """Request cooperative cancellation of a running job."""
        job = await self.get(job_id)
        if job is None:
            return None
        if job.status in {"pending", "running"}:
            job.cancel_requested = True
            job.emit("warn", "Cancellation requested; stopping at the next entry or stage")
        return job

    async def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    async def events(self, job_id: str) -> AsyncGenerator[JobEvent, None]:
        job = await self.get(job_id)
        if job is None:
            return

        queue = job.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                except TimeoutError:
                    if job.status in {"completed", "failed", "rejected"}:
                        return
                    continue
                yield event
                if event.level == "done":
                    return
        finally:
            job.unsubscribe(queue)

    async def _run(self, job: Job) -> None:
        job.status = "running"
        job.emit("info", "Job started")
        self._persist(job)

        try:
            if job.job_type == "train":
                result = await self._run_train(job)
            elif job.job_type == "batch":
                result = await self._run_batch(job)
            elif job.job_type == "experiment":
                result = await self._run_experiment(job)
            elif job.job_type == "try_all":
                result = await self._run_try_all(job)
            elif job.job_type == "proposal_experiment":
                result = await self._run_proposal_experiment(job)
            elif job.job_type == "agentic_round_execute":
                result = await self._run_agentic_round_execute(job)
            else:
                raise JobError(f"unsupported job type: {job.job_type}")

            job.result = result
            if job.cancel_requested:
                job.status = "cancelled"
                job.emit("warn", "Job cancelled by user", {"result": result})
            elif result.get("status") in {"failed", "partial"} or result.get("failed", 0) > 0:
                job.status = "failed" if result.get("status") == "failed" else "completed"
                job.emit("warn", "Job finished with failures", {"result": result})
            else:
                job.status = "completed"
                job.emit("info", "Job completed", {"result": result})
        except OrchestrationCancelled:
            job.status = "cancelled"
            job.error = "cancelled by user"
            job.emit("warn", "Job cancelled by user")
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = str(exc)
            job.emit("error", f"Job failed: {exc}")
        finally:
            job.emit("done", "Job done")
            self._persist(job)

    async def _run_train(self, job: Job) -> dict[str, Any]:
        payload = job.payload
        return await asyncio.to_thread(
            train_model,
            dataset_id=payload["dataset_id"],
            target=payload["target"],
            model=payload["model"],
            seed=int(payload.get("seed", 42)),
            task_type=payload.get("task_type", "auto"),
            hyperparameters=payload.get("hyperparameters"),
        )

    async def _run_try_all(self, job: Job) -> dict[str, Any]:
        """Dry-run every registered model against a dataset; progress per model."""
        payload = job.payload
        dataset_id = payload.get("dataset_id", "")
        target = payload.get("target", "")
        if not dataset_id or not target:
            raise JobError("try_all job requires dataset_id and target")

        from thelab.ide.datasets import dataset_id_to_relative_path
        from thelab.run.runner import try_all_models

        def on_result(result: dict[str, Any]) -> None:
            job.emit(
                "info",
                f"model {result.get('model')}: {result.get('status')}",
                {"stage": "try_all", "model": result.get("model")},
            )

        dataset_path = await asyncio.to_thread(dataset_id_to_relative_path, dataset_id)
        results = await asyncio.to_thread(
            try_all_models,
            dataset_path,
            target,
            int(payload.get("seed", 42)),
            "scratch",
            Path(os.environ.get("THELAB_WORKSPACE_ROOT", ".")),
            True,  # dry_run
            payload.get("task_type", "auto"),
            on_result,
            lambda: not job.cancel_requested,
        )
        safe_results: dict[str, Any] = _json_safe(
            {
                "dataset_id": dataset_id,
                "target": target,
                "results": results,
                "best": next((r for r in results if r.get("status") == "completed"), None),
            }
        )
        return safe_results

    async def _run_proposal_experiment(self, job: Job) -> dict[str, Any]:
        """Execute an approved proposal as a first-class experiment (SSE-visible)."""
        payload = job.payload
        experiment_id = payload.get("experiment_id")
        proposal_id = payload.get("proposal_id")
        if not experiment_id or not proposal_id:
            raise JobError("proposal_experiment requires experiment_id and proposal_id")

        store = ExperimentStore()
        experiment = store.load(experiment_id)
        if experiment is None:
            raise JobError(f"experiment not found: {experiment_id}")

        from thelab.agents.approval import ApprovalDenied, HumanApprovalRequired, ensure_executable
        from thelab.agents.worker import ProposalStore

        proposals_dir = os.environ.get("THELAB_PROPOSALS_DIR", "proposals")
        proposal_store = ProposalStore(proposals_dir)
        if not proposal_store.exists(proposal_id):
            raise JobError(f"proposal not found: {proposal_id}")
        # The job executor never approves. Human approval happens upstream
        # (UI click on /run-as-experiment or /approve-and-run, or the CLI).
        try:
            ensure_executable(
                proposal_store,
                proposal_id,
                principal=f"proposal_experiment:{experiment_id}",
                allow_auto=False,
            )
        except (ApprovalDenied, HumanApprovalRequired) as exc:
            raise JobError(str(exc)) from exc

        experiment.update_state(ExperimentState.TRAINING)
        store.save(experiment)
        job.emit("info", f"Running approved proposal {proposal_id}", {"stage": "training"})

        from thelab.run.batch import BatchRunner

        batch_path = proposal_store.write_batch_config(proposal_id)
        runner = BatchRunner(
            workspace_root=Path(os.environ.get("THELAB_WORKSPACE_ROOT", "."))
        )
        entries = runner.load_config(batch_path)

        def on_result(result: Any) -> None:
            job.emit(
                "info",
                f"model {result.entry.model} (seed {result.entry.seed}): {result.status}",
                {"stage": "training", "model": result.entry.model},
            )

        results = runner.run(
            entries,
            on_result=on_result,
            should_continue=lambda: not job.cancel_requested,
        )
        if job.cancel_requested:
            experiment.update_state(ExperimentState.CANCELLED)
            experiment.error = "cancelled by user"
            store.save(experiment)
            return {
                "status": "cancelled",
                "training_results": [
                    {
                        "model": r.entry.model,
                        "seed": r.entry.seed,
                        "status": r.status,
                        "run_id": r.run_id,
                        "error": r.error,
                    }
                    for r in results
                ],
            }

        training_results = [
            {
                "model": r.entry.model,
                "seed": r.entry.seed,
                "status": r.status,
                "run_id": r.run_id,
                "metrics": r.metrics,
                "error": r.error,
            }
            for r in results
        ]
        best = next((r for r in results if r.status == "completed"), None)
        if best is not None and best.run_id:
            experiment.best_run_id = best.run_id
            metrics = load_json_artifact(
                Path(os.environ.get("THELAB_RUNS_ROOT", "runs")), best.run_id, "metrics.json"
            )
            experiment.best_metrics = _json_safe(metrics or {})
        completed = sum(1 for r in results if r.status == "completed")
        experiment.update_state(ExperimentState.COMPLETED if completed else ExperimentState.FAILED)
        if not completed:
            experiment.error = "no candidate models completed"
        store.save(experiment)

        return {
            "status": "completed" if completed else "failed",
            "completed": completed,
            "total": len(results),
            "training_results": training_results,
        }

    async def _run_agentic_round_execute(self, job: Job) -> dict[str, Any]:
        """Execute an approved agentic-round proposal through the factory (human-gated)."""
        payload = job.payload
        experiment_id = payload.get("experiment_id")
        proposal_id = payload.get("proposal_id")
        if not experiment_id or not proposal_id:
            raise JobError("agentic_round_execute requires experiment_id and proposal_id")

        store = ExperimentStore()
        experiment = store.load(experiment_id)
        if experiment is None:
            raise JobError(f"experiment not found: {experiment_id}")

        from thelab.agents.approval import ApprovalDenied, HumanApprovalRequired
        from thelab.ide.agentic_round import execute_approved_round

        experiment.update_state(ExperimentState.TRAINING)
        store.save(experiment)

        def on_event(_stage: str, message: str) -> None:
            job.emit("info", message, {"stage": "agentic_round", "experiment_id": experiment_id})

        try:
            # Blocking in the coroutine (proven pattern; executor hops hang
            # non-deterministically — see P5_PLAN X1 notes).
            result = execute_approved_round(
                experiment,
                proposal_id,
                on_event=on_event,
                should_continue=lambda: not job.cancel_requested,
                runs_root=os.environ.get("THELAB_RUNS_ROOT", "runs"),
            )
        except (ApprovalDenied, HumanApprovalRequired) as exc:
            experiment.update_state(ExperimentState.AWAITING_APPROVAL)
            experiment.error = str(exc)
            store.save(experiment)
            job.emit("warn", str(exc), {"stage": "agentic_round"})
            return {"status": "awaiting_approval", "proposal_id": proposal_id, "error": str(exc)}

        if result.get("status") == "completed":
            comparison = result.get("comparison", {})
            agentic_best = (comparison.get("agentic_best") or {})
            experiment.sub_agent_results = {
                **experiment.sub_agent_results,
                "AgenticRound": {
                    "proposal_id": proposal_id,
                    "comparison": comparison,
                },
            }
            # Keep the overall best across deterministic and agentic runs,
            # recording which arm produced it.
            det_metrics = experiment.best_metrics or {}
            agent_metrics = agentic_best.get("metrics") or {}
            det_acc = det_metrics.get("test_accuracy", -1.0)
            agent_acc = agent_metrics.get("test_accuracy", -1.0)
            if isinstance(agent_acc, (int, float)) and agent_acc > (det_acc if isinstance(det_acc, (int, float)) else -1.0):
                experiment.best_run_id = agentic_best.get("run_id")
                experiment.best_metrics = _json_safe(agent_metrics)
                experiment.plan["best_source"] = "agentic_round"
            experiment.update_state(ExperimentState.COMPLETED)
        else:
            experiment.update_state(ExperimentState.FAILED)
            experiment.error = "agentic round training produced no completed runs"
        store.save(experiment)
        return result

    async def _run_batch(self, job: Job) -> dict[str, Any]:
        proposal_id = job.payload.get("proposal_id")
        if not proposal_id:
            raise JobError("batch job requires proposal_id")
        return await asyncio.to_thread(
            run_proposal,
            proposal_id,
            should_continue=lambda: not job.cancel_requested,
            on_result=lambda r: job.emit(
                "info",
                f"entry {r.entry.model} (seed {r.entry.seed}): {r.status}",
                {"stage": "training"},
            ),
        )

    async def _run_experiment(self, job: Job) -> dict[str, Any]:
        """Run a full agent-orchestrated experiment, streaming stage events."""
        payload = job.payload
        experiment_id = payload.get("experiment_id")
        if not experiment_id:
            raise JobError("experiment job requires experiment_id")

        store = ExperimentStore()
        experiment = store.load(experiment_id)
        if experiment is None:
            raise JobError(f"experiment not found: {experiment_id}")

        runs_root = os.environ.get("THELAB_RUNS_ROOT", "runs")
        orchestrator = ExperimentOrchestrator(
            runs_root=runs_root,
            proposals_dir=os.environ.get("THELAB_PROPOSALS_DIR", "proposals"),
        )

        state_by_stage = {
            "planning": ExperimentState.PLANNING,
            "cleaning": ExperimentState.CLEANING,
            "training": ExperimentState.TRAINING,
            "evaluating": ExperimentState.EVALUATING,
        }

        def on_event(stage: str, message: str) -> None:
            job.emit("info", message, {"stage": stage, "experiment_id": experiment_id})
            state = state_by_stage.get(stage)
            if state is not None:
                experiment.update_state(state)
                store.save(experiment)

        provider_name = payload.get("provider", "mock")
        try:
            if provider_name != "mock":
                from thelab.agents.chat import create_provider

                provider = create_provider(provider_name, payload.get("model"))
            else:
                provider = None
        except Exception as exc:  # noqa: BLE001 - provider config errors fail fast
            experiment.update_state(ExperimentState.FAILED)
            experiment.error = f"provider '{provider_name}' is not usable: {exc}"
            store.save(experiment)
            raise JobError(experiment.error) from exc

        job.emit("info", "Experiment started", {"stage": "planning", "experiment_id": experiment_id})
        try:
            result = await orchestrator.orchestrate(
                goal=payload.get("goal", ""),
                dataset_id=payload.get("dataset_id", ""),
                target=payload.get("target", ""),
                feedback=payload.get("feedback"),
                provider=provider,
                on_event=on_event,
                should_continue=lambda: not job.cancel_requested,
                experiment_id=experiment_id,
            )
        except OrchestrationCancelled:
            experiment.update_state(ExperimentState.CANCELLED)
            experiment.error = "cancelled by user"
            store.save(experiment)
            raise
        except OrchestrationFailed as exc:
            # Deterministic-stage failure: the provider is not to blame.
            experiment.update_state(ExperimentState.FAILED)
            experiment.error = str(exc)
            store.save(experiment)
            raise JobError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - mark experiment failed, not stuck
            detail = str(exc)
            if provider is not None:
                hint = ""
                if "Errno 111" in detail or "Connection refused" in detail:
                    hint = " — is the server running?"
                elif "timed out" in detail.lower():
                    hint = " — the server took too long to respond"
                detail = f"provider '{provider_name}' failed during orchestration: {detail}{hint}"
            experiment.update_state(ExperimentState.FAILED)
            experiment.error = detail
            store.save(experiment)
            raise JobError(detail) from exc

        # Persist sub-agent findings, plan, and best-run selection.
        if job.cancel_requested:
            experiment.update_state(ExperimentState.CANCELLED)
            experiment.error = "cancelled by user"
            store.save(experiment)
            return result

        previous_job_ids = [
            j for j in experiment.plan.get("previous_job_ids", []) if j
        ]
        old_job_id = experiment.plan.get("job_id")
        if old_job_id and old_job_id != job.job_id and old_job_id not in previous_job_ids:
            previous_job_ids.append(old_job_id)
        experiment.plan = {
            "job_id": job.job_id,
            "previous_job_ids": previous_job_ids,
            "recommendation": result.get("model_selection", {}).get("recommendation", {}),
        }
        experiment.sub_agent_results = {
            "EDAAnalyst": result.get("eda", {}),
            "FeatureEngineer": {
                "cleaned_dataset_id": result.get("feature_engineering", {}).get("cleaned_dataset_id"),
                "clean_metadata": result.get("feature_engineering", {}).get("clean_metadata", {}),
                "top_models": result.get("feature_engineering", {}).get("top_models", []),
            },
            "ModelSelector": result.get("model_selection", {}),
        }
        training_results = result.get("training_results", [])
        completed_runs = sum(1 for r in training_results if r.get("status") == "completed")
        best = next((r for r in training_results if r.get("status") == "completed"), None)
        if best is not None and best.get("run_id"):
            experiment.best_run_id = best["run_id"]
            metrics = load_json_artifact(Path(runs_root), best["run_id"], "metrics.json")
            experiment.best_metrics = metrics or {}
        if result.get("status") == "no_models_found" or (
            training_results and completed_runs == 0
        ):
            # Honest outcome: a batch where every candidate failed is a failed
            # experiment, never a green checkmark (audit BUG 1).
            experiment.update_state(ExperimentState.FAILED)
            experiment.error = (
                "no candidate models completed"
                if not training_results
                else f"all {len(training_results)} candidate training runs failed"
            )
        else:
            experiment.update_state(ExperimentState.COMPLETED)

        # Agentic round (opt-in): runs after the deterministic batch, grounded
        # in its artifacts. Always human-gated (require_approval=True is a
        # binding policy — the round never inherits auto-approval).
        round_record: dict[str, Any] | None = None
        if payload.get("agentic_round") and not job.cancel_requested:
            from thelab.ide.agentic_round import run_agentic_round

            job.emit(
                "info",
                "Starting agentic round (analyst -> sandboxed transform -> selection)",
                {"stage": "agentic_round", "experiment_id": experiment_id},
            )
            try:
                round_record = await run_agentic_round(
                    experiment,
                    result,
                    provider=provider,
                    require_approval=True,
                    on_event=on_event,
                    should_continue=lambda: not job.cancel_requested,
                    runs_root=runs_root,
                    proposals_dir=os.environ.get("THELAB_PROPOSALS_DIR", "proposals"),
                )
            except Exception as exc:  # noqa: BLE001 - round failure never breaks the experiment
                round_record = {"status": "failed", "error": str(exc)}
                job.emit(
                    "warn",
                    f"Agentic round failed (deterministic result stands): {exc}",
                    {"stage": "agentic_round", "experiment_id": experiment_id},
                )
            experiment.plan["agentic_round"] = {
                k: round_record.get(k)
                for k in ("round_id", "status", "proposal_id", "approval_error", "error")
            }
            experiment.sub_agent_results = {
                **experiment.sub_agent_results,
                "AgenticRound": round_record,
            }
            if round_record.get("status") == "awaiting_approval":
                experiment.update_state(ExperimentState.AWAITING_APPROVAL)

        store.save(experiment)
        if round_record is not None:
            result = {**result, "agentic_round": round_record}
        return result


_manager: JobManager | None = None


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _generate_job_id() -> str:
    return f"job-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def get_job_manager() -> JobManager:
    """Return the process-wide job manager."""
    global _manager
    if _manager is None:
        _manager = JobManager(Path(os.environ.get("THELAB_JOBS_DIR", ".thelab/jobs")))
    return _manager


def reset_job_manager() -> None:
    """Reset the process-wide job manager (tests only)."""
    global _manager
    _manager = None
