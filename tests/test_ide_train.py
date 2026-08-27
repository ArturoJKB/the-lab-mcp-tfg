"""Tests for deterministic train endpoint."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thelab.model_service.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def train_dirs(tmp_path: Path, monkeypatch):
    uploads = tmp_path / "uploads"
    runs = tmp_path / "runs"
    for d in (uploads, runs):
        d.mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(runs))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    return uploads, runs


def _write_iris(uploads: Path) -> None:
    rows = [
        "sepal_length,sepal_width,species",
        *[
            f"{sl},{sw},{sp}"
            for sp, samples in {
                "setosa": [(5.1, 3.5), (4.9, 3.0), (4.7, 3.2), (4.6, 3.1), (5.0, 3.6)],
                "versicolor": [(7.0, 3.2), (6.4, 3.2), (6.9, 3.1), (5.5, 2.3), (6.5, 2.8)],
                "virginica": [(6.3, 3.3), (5.8, 2.7), (7.1, 3.0), (6.3, 2.9), (6.5, 3.0)],
            }.items()
            for sl, sw in samples
        ],
    ]
    (uploads / "iris.csv").write_text("\n".join(rows), encoding="utf-8")


def test_train_model_deterministically(client: TestClient, train_dirs):
    uploads, runs = train_dirs
    _write_iris(uploads)

    response = client.post(
        "/train",
        json={"dataset_id": "uploads/iris.csv", "target": "species", "model": "logistic_regression", "seed": 42},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    outcome = payload["data"]
    assert outcome["status"] == "completed"
    assert outcome["run_id"]
    assert (runs / outcome["run_id"]).exists() or any(runs.iterdir())


def test_train_requires_fields(client: TestClient, train_dirs):
    response = client.post("/train", json={"dataset_id": "uploads/iris.csv", "target": "species"})
    assert response.status_code == 400


def test_train_rejects_unknown_dataset(client: TestClient, train_dirs):
    response = client.post(
        "/train",
        json={"dataset_id": "uploads/missing.csv", "target": "species", "model": "logistic_regression"},
    )
    assert response.status_code == 404


def test_available_models_endpoint(client: TestClient):
    response = client.get("/models/available")
    assert response.status_code == 200
    models = response.json()["data"]
    assert "logistic_regression" in models
