import json
import subprocess
import sys
from pathlib import Path

import joblib
import pytest

from thelab.run.inputs import RunInputs
from thelab.run.runner import run_model
from thelab.workspace import hash_file

SUCCESS_ARTIFACTS = {
    "manifest.json",
    "events.jsonl",
    "inputs.json",
    "data_profile.json",
    "dataset_contract.json",
    "training_config.json",
    "metrics.json",
    "validation_report.json",
    "model.joblib",
    "model_card.md",
    "task_spec.json",
}

REJECTED_ARTIFACTS = {
    "manifest.json",
    "events.jsonl",
    "inputs.json",
    "data_profile.json",
    "validation_report.json",
    "task_spec.json",
}


@pytest.fixture
def fixture_csv(tmp_path: Path) -> Path:
    """Create a small Iris-like CSV fixture."""
    csv = tmp_path / "iris.csv"
    csv.write_text(
        "sepal_length,sepal_width,petal_length,petal_width,species\n"
        "5.1,3.5,1.4,0.2,setosa\n"
        "4.9,3.0,1.4,0.2,setosa\n"
        "4.7,3.2,1.3,0.2,setosa\n"
        "7.0,3.2,4.7,1.4,versicolor\n"
        "6.4,3.2,4.5,1.5,versicolor\n"
        "6.9,3.1,4.9,1.5,versicolor\n"
        "6.3,3.3,6.0,2.5,virginica\n"
        "5.8,2.7,5.1,1.9,virginica\n"
        "7.1,3.0,5.9,2.1,virginica\n"
        "7.6,3.0,6.6,2.1,virginica\n"
        "4.9,2.5,4.5,1.7,virginica\n"
    )
    return csv


def test_run_success_creates_all_artifacts(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )

    assert result["status"] == "completed"
    run_dir = result["run_dir"]
    assert run_dir.exists()
    assert set(p.name for p in run_dir.iterdir()) == SUCCESS_ARTIFACTS


