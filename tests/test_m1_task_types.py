"""Tests for M1 — task-type generalization (classification + regression)."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import pytest

from thelab.run.model_registry import MODEL_REGISTRY
from thelab.run.runner import run_model, try_all_models
from thelab.run.task_type import infer_task_type


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


@pytest.fixture
def regression_csv(tmp_path: Path) -> Path:
    """Create a small regression CSV fixture."""
    csv = tmp_path / "housing.csv"
    csv.write_text(
        "square_feet,bedrooms,age_years,price\n"
        "1500,3,10,300000\n"
        "1200,2,15,225000\n"
        "1800,4,5,360000\n"
        "900,1,20,150000\n"
        "2100,4,8,420000\n"
        "1600,3,12,310000\n"
        "1100,2,18,198000\n"
        "2400,5,3,480000\n"
        "1300,3,14,247000\n"
        "1700,3,9,340000\n"
        "950,1,22,142500\n"
        "2000,4,7,400000\n"
        "1400,2,16,238000\n"
        "2200,5,6,440000\n"
        "1150,2,19,195000\n"
        "1850,4,4,370000\n"
        "1050,2,21,168000\n"
        "2500,5,2,500000\n"
        "1350,3,13,263500\n"
        "1900,4,6,380000\n"
        "800,1,25,120000\n"
        "1750,3,11,332500\n"
        "1450,3,10,290000\n"
        "2300,4,4,460000\n"
        "1250,2,17,218750\n"
        "1950,4,5,390000\n"
        "1550,3,12,279000\n"
        "850,1,24,127500\n"
        "2050,4,7,410000\n"
        "1650,3,9,330000\n"
        "1000,1,23,150000\n"
        "2150,4,6,430000\n"
        "1280,2,16,224000\n"
        "1780,3,8,356000\n"
        "980,1,21,147000\n"
        "2350,5,3,470000\n"
        "1480,3,11,296000\n"
        "1880,4,5,376000\n"
        "880,1,19,132000\n"
        "2250,4,4,450000\n"
        "1380,3,14,255000\n"
        "1680,3,10,336000\n"
        "920,1,20,138000\n"
        "2450,5,2,490000\n"
        "1580,3,12,303000\n"
        "1980,4,6,396000\n"
        "1080,2,18,189000\n"
        "2120,4,7,424000\n"
        "1420,2,15,248500\n"
        "1820,4,5,364000\n"
    )
    return csv


def test_infer_task_type_non_numeric_target():
    import pandas as pd

    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6], "target": ["x", "y", "x"]})
    assert infer_task_type(df, "target") == "classification"


def test_infer_task_type_numeric_low_cardinality():
    import pandas as pd

    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6], "target": [0, 1, 0]})
    assert infer_task_type(df, "target") == "classification"


def test_infer_task_type_numeric_high_cardinality():
    import pandas as pd

    df = pd.DataFrame({"a": range(30), "b": range(30, 60), "target": range(30)})
    assert infer_task_type(df, "target") == "regression"


def test_regression_run_end_to_end(tmp_path: Path, regression_csv: Path):
    result = run_model(
        dataset=regression_csv,
        target="price",
        model="ridge",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "completed"
    run_dir = result["run_dir"]
    assert run_dir.exists()

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["task_type"] == "regression"

    inputs = json.loads((run_dir / "inputs.json").read_text())
    assert inputs["task_type"] == "regression"

    config = json.loads((run_dir / "training_config.json").read_text())
    assert config["task_type"] == "regression"
    assert config["split"]["stratify"] is False

    metrics = json.loads((run_dir / "metrics.json").read_text())
    assert "test_rmse" in metrics
    assert "test_mae" in metrics
    assert "test_r2" in metrics
    assert "test_accuracy" not in metrics

    model = joblib.load(run_dir / "model.joblib")
    prediction = model.predict([[1500, 3, 10]])
    assert isinstance(prediction[0], (int, float))


def test_regression_run_determinism(tmp_path: Path, regression_csv: Path):
    result1 = run_model(
        dataset=regression_csv,
        target="price",
        model="ridge",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    result2 = run_model(
        dataset=regression_csv,
        target="price",
        model="ridge",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result1["run_id"] != result2["run_id"]
    assert result1["metrics"]["test_rmse"] == pytest.approx(result2["metrics"]["test_rmse"], abs=1e-12)
    assert result1["metrics"]["test_r2"] == pytest.approx(result2["metrics"]["test_r2"], abs=1e-12)


def test_regression_probability_suffix_rejected():
    with pytest.raises(ValueError) as exc_info:
        MODEL_REGISTRY.get("ridge_probability")
    assert "does not support probability" in str(exc_info.value).lower()


def test_classification_model_on_regression_data_rejected(tmp_path: Path, regression_csv: Path):
    result = run_model(
        dataset=regression_csv,
        target="price",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    assert "classification" in result["error"].lower()
    assert "regression" in result["error"].lower()


def test_regression_target_non_numeric_rejected(tmp_path: Path):
    csv = tmp_path / "bad.csv"
    csv.write_text(
        "a,b,target\n"
        "1,2,low\n"
        "3,4,high\n"
        "5,6,medium\n"
        "7,8,low\n"
        "9,10,high\n"
        "11,12,medium\n"
        "13,14,low\n"
        "15,16,high\n"
        "17,18,medium\n"
        "19,20,low\n"
    )
    result = run_model(
        dataset=csv,
        target="target",
        model="ridge",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
        task_type="regression",
    )
    assert result["status"] == "rejected"
    assert "numeric" in result["error"].lower()


def test_regression_target_zero_variance_rejected(tmp_path: Path):
    csv = tmp_path / "constant.csv"
    csv.write_text(
        "a,b,target\n"
        "1,2,5\n"
        "3,4,5\n"
        "5,6,5\n"
        "7,8,5\n"
        "9,10,5\n"
        "11,12,5\n"
        "13,14,5\n"
        "15,16,5\n"
        "17,18,5\n"
        "19,20,5\n"
    )
    result = run_model(
        dataset=csv,
        target="target",
        model="ridge",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
        task_type="regression",
    )
    assert result["status"] == "rejected"
    assert "variance" in result["error"].lower()


@pytest.mark.parametrize("model_name", ["linear_regression", "ridge", "random_forest_regressor", "hist_gradient_boosting_regressor"])
def test_regression_models_train_successfully(tmp_path: Path, regression_csv: Path, model_name: str):
    result = run_model(
        dataset=regression_csv,
        target="price",
        model=model_name,
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "completed"
    config = json.loads((result["run_dir"] / "training_config.json").read_text())
    assert config["model"] == model_name
    assert config["task_type"] == "regression"


def test_try_all_regression_models(tmp_path: Path, regression_csv: Path):
    results = try_all_models(
        dataset=regression_csv,
        target="price",
        seed=42,
        dry_run=True,
        workspace_root=tmp_path,
    )
    completed = [r for r in results if r["status"] == "completed"]
    regression_models = [m for m in MODEL_REGISTRY.list_models() if MODEL_REGISTRY.get(m).task_type == "regression"]
    assert len(completed) == len(regression_models)
    assert all("test_r2" in r["metrics"] for r in completed)


def test_model_registry_task_type_present(tmp_path: Path, regression_csv: Path):
    result = run_model(
        dataset=regression_csv,
        target="price",
        model="ridge",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    run_id = result["run_id"]

    runs_root = tmp_path / "runs"
    manifest = json.loads((runs_root / run_id / "manifest.json").read_text())
    assert manifest["task_type"] == "regression"


def test_compare_grouped_by_task_type(tmp_path: Path, fixture_csv: Path, regression_csv: Path):
    from thelab.run.compare import compare_runs, format_comparison

    run_model(
        dataset=regression_csv,
        target="price",
        model="ridge",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    run_model(
        dataset=fixture_csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )

    runs = compare_runs(tmp_path / "runs")
    assert len(runs) == 2
    text = format_comparison(runs)
    assert "## Classification runs" in text
    assert "## Regression runs" in text
    assert "Test Accuracy" in text
    assert "Test RMSE" in text


def test_explicit_task_type_override(tmp_path: Path, regression_csv: Path):
    result = run_model(
        dataset=regression_csv,
        target="price",
        model="ridge",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
        task_type="regression",
    )
    assert result["status"] == "completed"
    manifest = json.loads((result["run_dir"] / "manifest.json").read_text())
    assert manifest["task_type"] == "regression"
