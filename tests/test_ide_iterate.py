"""Tests for Phase 4 agent iteration endpoint."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thelab.model_service.app import app
from thelab.run.runner import run_model


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def iterate_dirs(tmp_path: Path, monkeypatch):
    uploads = tmp_path / "uploads"
    runs = tmp_path / "runs"
    proposals = tmp_path / "proposals"
    for d in (uploads, runs, proposals):
        d.mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(runs))
    monkeypatch.setenv("THELAB_PROPOSALS_DIR", str(proposals))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    return {"uploads": uploads, "runs": runs, "proposals": proposals, "workspace": tmp_path}


def _write_iris(uploads: Path) -> str:
    rows = ["sepal_length,sepal_width,species"]
    samples = {
        "setosa": [(5.1, 3.5), (4.9, 3.0), (4.7, 3.2), (4.6, 3.1), (5.0, 3.6), (5.4, 3.9)],
        "versicolor": [(7.0, 3.2), (6.4, 3.2), (6.9, 3.1), (5.5, 2.3), (6.5, 2.8), (6.3, 3.3)],
        "virginica": [(6.3, 3.3), (5.8, 2.7), (7.1, 3.0), (6.3, 2.9), (6.5, 3.0), (7.6, 3.0)],
    }
    for species, pairs in samples.items():
        for sl, sw in pairs:
            rows.append(f"{sl},{sw},{species}")
    csv = uploads / "iris.csv"
    csv.write_text("\n".join(rows), encoding="utf-8")
    return "uploads/iris.csv"


def test_iterate_creates_proposal(client: TestClient, iterate_dirs):
    uploads = iterate_dirs["uploads"]
    proposals = iterate_dirs["proposals"]
    workspace = iterate_dirs["workspace"]
    dataset_id = _write_iris(uploads)

    result = run_model(
        dataset=str(uploads / "iris.csv"),
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=workspace,
    )
    assert result["status"] == "completed"
    run_id = result["run_id"]

    response = client.post("/agent/iterate", json={"run_id": run_id})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["proposal_id"]
    assert data["dataset"] == dataset_id
    assert data["target"] == "species"
    assert (proposals / f"{data['proposal_id']}.json").is_file()


def test_iterate_rejects_missing_run(client: TestClient, iterate_dirs):
    response = client.post("/agent/iterate", json={"run_id": "does-not-exist"})
    assert response.status_code == 400


def test_iterate_requires_run_id(client: TestClient, iterate_dirs):
    response = client.post("/agent/iterate", json={})
    assert response.status_code == 400
