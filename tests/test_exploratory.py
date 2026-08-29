"""Tests for exploratory features: inspect, dry-run, try-all, predict, compare, quick API."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from thelab.quick import compare, experiment, list_models
from thelab.run.compare import compare_runs, format_comparison
from thelab.run.inspect import format_inspect, inspect_dataset
from thelab.run.prediction import predict
from thelab.run.runner import run_model, try_all_models


@pytest.fixture
def fixture_csv(tmp_path: Path) -> Path:
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


def test_inspect_dataset(tmp_path: Path, fixture_csv: Path):
    result = inspect_dataset(fixture_csv, target_column="species")
    assert result["target"] == "species"
    assert "species" not in result["features"]
    assert result["profile"]["row_count"] == 11
    assert any(c["check"] == "dataset_not_empty" and c["passed"] for c in result["checks"])


def test_format_inspect(tmp_path: Path, fixture_csv: Path):
    text = format_inspect(inspect_dataset(fixture_csv, target_column="species"))
    assert "Dataset:" in text
    assert "Rows:" in text
    assert "sepal_length" in text


def test_dry_run_does_not_create_run_dir(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
        dry_run=True,
    )
    assert result["status"] == "completed"
    assert result["metrics"]["test_accuracy"] > 0
    assert result["run_dir"] is None
    assert not (tmp_path / "runs").exists()


def test_try_all_models_returns_all_compatible_models(tmp_path: Path, fixture_csv: Path):
    results = try_all_models(
        dataset="iris.csv",
        target="species",
        seed=42,
        dry_run=True,
        workspace_root=tmp_path,
    )
    completed = [r for r in results if r["status"] == "completed"]
    assert len(completed) == len([m for m in list_models() if not m.endswith("_regressor") and m not in {"linear_regression", "ridge"}])
    assert all("test_accuracy" in r["metrics"] for r in completed)


def test_try_all_models_sorted_best_first(tmp_path: Path, fixture_csv: Path):
    results = try_all_models(
        dataset="iris.csv",
        target="species",
        seed=42,
        dry_run=True,
        workspace_root=tmp_path,
    )
    completed = [r for r in results if r["status"] == "completed"]
    f1_scores = [r["metrics"]["test_f1_macro"] for r in completed]
    assert f1_scores == sorted(f1_scores, reverse=True)


def test_predict_from_run(tmp_path: Path, fixture_csv: Path):
    result = run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    run_id = result["run_id"]

    prediction = predict(run_id, [[5.0, 3.4, 1.5, 0.2]], workspace_root=tmp_path)
    assert prediction["run_id"] == run_id
    assert len(prediction["predictions"]) == 1
    assert prediction["predictions"][0] in {"setosa", "versicolor", "virginica"}


def test_compare_runs(tmp_path: Path, fixture_csv: Path):
    run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    run_model(
        dataset=fixture_csv,
        target="species",
        model="random_forest",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )

    runs = compare_runs(tmp_path / "runs")
    assert len(runs) == 2
    text = format_comparison(runs)
    assert "logistic_regression" in text
    assert "random_forest" in text


def test_quick_experiment(tmp_path: Path, fixture_csv: Path):
    exp = experiment(
        dataset="iris.csv",
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert exp.status == "completed"
    assert exp.metrics["test_accuracy"] > 0
    prediction = exp.predict([5.0, 3.4, 1.5, 0.2])
    assert prediction[0] in {"setosa", "versicolor", "virginica"}


def test_quick_compare(tmp_path: Path, fixture_csv: Path):
    experiments = compare(
        dataset="iris.csv",
        target="species",
        seed=42,
        workspace_root=tmp_path,
    )
    completed = [e for e in experiments if e.status == "completed"]
    expected = len([m for m in list_models() if not m.endswith("_regressor") and m not in {"linear_regression", "ridge"}])
    assert len(completed) == expected
    assert all(e.status == "completed" for e in completed)


def test_cli_inspect(tmp_path: Path, fixture_csv: Path):
    result = subprocess.run(
        [
            sys.executable, "-m", "thelab.cli",
            "inspect",
            "--dataset", str(fixture_csv.relative_to(tmp_path)),
            "--target", "species",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert "Rows:" in result.stdout


def test_cli_dry_run(tmp_path: Path, fixture_csv: Path):
    result = subprocess.run(
        [
            sys.executable, "-m", "thelab.cli",
            "run", "model",
            "--dataset", str(fixture_csv.relative_to(tmp_path)),
            "--target", "species",
            "--model", "logistic_regression",
            "--seed", "42",
            "--output", "runs",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert "Test accuracy" in result.stderr
    assert not (tmp_path / "runs").exists()


def test_cli_try_all(tmp_path: Path, fixture_csv: Path):
    result = subprocess.run(
        [
            sys.executable, "-m", "thelab.cli",
            "run", "model",
            "--dataset", str(fixture_csv.relative_to(tmp_path)),
            "--target", "species",
            "--model", "logistic_regression",
            "--seed", "42",
            "--output", "scratch",
            "--try-all",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert "Trained" in result.stdout
    assert "logistic_regression" in result.stdout


def test_cli_predict_and_compare(tmp_path: Path, fixture_csv: Path):
    run = subprocess.run(
        [
            sys.executable, "-m", "thelab.cli",
            "run", "model",
            "--dataset", str(fixture_csv.relative_to(tmp_path)),
            "--target", "species",
            "--model", "logistic_regression",
            "--seed", "42",
            "--output", "runs",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert run.returncode == 0, run.stderr
    run_id = run.stderr.splitlines()[0].replace("Run completed: ", "").strip()

    predict_result = subprocess.run(
        [
            sys.executable, "-m", "thelab.cli",
            "predict",
            "--run-id", run_id,
            "--features", "5.1,3.5,1.4,0.2",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert predict_result.returncode == 0, predict_result.stderr
    assert "Prediction:" in predict_result.stdout

    json_predict = subprocess.run(
        [
            sys.executable, "-m", "thelab.cli",
            "predict",
            "--run-id", run_id,
            "--features", "5.1,3.5,1.4,0.2",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert json_predict.returncode == 0
    payload = json.loads(json_predict.stdout)
    assert payload["run_id"] == run_id
    assert isinstance(payload["predictions"], list)

    compare_result = subprocess.run(
        [
            sys.executable, "-m", "thelab.cli",
            "compare",
            "--output", "runs",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert compare_result.returncode == 0
    assert run_id in compare_result.stdout
