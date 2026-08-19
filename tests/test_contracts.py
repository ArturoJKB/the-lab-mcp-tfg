from pathlib import Path

import pytest
from pydantic import ValidationError

from thelab.contracts import (
    ArtifactRef,
    DatasetSpec,
    LogEntry,
    ModelSpec,
    RunManifest,
    TaskSpec,
)
from thelab.contracts.log_entry import EventType


def test_task_spec_defaults():
    spec = TaskSpec(objective="train a model")
    assert spec.task_state.value == "pending"
    assert spec.responsible_agent == "orchestrator"
    assert isinstance(spec.task_id, str)
    assert spec.created_at <= spec.updated_at


def test_run_manifest():
    manifest = RunManifest(
        run_id="run-001",
        input_hash="abc123",
        random_seed=42,
        dependency_versions={"python": "3.11", "thelab": "0.1.0"},
    )
    assert manifest.final_status.value == "pending"
    assert manifest.validation_status.value == "pending"
    assert manifest.error_summary is None


def test_artifact_ref_rejects_absolute_path():
    with pytest.raises(ValidationError):
        ArtifactRef(
            artifact_id="a1",
            artifact_type="dataset",
            relative_path=Path("/etc/passwd"),
            content_hash="hash",
            origin="user",
            parent_run_id="run-001",
        )


def test_artifact_ref_rejects_parent_traversal():
    with pytest.raises(ValidationError):
        ArtifactRef(
            artifact_id="a1",
            artifact_type="dataset",
            relative_path=Path("../secret.txt"),
            content_hash="hash",
            origin="user",
            parent_run_id="run-001",
        )
    with pytest.raises(ValidationError):
        ArtifactRef(
            artifact_id="a1",
            artifact_type="dataset",
            relative_path=Path("foo/../bar.txt"),
            content_hash="hash",
            origin="user",
            parent_run_id="run-001",
        )


def test_dataset_spec():
    spec = DatasetSpec(
        source="data/fixtures/iris.csv",
        target_column="species",
        train_test_split={"test_size": 0.2, "random_state": 42},
    )
    assert spec.target_column == "species"
    assert spec.privacy_classification == "internal"


def test_model_spec():
    spec = ModelSpec(
        algorithm="logistic_regression",
        hyperparameters={"C": 1.0},
        target_metric="f1_macro",
        random_seed=123,
    )
    assert spec.algorithm == "logistic_regression"
    assert spec.random_seed == 123


def test_log_entry():
    entry = LogEntry(
        event_type=EventType.pipeline,
        session_id="session-1",
        tags=["training"],
        redacted_summary="started training",
    )
    assert entry.privacy_level.value == "internal"
    assert entry.related_artifact_refs == []


def test_manifest_json_roundtrip():
    manifest = RunManifest(
        run_id="run-002",
        input_hash="def456",
        random_seed=7,
        artifact_refs=[
            ArtifactRef(
                artifact_id="m1",
                artifact_type="model",
                relative_path=Path("model.joblib"),
                content_hash="hash1",
                origin="trainer",
                parent_run_id="run-002",
            )
        ],
    )
    data = manifest.model_dump_json()
    restored = RunManifest.model_validate_json(data)
    assert restored.artifact_refs[0].artifact_id == "m1"
