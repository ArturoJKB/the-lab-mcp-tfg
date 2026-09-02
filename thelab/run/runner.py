from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thelab.contracts import RunStatus, TaskSpec, TaskState, TaskType, ValidationStatus
from thelab.version import dependency_versions
from thelab.workspace import hash_file

from .artifacts import append_event, write_artifacts
from .contract import build_dataset_contract
from .errors import RejectedRunError
from .inputs import RunInputs, TaskTypeArg
from .model_registry import MODEL_REGISTRY
from .preprocess import build_pipeline
from .profile import profile_dataframe, read_csv
from .task_type import infer_task_type
from .train import train_and_evaluate
from .validate import validate_dataset


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _generate_run_id() -> str:
    return f"run-{_utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _relative_output(run_dir: Path, workspace_root: Path) -> str:
    try:
        return str(run_dir.relative_to(workspace_root))
    except ValueError:
        return str(run_dir)


_TASK_STATE_FOR_RUN_STATUS = {
    RunStatus.pending: TaskState.pending,
    RunStatus.running: TaskState.running,
    RunStatus.completed: TaskState.completed,
    RunStatus.rejected: TaskState.rejected,
    RunStatus.failed: TaskState.failed,
}


def _build_task_spec(run_id: str, inputs: RunInputs) -> TaskSpec:
    return TaskSpec(
        task_id=run_id,
        objective=f"Train {inputs.model} on {inputs.dataset.name} to predict {inputs.target}",
        constraints={
            "dataset": str(inputs.dataset),
            "target": inputs.target,
            "model": inputs.model,
            "seed": inputs.seed,
            "output": str(inputs.output),
        },
        responsible_agent="orchestrator",
        task_state=TaskState.pending,
    )


