"""Tests for Phase 5 dataset preview and run comparison endpoints."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thelab.model_service.app import app
from thelab.run.runner import run_model


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def viewer_dirs(tmp_path: Path, monkeypatch):
    uploads = tmp_path / "uploads"
    fixtures = tmp_path / "fixtures"
    runs = tmp_path / "runs"
    for d in (uploads, fixtures, runs):
        d.mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_FIXTURES_DIR", str(fixtures))
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(runs))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    return uploads, fixtures, runs


def test_preview_returns_rows_and_columns(client: TestClient, viewer_dirs):
    uploads, _, _ = viewer_dirs
    (uploads / "data.csv").write_text("a,b\n1,x\n2,y\n3,z\n", encoding="utf-8")

    response = client.get("/datasets/uploads%2Fdata.csv/preview")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["dataset_id"] == "uploads/data.csv"
    assert data["total_rows"] == 3
    assert data["returned_rows"] == 3
    assert not data["truncated"]
    assert [c["name"] for c in data["columns"]] == ["a", "b"]
    assert [c["dtype"] for c in data["columns"]] == ["numeric", "text"]
    assert data["rows"][0] == {"a": 1, "b": "x"}


def test_preview_respects_limit(client: TestClient, viewer_dirs):
    uploads, _, _ = viewer_dirs
    (uploads / "data.csv").write_text(
        "a\n" + "\n".join(str(i) for i in range(50)), encoding="utf-8"
    )

    response = client.get("/datasets/uploads%2Fdata.csv/preview?limit=10")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["returned_rows"] == 10
    assert data["total_rows"] == 50
    assert data["truncated"] is True


def test_preview_caps_limit_at_1000(client: TestClient, viewer_dirs):
    uploads, _, _ = viewer_dirs
    (uploads / "data.csv").write_text("a\n1\n2\n", encoding="utf-8")

    response = client.get("/datasets/uploads%2Fdata.csv/preview?limit=99999")
    assert response.status_code == 200


def test_preview_replaces_nan_with_null(client: TestClient, viewer_dirs):
    uploads, _, _ = viewer_dirs
    (uploads / "data.csv").write_text("a,b\n1,\n2,y\n", encoding="utf-8")

    response = client.get("/datasets/uploads%2Fdata.csv/preview")
    assert response.status_code == 200
    assert response.json()["data"]["rows"][0]["b"] is None


def test_preview_rejects_unknown_dataset(client: TestClient, viewer_dirs):
    response = client.get("/datasets/uploads%2Fmissing.csv/preview")
    assert response.status_code == 404


def test_preview_rejects_unsafe_dataset_id(client: TestClient, viewer_dirs):
    response = client.get("/datasets/..%2Fsecrets.csv/preview")
    assert response.status_code == 404


def test_comparison_lists_completed_runs(client: TestClient, viewer_dirs):
    uploads, _, _ = viewer_dirs
    (uploads / "iris.csv").write_text(
        "sepal_length,sepal_width,species\n"
        "5.1,3.5,setosa\n4.9,3.0,setosa\n4.7,3.2,setosa\n4.6,3.1,setosa\n5.0,3.6,setosa\n5.4,3.9,setosa\n"
        "7.0,3.2,versicolor\n6.4,3.2,versicolor\n6.9,3.1,versicolor\n5.5,2.3,versicolor\n6.5,2.8,versicolor\n6.3,3.3,versicolor\n"
        "6.3,3.3,virginica\n5.8,2.7,virginica\n7.1,3.0,virginica\n6.3,2.9,virginica\n6.5,3.0,virginica\n7.6,3.0,virginica\n",
        encoding="utf-8",
    )
    result = run_model(
        dataset=str(uploads / "iris.csv"),
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=viewer_dirs[2].parent,
    )
    assert result["status"] == "completed"

    response = client.get("/runs/comparison")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] >= 1
    entry = next(r for r in data["runs"] if r["run_id"] == result["run_id"])
    assert entry["model"] == "logistic_regression"
    assert entry["target"] == "species"
    assert entry["validation_status"] == "approved"
    assert "test_accuracy" in entry["metrics"]


def test_comparison_excludes_failed_runs(client: TestClient, viewer_dirs):
    uploads, _, _ = viewer_dirs
    (uploads / "bad.csv").write_text("a,b\n1,x\n", encoding="utf-8")
    result = run_model(
        dataset=str(uploads / "bad.csv"),
        target="missing_target",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=viewer_dirs[2].parent,
    )
    assert result["status"] == "rejected"

    response = client.get("/runs/comparison")
    assert response.status_code == 200
    data = response.json()["data"]
    assert all(r["run_id"] != result["run_id"] for r in data["runs"])


def test_comparison_sanitizes_nan_metrics(client: TestClient, viewer_dirs):
    """A NaN metric must not make Starlette's strict JSON encoder raise (500)."""
    import json

    uploads, _, runs_root = viewer_dirs
    rows = [
        "sepal_length,sepal_width,species",
        *[
            f"{sl},{sw},{sp}"
            for sp, samples in {
                "setosa": [(5.1, 3.5), (4.9, 3.0), (4.7, 3.2), (4.6, 3.1), (5.0, 3.6), (5.4, 3.9)],
                "versicolor": [(7.0, 3.2), (6.4, 3.2), (6.9, 3.1), (5.5, 2.3), (6.5, 2.8), (6.3, 2.2)],
                "virginica": [(6.3, 3.3), (5.8, 2.7), (7.1, 3.0), (6.3, 2.9), (6.5, 3.0), (7.6, 3.0)],
            }.items()
            for sl, sw in samples
        ],
    ]
    (uploads / "iris.csv").write_text("\n".join(rows), encoding="utf-8")
    result = run_model(
        dataset=str(uploads / "iris.csv"),
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=runs_root.parent,
    )
    assert result["status"] == "completed"
    metrics_path = runs_root / result["run_id"] / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["test_r2"] = float("nan")
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")

    response = client.get("/runs/comparison")
    assert response.status_code == 200
    entry = next(r for r in response.json()["data"]["runs"] if r["run_id"] == result["run_id"])
    assert entry["metrics"]["test_r2"] is None