def test_all_json_artifacts_are_valid_json(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    run_dir = result["run_dir"]

    for name in SUCCESS_ARTIFACTS - {"events.jsonl", "model.joblib", "model_card.md"}:
        path = run_dir / name
        data = json.loads(path.read_text())
        assert isinstance(data, (dict, list))


def test_events_jsonl_contains_lifecycle_events(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    events_path = result["run_dir"] / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().strip().split("\n")]
    assert all(isinstance(e, dict) for e in events)
    event_types = [e["event_type"] for e in events]
    assert "run_started" in event_types
    assert "data_validated" in event_types
    assert "validation_completed" in event_types
    assert "training_completed" in event_types
    assert "run_completed" in event_types


def test_event_timestamps_are_chronological(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    manifest = json.loads((result["run_dir"] / "manifest.json").read_text())
    started = manifest["started_at"]
    finished = manifest["finished_at"]

    events_path = result["run_dir"] / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().strip().split("\n")]
    timestamps = [e["timestamp"] for e in events]
    assert all(started <= ts <= finished for ts in timestamps), f"event outside run window: {timestamps}"

    # Events should be in chronological order.
    assert timestamps == sorted(timestamps)


def test_model_joblib_loads_and_predicts(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    model_path = result["run_dir"] / "model.joblib"
    model = joblib.load(model_path)
    prediction = model.predict([[5.0, 3.4, 1.5, 0.2]])
    assert prediction[0] in {"setosa", "versicolor", "virginica"}


def test_manifest_records_seed_model_and_fingerprint(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    manifest = json.loads((result["run_dir"] / "manifest.json").read_text())
    assert manifest["random_seed"] == 42
    assert manifest["training_config"]["model"] == "logistic_regression"
    assert manifest["input_hash"] is not None
    assert len(manifest["input_hash"]) == 64
    assert manifest["final_status"] == "completed"
    assert manifest["validation_status"] == "approved"


def test_task_spec_is_created_and_linked_in_manifest(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    run_dir = result["run_dir"]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    task_spec = json.loads((run_dir / "task_spec.json").read_text())

    assert manifest["task_spec_id"] == result["run_id"]
    assert task_spec["task_id"] == result["run_id"]
    assert task_spec["objective"] == "Train logistic_regression on iris.csv to predict species"
    assert task_spec["responsible_agent"] == "orchestrator"
    assert task_spec["task_state"] == "completed"
    assert task_spec["constraints"]["seed"] == 42


def test_rejected_run_task_spec_reflects_rejected_state(tmp_path: Path):
    result = run_model(
        dataset=tmp_path / "does_not_exist.csv",
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    task_spec = json.loads((result["run_dir"] / "task_spec.json").read_text())
    assert task_spec["task_state"] == "rejected"
    assert task_spec["updated_at"] >= task_spec["created_at"]


def test_manifest_references_all_produced_artifacts(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    run_dir = result["run_dir"]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    produced = {p.name for p in run_dir.iterdir()}
    referenced = {str(ref["relative_path"]) for ref in manifest["artifact_refs"]}

    # manifest.json is not referenced inside itself; everything else should be.
    assert produced - referenced == {"manifest.json"}
    assert "events.jsonl" in referenced
    assert "inputs.json" in referenced
    assert "data_profile.json" in referenced
    assert "dataset_contract.json" in referenced
    assert "training_config.json" in referenced
    assert "metrics.json" in referenced
    assert "validation_report.json" in referenced
    assert "model.joblib" in referenced
    assert "model_card.md" in referenced
    assert "manifest.json" not in referenced


def test_reproducible_metrics_within_tolerance(tmp_path: Path, fixture_csv: Path):
    result1 = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    result2 = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )

    assert result1["run_id"] != result2["run_id"]
    for key in ("test_accuracy", "test_f1_macro", "train_accuracy", "train_f1_macro"):
        assert result1["metrics"][key] == pytest.approx(result2["metrics"][key], abs=1e-12)


def test_rejected_missing_dataset_has_no_model_artifacts(tmp_path: Path):
    result = run_model(
        dataset=tmp_path / "does_not_exist.csv",
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    assert "not found" in result["error"].lower()

    run_dir = result["run_dir"]
    assert set(p.name for p in run_dir.iterdir()) == REJECTED_ARTIFACTS
    assert not (run_dir / "model.joblib").exists()
    assert not (run_dir / "model_card.md").exists()


def test_rejected_missing_target_has_no_training_completed_event(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="missing_column",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    assert "missing_column" in result["error"]

    events_path = result["run_dir"] / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().strip().split("\n")]
    event_types = [e["event_type"] for e in events]
    assert "training_completed" not in event_types
    assert "run_rejected" in event_types


def test_unsupported_model_fails_clearly(tmp_path: Path, fixture_csv: Path):
    with pytest.raises(ValueError) as exc_info:
        run_model(
            dataset=fixture_csv,
            target="species",
            model="neural_network",
            seed=42,
            output="runs",
            workspace_root=tmp_path,
        )
    assert "unsupported" in str(exc_info.value).lower()
    assert "logistic_regression" in str(exc_info.value)


def test_absolute_dataset_path_is_rejected(tmp_path: Path, fixture_csv: Path):
    with pytest.raises(ValueError) as exc_info:
        RunInputs(
            dataset=fixture_csv,
            target="species",
            model="logistic_regression",
            seed=42,
            output="runs",
            workspace_root=tmp_path,
        )
    assert "relative path" in str(exc_info.value).lower()


def test_parent_traversal_in_dataset_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError) as exc_info:
        RunInputs(
            dataset=Path("..") / "iris.csv",
            target="species",
            model="logistic_regression",
            seed=42,
            output="runs",
            workspace_root=tmp_path,
        )
    assert "'..'" in str(exc_info.value)


def test_parent_traversal_in_output_is_rejected(tmp_path: Path, fixture_csv: Path):
    with pytest.raises(ValueError) as exc_info:
        RunInputs(
            dataset=Path("iris.csv"),
            target="species",
            model="logistic_regression",
            seed=42,
            output=Path("..") / "runs",
            workspace_root=tmp_path,
        )
    assert "'..'" in str(exc_info.value)


def test_duplicate_reporting_exists(tmp_path: Path, fixture_csv: Path):
    # Append a duplicate row to the fixture.
    text = fixture_csv.read_text()
    fixture_csv.write_text(text + text.split("\n")[1] + "\n")

    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    profile = json.loads((result["run_dir"] / "data_profile.json").read_text())
    assert "duplicate_row_count" in profile
    assert "duplicate_rate" in profile
    assert profile["duplicate_row_count"] == 1
    assert profile["duplicate_rate"] > 0


def test_missing_feature_values_are_rejected(tmp_path: Path):
    csv = tmp_path / "missing_features.csv"
    csv.write_text(
        "sepal_length,sepal_width,petal_length,petal_width,species\n"
        "5.1,3.5,,0.2,setosa\n"
        "4.9,3.0,1.4,0.2,setosa\n"
        "7.0,3.2,4.7,1.4,versicolor\n"
        "6.3,3.3,6.0,2.5,virginica\n"
    )
    result = run_model(
        dataset=csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    assert "missing" in result["error"].lower()
    assert not (result["run_dir"] / "model.joblib").exists()


def test_small_split_counts_match_metrics(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    metrics = json.loads((result["run_dir"] / "metrics.json").read_text())
    validation = json.loads((result["run_dir"] / "validation_report.json").read_text())
    config = json.loads((result["run_dir"] / "training_config.json").read_text())

    assert validation["split_summary"]["train_count"] == metrics["train_samples"]
    assert validation["split_summary"]["test_count"] == metrics["test_samples"]
    assert config["split"]["train_count"] == metrics["train_samples"]
    assert config["split"]["test_count"] == metrics["test_samples"]


def test_cli_success_and_invalid_exit_code(tmp_path: Path, fixture_csv: Path):
    # Successful run via installed CLI script. The CLI requires relative paths,
    # so execute from the workspace root where the fixture lives.
    success = subprocess.run(
        [
            sys.executable, "-m", "thelab.cli",
            "run", "model",
            "--dataset", "iris.csv",
            "--target", "species",
            "--model", "logistic_regression",
            "--seed", "42",
            "--output", "runs",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert success.returncode == 0
    assert "Run completed" in success.stdout

    # Invalid model should exit non-zero.
    invalid = subprocess.run(
        [
            sys.executable, "-m", "thelab.cli",
            "run", "model",
            "--dataset", "iris.csv",
            "--target", "species",
            "--model", "neural_network",
            "--seed", "42",
            "--output", "runs",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert invalid.returncode == 1
    assert "unsupported" in (invalid.stdout + invalid.stderr).lower()


def _assert_artifact_hashes_match(run_dir: Path) -> None:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    for ref in manifest["artifact_refs"]:
        rel_path = str(ref["relative_path"])
        artifact_path = run_dir / rel_path
        expected = ref["content_hash"]
        actual = hash_file(artifact_path)
        assert actual == expected, f"hash mismatch for {rel_path}: expected {expected}, got {actual}"


def test_artifact_hashes_match_persisted_bytes_completed(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "completed"
    _assert_artifact_hashes_match(result["run_dir"])


def test_artifact_hashes_match_persisted_bytes_rejected(tmp_path: Path):
    result = run_model(
        dataset=tmp_path / "does_not_exist.csv",
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    _assert_artifact_hashes_match(result["run_dir"])


def test_stratified_split_rejects_6_rows_3_classes_2_each(tmp_path: Path):
    csv = tmp_path / "tiny_stratify.csv"
    csv.write_text(
        "a,b,label\n"
        "1,1,alpha\n"
        "2,2,alpha\n"
        "3,3,beta\n"
        "4,4,beta\n"
        "5,5,gamma\n"
        "6,6,gamma\n"
    )
    result = run_model(
        dataset=csv,
        target="label",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    assert result["manifest"].final_status.value == "rejected"
    assert result["manifest"].validation_status.value == "rejected"
    assert "cannot stratify" in result["error"].lower()

    run_dir = result["run_dir"]
    assert not (run_dir / "model.joblib").exists()
    assert not (run_dir / "model_card.md").exists()

    events_path = run_dir / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().strip().split("\n")]
    event_types = [e["event_type"] for e in events]
    assert "training_completed" not in event_types
    assert "run_rejected" in event_types


@pytest.mark.parametrize("model_name", ["random_forest", "svc", "sgd_classifier"])
def test_additional_models_train_successfully(tmp_path: Path, fixture_csv: Path, model_name: str):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model=model_name,
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "completed"
    config = json.loads((result["run_dir"] / "training_config.json").read_text())
    assert config["model"] == model_name
    assert config["estimator"]["class"] == {
        "random_forest": "RandomForestClassifier",
        "svc": "SVC",
        "sgd_classifier": "SGDClassifier",
    }[model_name]


@pytest.mark.parametrize("model_name", ["logistic_regression_probability", "random_forest_probability", "svc_probability", "sgd_classifier_probability"])
def test_probability_variant_enables_predict_proba(tmp_path: Path, fixture_csv: Path, model_name: str):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model=model_name,
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "completed"
    model = joblib.load(result["run_dir"] / "model.joblib")
    proba = model.predict_proba([[5.0, 3.4, 1.5, 0.2]])
    assert proba.shape[1] == 3


def test_non_probability_svc_rejects_predict_proba(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="svc",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "completed"
    model = joblib.load(result["run_dir"] / "model.joblib")
    with pytest.raises(ValueError) as exc_info:
        model.predict_proba([[5.0, 3.4, 1.5, 0.2]])
    assert "does not support probability" in str(exc_info.value).lower()