def _relative_if_under(path: Path, root: Path) -> Path:
    """Return a relative path if *path* is under *root*; otherwise return it unchanged."""
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def run_model(
    dataset: Path | str,
    target: str,
    model: str,
    seed: int,
    output: Path | str,
    workspace_root: Path | str | None = None,
    dry_run: bool = False,
    task_type: TaskTypeArg = "auto",
    hyperparameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a direct deterministic Data-to-Model run.

    Returns a dictionary with run_id, run_dir, metrics, and status.

    When *dry_run* is True, the dataset is validated and the model is trained
    in-memory, but no run directory or artifacts are persisted.
    """
    if workspace_root is None:
        workspace_root = Path.cwd()
    workspace_root = Path(workspace_root)
    dataset_path = Path(dataset)
    output_path = Path(output)

    # Programmatic callers may pass absolute paths; normalize them relative to the
    # workspace root so persisted references stay relative.
    dataset_path = _relative_if_under(dataset_path, workspace_root)
    output_path = _relative_if_under(output_path, workspace_root)

    inputs = RunInputs(
        dataset=dataset_path,
        target=target,
        model=model,
        seed=seed,
        output=output_path,
        task_type=task_type,
        workspace_root=workspace_root,
    )

    run_id = _generate_run_id()
    run_dir = inputs.workspace_root / inputs.output / run_id
    if not dry_run:
        run_dir.mkdir(parents=True, exist_ok=True)
    started_at = _utcnow()

    task_spec = _build_task_spec(run_id, inputs)
    task_spec.task_state = TaskState.running
    task_spec.updated_at = _utcnow()

    final_status = RunStatus.running
    validation_status = ValidationStatus.pending
    error_summary: str | None = None

    data_profile: dict[str, Any] = {}
    dataset_contract: dict[str, Any] = {}
    training_config: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    validation_report: dict[str, Any] = {}
    fitted_pipeline: Any | None = None
    split_info: dict[str, int] | None = None
    resolved_task_type: TaskType = "classification"
    dataset_path = inputs.workspace_root / inputs.dataset

    events_path = run_dir / "events.jsonl"
    if not dry_run:
        append_event(events_path, run_id, "run_started", "Run started", {"inputs": inputs.safe_dict()})

    try:
        inputs.validate_dataset_exists()
        df = read_csv(dataset_path)
        feature_columns = [col for col in df.columns if col != inputs.target]

        resolved_task_type = (
            infer_task_type(df, inputs.target)
            if inputs.task_type == "auto"
            else inputs.task_type
        )

        model_entry = MODEL_REGISTRY.get(inputs.model)
        if model_entry.task_type != resolved_task_type:
            raise RejectedRunError(
                f"model '{inputs.model}' is a {model_entry.task_type} model, "
                f"but the dataset resolves to {resolved_task_type}"
            )
        if model_entry.max_train_rows is not None and len(df) > model_entry.max_train_rows:
            raise RejectedRunError(
                f"model '{inputs.model}' is limited to {model_entry.max_train_rows} training rows "
                f"(dataset has {len(df)} rows); choose a scalable model or subsample the data"
            )

        data_profile = profile_dataframe(df, inputs.target)
        validation_report = validate_dataset(
            df,
            dataset_path,
            inputs.target,
            feature_columns,
            inputs.seed,
            task_type=resolved_task_type,
        )

        if not validation_report["valid"]:
            failed = [c for c in validation_report.get("checks", []) if not c.get("passed")]
            reason = failed[0]["message"] if failed else "dataset validation failed"
            raise RejectedRunError(reason)

        if not dry_run:
            append_event(events_path, run_id, "data_validated", "Dataset validated", {"valid": True})

        dataset_fingerprint = hash_file(dataset_path)
        dataset_contract = build_dataset_contract(
            df, dataset_path, inputs.target, feature_columns, dataset_fingerprint
        )

        if not dry_run:
            append_event(events_path, run_id, "validation_completed", "Validation completed", {"valid": True})

        pipeline = build_pipeline(inputs.model, inputs.seed, hyperparameters=hyperparameters)
        fitted_pipeline, metrics, split_info, _, _, _, _ = train_and_evaluate(
            df,
            feature_columns,
            inputs.target,
            pipeline,
            inputs.seed,
            task_type=resolved_task_type,
        )

        # Update split summary with actual counts from train_test_split.
        validation_report["split_summary"]["train_count"] = split_info["train_count"]
        validation_report["split_summary"]["test_count"] = split_info["test_count"]

        training_config = {
            "model": inputs.model,
            "seed": inputs.seed,
            "task_type": resolved_task_type,
            "preprocessing": ["StandardScaler"],
            "split": validation_report["split_summary"],
            "dependency_versions": dependency_versions(),
            "estimator": {
                "class": model_entry.estimator_class.__name__,
                "module": model_entry.estimator_class.__module__,
                "default_params": model_entry.default_params,
                "hyperparameters": hyperparameters,
            },
            "supports_probability": model_entry.supports_probability,
        }

        if not dry_run:
            event_data = (
                {"test_rmse": metrics["test_rmse"]}
                if resolved_task_type == "regression"
                else {"test_accuracy": metrics["test_accuracy"]}
            )
            append_event(
                events_path,
                run_id,
                "training_completed",
                "Training completed",
                event_data,
            )

        final_status = RunStatus.completed
        validation_status = ValidationStatus.approved
    except RejectedRunError as exc:
        final_status = RunStatus.rejected
        validation_status = ValidationStatus.rejected
        error_summary = str(exc)
    except Exception as exc:
        final_status = RunStatus.failed
        validation_status = ValidationStatus.rejected
        error_summary = str(exc)

    # Emit final lifecycle event before closing the run window.
    if not dry_run:
        if final_status == RunStatus.completed:
            append_event(events_path, run_id, "run_completed", "Run completed successfully")
        elif final_status == RunStatus.rejected:
            append_event(events_path, run_id, "run_rejected", "Run rejected", {"error": error_summary})
        else:
            append_event(events_path, run_id, "run_failed", "Run failed", {"error": error_summary})

    finished_at = _utcnow()

    task_spec.task_state = _TASK_STATE_FOR_RUN_STATUS[final_status]
    task_spec.updated_at = finished_at

    manifest: Any = None
    if not dry_run:
        task_spec_path = run_dir / "task_spec.json"
        task_spec_path.write_text(task_spec.model_dump_json(indent=2), encoding="utf-8")

        safe_inputs = inputs.safe_dict()
        safe_inputs["task_type"] = resolved_task_type
        manifest = write_artifacts(
            run_dir=run_dir,
            run_id=run_id,
            inputs=safe_inputs,
            dataset_path=dataset_path,
            data_profile=data_profile,
            dataset_contract=dataset_contract,
            training_config=training_config,
            metrics=metrics,
            validation_report=validation_report,
            fitted_pipeline=fitted_pipeline,
            dependency_versions=dependency_versions(),
            started_at=started_at,
            finished_at=finished_at,
            final_status=final_status,
            validation_status=validation_status,
            error_summary=error_summary,
            task_spec_id=task_spec.task_id,
            task_spec_path=task_spec_path,
            task_type=resolved_task_type,
        )

    if final_status == RunStatus.completed:
        output_label = "not persisted (dry run)" if dry_run else _relative_output(run_dir, inputs.workspace_root)
        # All lifecycle output goes to stderr: stdout is the MCP JSON-RPC
        # transport when the pipeline runs inside a stdio MCP server.
        if resolved_task_type == "regression":
            print(
                f"Run completed: {run_id}\n"
                f"  Output: {output_label}\n"
                f"  Model: {inputs.model}\n"
                f"  Seed: {inputs.seed}\n"
                f"  Task type: {resolved_task_type}\n"
                f"  Test RMSE: {metrics['test_rmse']:.6f}\n"
                f"  Test MAE: {metrics['test_mae']:.6f}\n"
                f"  Test R2: {metrics['test_r2']:.6f}",
                file=sys.stderr,
            )
        else:
            print(
                f"Run completed: {run_id}\n"
                f"  Output: {output_label}\n"
                f"  Model: {inputs.model}\n"
                f"  Seed: {inputs.seed}\n"
                f"  Task type: {resolved_task_type}\n"
                f"  Test accuracy: {metrics['test_accuracy']:.6f}\n"
                f"  Test macro F1: {metrics['test_f1_macro']:.6f}",
                file=sys.stderr,
            )
    elif final_status == RunStatus.rejected:
        print(f"Run rejected: {run_id}\n  Error: {error_summary}", file=sys.stderr)
    else:
        print(f"Run failed: {run_id}\n  Error: {error_summary}", file=sys.stderr)

    return {
        "run_id": run_id,
        "run_dir": run_dir if not dry_run else None,
        "status": final_status.value,
        "model": inputs.model,
        "metrics": metrics,
        "manifest": manifest,
        "error": error_summary,
    }


def try_all_models(
    dataset: Path | str,
    target: str,
    seed: int,
    output: Path | str = "scratch",
    workspace_root: Path | str | None = None,
    dry_run: bool = True,
    task_type: TaskTypeArg = "auto",
    on_result: Callable[[dict[str, Any]], None] | None = None,
    should_continue: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Train every registered model and return a comparison list.

    Results are sorted best-first by ``test_f1_macro`` (tiebreak:
    ``test_accuracy``, then model name). By default this runs in dry-run mode
    so nothing is persisted; set *dry_run* to False and pick an *output*
    directory if you want to keep the runs.

    ``on_result(result)`` fires after each model for progress streaming;
    ``should_continue()`` returning False stops between models (cooperative
    cancellation).
    """
    results = []
    for model_name in MODEL_REGISTRY.list_models():
        if should_continue is not None and not should_continue():
            break
        result = run_model(
            dataset=dataset,
            target=target,
            model=model_name,
            seed=seed,
            output=output,
            workspace_root=workspace_root,
            dry_run=dry_run,
            task_type=task_type,
        )
        results.append(result)
        if on_result is not None:
            on_result(result)
    return sorted(
        results,
        key=lambda r: (
            -float((r.get("metrics") or {}).get("test_f1_macro") or 0.0),
            -float((r.get("metrics") or {}).get("test_accuracy") or 0.0),
            -float((r.get("metrics") or {}).get("test_r2") or 0.0),
            str(r.get("model", "")),
        ),
    )
