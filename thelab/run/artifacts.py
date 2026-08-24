from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from thelab.contracts import ArtifactRef, RunManifest, RunStatus, TaskType, ValidationStatus
from thelab.workspace import hash_bytes, hash_file


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def append_event(events_path: Path, run_id: str, event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
    event: dict[str, Any] = {
        "event_type": event_type,
        "run_id": run_id,
        "timestamp": now_iso(),
        "message": message,
    }
    if data:
        event["data"] = data
    with open(events_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")


def artifact_ref(run_id: str, artifact_type: str, relative_path: Path, content_hash: str, origin: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=f"{run_id}-{artifact_type}",
        artifact_type=artifact_type,
        relative_path=relative_path,
        content_hash=content_hash,
        origin=origin,
        parent_run_id=run_id,
    )


def build_manifest(
    run_id: str,
    inputs: dict[str, Any],
    dataset_path: Path,
    training_config: dict[str, Any],
    seed: int,
    dependency_versions: dict[str, str],
    artifact_refs: list[ArtifactRef],
    final_status: RunStatus,
    validation_status: ValidationStatus,
    error_summary: str | None,
    started_at: datetime,
    finished_at: datetime,
    task_spec_id: str | None = None,
    task_type: TaskType | None = None,
) -> RunManifest:
    try:
        dataset_hash = hash_file(dataset_path)
    except FileNotFoundError:
        dataset_hash = ""

    return RunManifest(
        run_id=run_id,
        input_hash=dataset_hash,
        training_config=training_config if training_config else {"model": inputs["model"], "seed": seed},
        random_seed=seed,
        dependency_versions=dependency_versions,
        started_at=started_at,
        finished_at=finished_at,
        final_status=final_status,
        validation_status=validation_status,
        artifact_refs=artifact_refs,
        error_summary=error_summary,
        task_spec_id=task_spec_id,
        task_type=task_type,
    )


def write_model_card(
    path: Path,
    run_id: str,
    inputs: dict[str, Any],
    training_config: dict[str, Any],
    data_profile: dict[str, Any],
    metrics: dict[str, Any],
    validation_report: dict[str, Any],
) -> None:
    def _fmt(key: str) -> str:
        return f"{metrics[key]:.6f}" if key in metrics else "N/A"

    preprocessing = training_config.get("preprocessing", ["StandardScaler"])
    limitations = training_config.get(
        "limitations",
        [
            "Supports only numeric features.",
            "No hyperparameter search, AutoML, or feature engineering.",
        ],
    )
    task_type = training_config.get("task_type", "classification")
    purpose = (
        "Trained regression model produced by The Lab direct run."
        if task_type == "regression"
        else "Trained classification model produced by The Lab direct run."
    )
    split_desc = "80/20 stratified" if task_type == "classification" else "80/20 shuffle"

    lines = [
        "# Model Card",
        "",
        "## Purpose",
        purpose,
        "",
        "## Dataset summary",
        f"- Source: `{inputs['dataset']}`",
        f"- Rows: {data_profile.get('row_count', 'N/A')}",
        f"- Columns: {data_profile.get('column_count', 'N/A')}",
        f"- Target: `{inputs['target']}`",
        "",
        "## Target",
        f"`{inputs['target']}`",
        "",
        "## Model and preprocessing",
        f"- Model: `{inputs['model']}`",
        f"- Task type: {task_type}",
        f"- Preprocessing: {', '.join(preprocessing)}",
        f"- Seed: {inputs['seed']}",
        "",
        "## Validation procedure",
        f"- Train/test split: {split_desc}",
        f"- Seed: {inputs['seed']}",
        f"- Valid: {validation_report.get('valid', 'N/A')}",
        "",
        "## Metrics",
    ]
    if task_type == "regression":
        lines.extend([
            f"- Test RMSE: {_fmt('test_rmse')}",
            f"- Test MAE: {_fmt('test_mae')}",
            f"- Test R2: {_fmt('test_r2')}",
        ])
    else:
        lines.extend([
            f"- Test accuracy: {_fmt('test_accuracy')}",
            f"- Test macro F1: {_fmt('test_f1_macro')}",
        ])
    lines.extend([
        f"- Train samples: {metrics.get('train_samples', 'N/A')}",
        f"- Test samples: {metrics.get('test_samples', 'N/A')}",
        "",
        "## Reproducibility command",
        f"```bash\nthelab run model --dataset {inputs['dataset']} --target {inputs['target']} --model {inputs['model']} --seed {inputs['seed']} --output {inputs['output']}\n```",
        "",
        "## Limitations",
    ])
    for limitation in limitations:
        lines.append(f"- {limitation}")
    lines.extend([
        "",
        "## Artifact references",
        "- `manifest.json`",
        "- `events.jsonl`",
        "- `inputs.json`",
        "- `data_profile.json`",
        "- `dataset_contract.json`",
        "- `training_config.json`",
        "- `metrics.json`",
        "- `validation_report.json`",
        "- `model.joblib`",
        "- `model_card.md`",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_artifacts(
    run_dir: Path,
    run_id: str,
    inputs: dict[str, Any],
    dataset_path: Path,
    data_profile: dict[str, Any],
    dataset_contract: dict[str, Any],
    training_config: dict[str, Any],
    metrics: dict[str, Any],
    validation_report: dict[str, Any],
    fitted_pipeline: Any,
    dependency_versions: dict[str, str],
    started_at: datetime,
    finished_at: datetime,
    final_status: RunStatus,
    validation_status: ValidationStatus,
    error_summary: str | None,
    task_spec_id: str | None = None,
    task_spec_path: Path | None = None,
    task_type: TaskType | None = None,
) -> RunManifest:
    run_dir.mkdir(parents=True, exist_ok=True)

    events_path = run_dir / "events.jsonl"
    refs: list[ArtifactRef] = []

    # task_spec.json is written by the runner; reference it in the manifest.
    if task_spec_path is not None and task_spec_path.is_file():
        refs.append(artifact_ref(run_id, "task_spec", Path("task_spec.json"), hash_file(task_spec_path), "orchestrator"))

    # inputs.json
    inputs_path = run_dir / "inputs.json"
    write_json(inputs_path, inputs)
    refs.append(artifact_ref(run_id, "inputs", Path("inputs.json"), hash_file(inputs_path), "cli"))

    # data_profile.json
    profile_path = run_dir / "data_profile.json"
    write_json(profile_path, data_profile)
    refs.append(artifact_ref(run_id, "data_profile", Path("data_profile.json"), hash_file(profile_path), "profiler"))

    # dataset_contract.json (only if validation produced a contract)
    if dataset_contract:
        contract_path = run_dir / "dataset_contract.json"
        write_json(contract_path, dataset_contract)
        refs.append(artifact_ref(run_id, "dataset_contract", Path("dataset_contract.json"), hash_file(contract_path), "validator"))

    # training_config.json, metrics.json, model.joblib, model_card.md only for completed runs
    if final_status == RunStatus.completed:
        config_path = run_dir / "training_config.json"
        write_json(config_path, training_config)
        refs.append(artifact_ref(run_id, "training_config", Path("training_config.json"), hash_file(config_path), "trainer"))

        metrics_path = run_dir / "metrics.json"
        write_json(metrics_path, metrics)
        refs.append(artifact_ref(run_id, "metrics", Path("metrics.json"), hash_file(metrics_path), "evaluator"))

        report_path = run_dir / "validation_report.json"
        write_json(report_path, validation_report)
        refs.append(artifact_ref(run_id, "validation_report", Path("validation_report.json"), hash_file(report_path), "validator"))

        model_path = run_dir / "model.joblib"
        joblib.dump(fitted_pipeline, model_path)
        refs.append(artifact_ref(run_id, "model", Path("model.joblib"), hash_bytes(model_path.read_bytes()), "trainer"))

        card_path = run_dir / "model_card.md"
        write_model_card(card_path, run_id, inputs, training_config, data_profile, metrics, validation_report)
        refs.append(artifact_ref(run_id, "model_card", Path("model_card.md"), hash_bytes(card_path.read_bytes()), "trainer"))
    else:
        # validation_report.json is still produced for rejected/failed runs
        report_path = run_dir / "validation_report.json"
        write_json(report_path, validation_report)
        refs.append(artifact_ref(run_id, "validation_report", Path("validation_report.json"), hash_file(report_path), "validator"))

    # events.jsonl reference (written incrementally by runner)
    refs.append(artifact_ref(run_id, "events", Path("events.jsonl"), hash_bytes(events_path.read_bytes()), "runner"))

    # manifest.json
    manifest = build_manifest(
        run_id=run_id,
        inputs=inputs,
        dataset_path=dataset_path,
        training_config=training_config,
        seed=inputs["seed"],
        dependency_versions=dependency_versions,
        artifact_refs=refs,
        final_status=final_status,
        validation_status=validation_status,
        error_summary=error_summary,
        started_at=started_at,
        finished_at=finished_at,
        task_spec_id=task_spec_id,
        task_type=task_type,
    )
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    # Note: manifest.json is intentionally not included in artifact_refs because a
    # self-reference would create a circular content hash (the reference is part of
    # the manifest content). events.jsonl captures the full lifecycle.

    return manifest
