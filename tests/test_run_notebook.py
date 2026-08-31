"""Tests for generated run notebooks (P3.6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thelab.run.notebook import generate_run_notebook
from thelab.run.runner import run_model


def _completed_run(tmp_path: Path, target: str = "species", model: str = "logistic_regression") -> str:
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
    result = run_model(
        dataset=csv,
        target=target,
        model=model,
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "completed"
    return result["run_id"]


def _regression_csv(tmp_path: Path) -> Path:
    csv = tmp_path / "housing.csv"
    rows = ["a,b,target"]
    for i in range(30):
        rows.append(f"{i},{i % 7},{i * 0.5 + (i % 3)}")
    csv.write_text("\n".join(rows), encoding="utf-8")
    return csv


def test_notebook_from_completed_classification_run(tmp_path: Path):
    run_id = _completed_run(tmp_path)
    nb = generate_run_notebook(run_id, runs_root=tmp_path / "runs")

    assert nb["nbformat"] == 4
    assert len(nb["cells"]) == 6
    json.dumps(nb)  # JSON-serializable

    summary = "".join(nb["cells"][0]["source"])
    assert "logistic_regression" in summary
    assert "42" in summary
    assert "completed" in summary

    reproduce = "".join(nb["cells"][2]["source"])
    assert "logistic_regression" in reproduce
    assert "seed=42" in reproduce
    assert "run_model(" in reproduce
    # The recorded relative dataset path is used, not the temp dir.
    assert "iris.csv" in reproduce
    assert str(tmp_path) not in reproduce


def test_notebook_from_regression_run(tmp_path: Path):
    csv = _regression_csv(tmp_path)
    result = run_model(
        dataset=csv,
        target="target",
        model="linear_regression",
        seed=7,
        output="runs",
        workspace_root=tmp_path,
        task_type="regression",
    )
    assert result["status"] == "completed"
    nb = generate_run_notebook(result["run_id"], runs_root=tmp_path / "runs")

    reproduce = "".join(nb["cells"][2]["source"])
    assert "linear_regression" in reproduce
    assert "seed=7" in reproduce
    assert "regression" in reproduce
    json.dumps(nb)


def test_notebook_missing_run(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        generate_run_notebook("run-does-not-exist", runs_root=tmp_path)


def test_notebook_from_rejected_run(tmp_path: Path):
    csv = tmp_path / "bad.csv"
    csv.write_text(
        "sepal_length,sepal_width,species\n"
        "5.1,3.5,setosa\n"
        "4.9,3.0,setosa\n"
    )
    result = run_model(
        dataset=csv,
        target="missing",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    nb = generate_run_notebook(result["run_id"], runs_root=tmp_path / "runs")

    assert nb["metadata"]["thelab"]["final_status"] == "rejected"
    findings = "".join(nb["cells"][5]["source"])
    assert "Rejected" in findings
    json.dumps(nb)


def test_notebook_endpoint(tmp_path: Path, monkeypatch):

    from thelab.model_service.app import app

    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))
    run_id = _completed_run(tmp_path)

    client = TestClient(app)
    response = client.get(f"/runs/{run_id}/notebook")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["nbformat"] == 4
    assert any("run_model(" in "".join(c["source"]) for c in data["cells"] if c["cell_type"] == "code")

    missing = client.get("/runs/run-unknown/notebook")
    assert missing.status_code == 404
