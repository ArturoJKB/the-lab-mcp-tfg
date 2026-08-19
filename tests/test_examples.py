"""Tests that shipped example datasets and batch configs are usable."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from thelab.run.batch import BatchRunner
from thelab.run.runner import run_model

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


def _copy_examples(tmp_path: Path) -> Path:
    """Copy shipped example CSVs into the temp workspace keeping the examples/ prefix."""
    dest = tmp_path / "examples"
    dest.mkdir()
    for csv in EXAMPLES_DIR.glob("*.csv"):
        shutil.copy(csv, dest / csv.name)
    return dest


@pytest.mark.parametrize(
    "dataset,target,model",
    [
        ("iris.csv", "species", "logistic_regression"),
        ("iris.csv", "species", "random_forest"),
        ("wine.csv", "class", "logistic_regression"),
        ("wine.csv", "class", "random_forest"),
        ("breast_cancer.csv", "target", "logistic_regression"),
        ("breast_cancer.csv", "target", "sgd_classifier"),
    ],
)
def test_example_datasets_train(tmp_path: Path, dataset: str, target: str, model: str):
    _copy_examples(tmp_path)
    result = run_model(
        dataset=f"examples/{dataset}",
        target=target,
        model=model,
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "completed"
    assert result["metrics"]["test_accuracy"] > 0


@pytest.mark.parametrize(
    "config_file",
    [
        "iris-batch.json",
        "wine-batch.json",
        "breast-cancer-batch.json",
        "multi-dataset-batch.json",
    ],
)
def test_example_batch_configs_run(tmp_path: Path, config_file: str):
    _copy_examples(tmp_path)
    config_path = EXAMPLES_DIR / config_file
    runner = BatchRunner(workspace_root=tmp_path)
    entries = runner.load_config(config_path)
    results = runner.run(entries, output="runs")

    assert len(results) == len(entries)
    assert all(r.status == "completed" for r in results)

    summary_path = tmp_path / "runs" / "batch_summary.json"
    runner.write_summary(results, summary_path)
    summary = json.loads(summary_path.read_text())
    assert summary["completed"] == len(entries)
